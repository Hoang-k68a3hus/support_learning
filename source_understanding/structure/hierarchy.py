from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    Confidence,
    ContextNode,
    Identifier,
    SchemaModel,
    StructureMode,
    StructureSource,
)
from source_understanding.schemas.document import DocumentStructure
from source_understanding.schemas.element import Element, ElementType

from .boundary import BoundaryClass, BoundaryDecision, BoundaryReason, BoundarySet
from .signals import StructureSignal, StructureSignalKind, StructureSignalSet


HIERARCHY_VERSION = "1"
HIERARCHY_POLICY_VERSION = "1"

_HIERARCHICAL_NUMBERING_RE = re.compile(r"^\d+(?:\.\d+)+$")
_FLAT_NUMBERING_RE = re.compile(r"^(?:\d+|[A-Za-z]|[IVXLCDMivxlcdm]+)$")


class HierarchyError(ValueError):
    """Hierarchy inputs cannot support a trustworthy context interpretation."""


class HierarchyPolicy(SchemaModel):
    """Conservative, uncalibrated baseline policy recorded with the result."""

    version: str = HIERARCHY_POLICY_VERSION
    explicit_node_confidence: Confidence = 0.95
    inferred_node_confidence: Confidence = 0.75
    derived_node_confidence: Confidence = 0.80
    local_structure_confidence: Confidence = 0.60
    grouped_structure_confidence: Confidence = 0.70
    hierarchical_structure_confidence: Confidence = 0.85
    max_label_length: int = Field(default=2048, ge=1, le=2048)


class ElementContextAssignment(SchemaModel):
    element_id: Identifier
    context_node_ids: tuple[Identifier, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_contexts(self) -> "ElementContextAssignment":
        if len(self.context_node_ids) != len(set(self.context_node_ids)):
            raise ValueError("context_node_ids must be unique")
        return self


class HierarchyResult(SchemaModel):
    version: str = HIERARCHY_VERSION
    element_count: int = Field(ge=1)
    signal_version: str
    boundary_version: str
    policy: HierarchyPolicy
    context_nodes: tuple[ContextNode, ...] = Field(default_factory=tuple)
    assignments: tuple[ElementContextAssignment, ...]
    structure: DocumentStructure

    @model_validator(mode="after")
    def validate_result(self) -> "HierarchyResult":
        if len(self.assignments) != self.element_count:
            raise ValueError("hierarchy assignments must cover every input element")

        node_ids = [node.id for node in self.context_nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("hierarchy context node ids must be unique")
        valid_nodes = set(node_ids)

        assignment_ids = [assignment.element_id for assignment in self.assignments]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("hierarchy assignments must use unique element ids")
        for assignment in self.assignments:
            missing = set(assignment.context_node_ids) - valid_nodes
            if missing:
                raise ValueError(
                    f"hierarchy assignment references unknown context nodes: {sorted(missing)}"
                )

        by_id = {node.id: node for node in self.context_nodes}
        for node in self.context_nodes:
            if node.parent_id is not None:
                parent = by_id.get(node.parent_id)
                if parent is None:
                    raise ValueError(
                        f"context node {node.id!r} references unknown parent {node.parent_id!r}"
                    )
                if (
                    node.level is not None
                    and parent.level is not None
                    and parent.level >= node.level
                ):
                    raise ValueError("context parent level must be shallower than child level")
        return self


@dataclass(frozen=True)
class _ContextCandidate:
    element: Element
    node_type: str
    label: str
    level: int
    source: StructureSource
    confidence: float
    signal_ids: tuple[str, ...]
    level_source: str
    label_truncated: bool


class HierarchyBuilder:
    """Build conservative context nodes without inventing missing hierarchy levels."""

    version: str = HIERARCHY_VERSION

    def __init__(self, policy: HierarchyPolicy | None = None) -> None:
        self._policy = policy if policy is not None else HierarchyPolicy()

    def build(
        self,
        elements: Sequence[Element],
        signal_set: StructureSignalSet,
        boundary_set: BoundarySet,
    ) -> HierarchyResult:
        snapshot = tuple(elements)
        self._validate_inputs(snapshot, signal_set, boundary_set)

        signals_by_element = self._signals_by_element(snapshot, signal_set)
        boundary_before = {
            boundary.right_element_id: boundary for boundary in boundary_set.boundaries
        }

        candidates: dict[str, _ContextCandidate] = {}
        for element in snapshot:
            candidate = self._candidate(
                element,
                signals_by_element[element.id],
                boundary_before.get(element.id),
            )
            if candidate is not None:
                candidates[element.id] = candidate

        nodes: list[ContextNode] = []
        assignments: list[ElementContextAssignment] = []
        stack: list[ContextNode] = []

        for element in snapshot:
            candidate = candidates.get(element.id)
            if candidate is not None:
                while (
                    stack
                    and stack[-1].level is not None
                    and stack[-1].level >= candidate.level
                ):
                    stack.pop()

                parent_id = stack[-1].id if stack else None
                node = self._make_node(candidate, parent_id)
                nodes.append(node)
                stack.append(node)

            assignments.append(
                ElementContextAssignment(
                    element_id=element.id,
                    context_node_ids=tuple(node.id for node in stack),
                )
            )

        structure = self._structure(tuple(nodes), len(snapshot))
        return HierarchyResult(
            element_count=len(snapshot),
            signal_version=signal_set.version,
            boundary_version=boundary_set.version,
            policy=self._policy,
            context_nodes=tuple(nodes),
            assignments=tuple(assignments),
            structure=structure,
        )

    def _candidate(
        self,
        element: Element,
        signals: tuple[StructureSignal, ...],
        incoming_boundary: BoundaryDecision | None,
    ) -> _ContextCandidate | None:
        if element.type not in {ElementType.TITLE, ElementType.HEADING}:
            return None

        type_signal = next(
            signal
            for signal in signals
            if signal.kind == StructureSignalKind.ELEMENT_TYPE
        )

        if incoming_boundary is not None:
            if type_signal.source == StructureSource.EXPLICIT:
                if (
                    incoming_boundary.classification != BoundaryClass.HARD
                    or BoundaryReason.EXPLICIT_STRUCTURE_START
                    not in incoming_boundary.reasons
                ):
                    raise HierarchyError(
                        f"explicit structural element {element.id!r} must start at a "
                        "HARD explicit-structure boundary"
                    )
            elif incoming_boundary.classification not in {
                BoundaryClass.HARD,
                BoundaryClass.SOFT,
            }:
                raise HierarchyError(
                    f"inferred structural element {element.id!r} requires at least "
                    "a SOFT incoming boundary"
                )

        text = element.text
        if text is None or not text.strip():
            return None

        stripped = text.strip()
        label_truncated = len(stripped) > self._policy.max_label_length
        label = stripped[: self._policy.max_label_length]

        numbering_signal = next(
            (
                signal
                for signal in signals
                if signal.kind == StructureSignalKind.NUMBERING_MARKER
            ),
            None,
        )

        if element.type == ElementType.TITLE:
            level = 0
            level_source = "ELEMENT_TYPE"
        elif numbering_signal is not None:
            parsed = self._numbering_level(numbering_signal.text_value)
            level = 1 if parsed is None else parsed
            level_source = "NUMBERING_MARKER"
        else:
            level = 1
            level_source = "DEFAULT_HEADING_LEVEL"

        base_confidence = {
            StructureSource.EXPLICIT: self._policy.explicit_node_confidence,
            StructureSource.INFERRED: self._policy.inferred_node_confidence,
            StructureSource.DERIVED: self._policy.derived_node_confidence,
        }[type_signal.source]
        confidence_values = [base_confidence]
        if type_signal.confidence is not None:
            confidence_values.append(type_signal.confidence)
        if numbering_signal is not None and numbering_signal.confidence is not None:
            confidence_values.append(numbering_signal.confidence)

        supporting_signal_ids = [type_signal.id]
        if numbering_signal is not None:
            supporting_signal_ids.append(numbering_signal.id)
        supporting_signal_ids.extend(
            signal.id
            for signal in signals
            if signal.kind
            in {
                StructureSignalKind.SECTION_MARKER,
                StructureSignalKind.STYLE_BOLD,
                StructureSignalKind.STYLE_FONT_SIZE,
                StructureSignalKind.STYLE_INDENTATION,
            }
            and signal.id not in supporting_signal_ids
        )

        return _ContextCandidate(
            element=element,
            node_type=element.type.value,
            label=label,
            level=level,
            source=type_signal.source,
            confidence=min(confidence_values),
            signal_ids=tuple(supporting_signal_ids),
            level_source=level_source,
            label_truncated=label_truncated,
        )

    @staticmethod
    def _numbering_level(marker: str | None) -> int | None:
        if marker is None:
            return None
        normalized = marker.strip()
        if normalized.endswith((")", ".")):
            normalized = normalized[:-1]
        if _HIERARCHICAL_NUMBERING_RE.fullmatch(normalized):
            return normalized.count(".") + 1
        if _FLAT_NUMBERING_RE.fullmatch(normalized):
            return 1
        return None

    @staticmethod
    def _make_node(
        candidate: _ContextCandidate,
        parent_id: str | None,
    ) -> ContextNode:
        identity = (
            f"{candidate.element.id}|{candidate.node_type}|{candidate.level}|"
            f"{candidate.label}"
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return ContextNode(
            id=f"ctx_{digest}",
            type=candidate.node_type,
            label=candidate.label,
            level=candidate.level,
            source=candidate.source,
            confidence=candidate.confidence,
            parent_id=parent_id,
            attributes={
                "anchor_element_id": candidate.element.id,
                "signal_ids": list(candidate.signal_ids),
                "level_source": candidate.level_source,
                "parent_source": StructureSource.DERIVED.value,
                "label_truncated": candidate.label_truncated,
            },
        )

    def _structure(
        self,
        nodes: tuple[ContextNode, ...],
        element_count: int,
    ) -> DocumentStructure:
        if not nodes:
            return DocumentStructure()

        explicit_ratio = sum(
            node.source == StructureSource.EXPLICIT for node in nodes
        ) / len(nodes)
        nested_ratio = sum(node.parent_id is not None for node in nodes) / len(nodes)
        context_ratio = len(nodes) / element_count
        average_confidence = sum(node.confidence for node in nodes) / len(nodes)

        if len(nodes) == 1:
            mode = StructureMode.LOCAL
            confidence = min(
                self._policy.local_structure_confidence,
                average_confidence,
            )
        elif any(node.parent_id is not None for node in nodes):
            mode = StructureMode.HIERARCHICAL
            confidence = min(
                self._policy.hierarchical_structure_confidence,
                average_confidence,
            )
        else:
            mode = StructureMode.GROUPED
            confidence = min(
                self._policy.grouped_structure_confidence,
                average_confidence,
            )

        return DocumentStructure(
            mode=mode,
            source=StructureSource.DERIVED,
            confidence=confidence,
            signals={
                "context_node_ratio": context_ratio,
                "nested_context_ratio": nested_ratio,
                "explicit_context_ratio": explicit_ratio,
            },
        )

    @staticmethod
    def _signals_by_element(
        elements: tuple[Element, ...],
        signal_set: StructureSignalSet,
    ) -> dict[str, tuple[StructureSignal, ...]]:
        by_element: dict[str, list[StructureSignal]] = {
            element.id: [] for element in elements
        }
        for signal in signal_set.signals:
            for element_id in signal.element_ids:
                by_element[element_id].append(signal)
        return {
            element_id: tuple(signals)
            for element_id, signals in by_element.items()
        }

    @staticmethod
    def _validate_inputs(
        elements: tuple[Element, ...],
        signal_set: StructureSignalSet,
        boundary_set: BoundarySet,
    ) -> None:
        if not elements:
            raise HierarchyError("cannot build hierarchy from empty elements")

        ids = [element.id for element in elements]
        if len(ids) != len(set(ids)):
            raise HierarchyError("hierarchy requires unique element ids")

        orders = [element.order for element in elements]
        if len(orders) != len(set(orders)):
            raise HierarchyError("hierarchy requires unique element order values")
        if orders != sorted(orders):
            raise HierarchyError(
                "hierarchy requires elements in ascending canonical source order"
            )

        if signal_set.element_count != len(elements):
            raise HierarchyError(
                "structure signal element_count does not match hierarchy input elements"
            )
        if boundary_set.element_count != len(elements):
            raise HierarchyError(
                "boundary element_count does not match hierarchy input elements"
            )
        if boundary_set.signal_version != signal_set.version:
            raise HierarchyError(
                "boundary signal_version does not match supplied structure signals"
            )

        positions = {element.id: index for index, element in enumerate(elements)}
        signal_ids = [signal.id for signal in signal_set.signals]
        if len(signal_ids) != len(set(signal_ids)):
            raise HierarchyError("structure signal ids must be unique")

        type_signals: dict[str, list[StructureSignal]] = {
            element.id: [] for element in elements
        }
        for signal in signal_set.signals:
            unknown = set(signal.element_ids) - positions.keys()
            if unknown:
                raise HierarchyError(
                    f"structure signal {signal.id!r} references unknown elements: "
                    f"{sorted(unknown)}"
                )
            if signal.kind == StructureSignalKind.ELEMENT_TYPE:
                if len(signal.element_ids) != 1:
                    raise HierarchyError(
                        "ELEMENT_TYPE signals must reference exactly one element"
                    )
                type_signals[signal.element_ids[0]].append(signal)

        for element in elements:
            matches = type_signals[element.id]
            if len(matches) != 1:
                raise HierarchyError(
                    f"element {element.id!r} must have exactly one ELEMENT_TYPE signal"
                )
            signal = matches[0]
            if signal.text_value != element.type.value:
                raise HierarchyError(
                    f"ELEMENT_TYPE signal disagrees with canonical type for {element.id!r}"
                )
            if signal.source != element.provenance.source:
                raise HierarchyError(
                    f"ELEMENT_TYPE signal provenance disagrees for {element.id!r}"
                )
            if signal.confidence != element.confidence.type:
                raise HierarchyError(
                    f"ELEMENT_TYPE signal confidence disagrees for {element.id!r}"
                )

        if len(boundary_set.boundaries) != max(0, len(elements) - 1):
            raise HierarchyError("boundary count does not match adjacent element pairs")
        for index, boundary in enumerate(boundary_set.boundaries):
            left = elements[index]
            right = elements[index + 1]
            if (
                boundary.left_element_id != left.id
                or boundary.right_element_id != right.id
            ):
                raise HierarchyError(
                    "boundary decisions must follow canonical adjacent element order"
                )
