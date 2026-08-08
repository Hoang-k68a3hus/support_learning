from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from source_understanding.schemas.context import Confidence, JsonObject, SchemaModel, StructureSource
from source_understanding.schemas.element import Element, ElementType
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType

from .grouping import GroupingResult

if TYPE_CHECKING:
    from .boundary import BoundarySet


INTEGRITY_CONSOLIDATION_VERSION = "1"
INTEGRITY_CONSOLIDATION_POLICY_VERSION = "1"


class IntegrityConsolidationError(ValueError):
    """Existing grouping cannot be consolidated without changing trusted membership."""


@dataclass(frozen=True, slots=True)
class _Family:
    name: str
    element_types: frozenset[ElementType]
    unit_type: LogicalUnitType
    container_types: frozenset[ElementType] = frozenset()


_FAMILIES = (
    _Family(
        "table",
        frozenset({ElementType.TABLE, ElementType.TABLE_ROW, ElementType.TABLE_CELL}),
        LogicalUnitType.TABLE_BLOCK,
        frozenset({ElementType.TABLE}),
    ),
    _Family(
        "list",
        frozenset({ElementType.LIST, ElementType.LIST_ITEM}),
        LogicalUnitType.LIST_GROUP,
        frozenset({ElementType.LIST}),
    ),
    _Family("code", frozenset({ElementType.CODE}), LogicalUnitType.CODE_BLOCK),
    _Family("formula", frozenset({ElementType.FORMULA}), LogicalUnitType.TEXT_BLOCK),
    _Family("key_value", frozenset({ElementType.KEY_VALUE}), LogicalUnitType.KEY_VALUE_GROUP),
)
_TYPE_TO_FAMILY = {
    element_type: family
    for family in _FAMILIES
    for element_type in family.element_types
}


class IntegrityConsolidationPolicy(SchemaModel):
    version: str = INTEGRITY_CONSOLIDATION_POLICY_VERSION
    confidence: Confidence = 0.92
    merge_across_soft_boundaries: bool = True
    merge_across_unknown_boundaries: bool = True
    split_on_repeated_container: bool = True


class IntegrityConsolidationReport(SchemaModel):
    version: str = INTEGRITY_CONSOLIDATION_VERSION
    element_count: int = Field(ge=1)
    policy: IntegrityConsolidationPolicy
    consolidated_unit_ids: tuple[str, ...] = Field(default_factory=tuple)
    family_counts: JsonObject = Field(default_factory=dict)
    replaced_unit_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_ids(self) -> "IntegrityConsolidationReport":
        if len(self.consolidated_unit_ids) != len(set(self.consolidated_unit_ids)):
            raise ValueError("consolidated_unit_ids must be unique")
        if len(self.replaced_unit_ids) != len(set(self.replaced_unit_ids)):
            raise ValueError("replaced_unit_ids must be unique")
        return self


def unresolved_integrity_boundary_ids(
    boundary_set: "BoundarySet",
    grouping_result: GroupingResult,
) -> tuple[str, ...]:
    """Return integrity-warning boundaries not resolved by one LogicalUnit.

    Boundary scoring intentionally marks uncertain same-family adjacency before
    grouping. Once grouping/consolidation places both adjacent elements in the
    same LogicalUnit, that warning is structurally resolved and must not continue
    to depress document-quality diagnostics.
    """

    owners: dict[str, str] = {}
    for unit in grouping_result.logical_units:
        for element_id in unit.element_ids:
            previous = owners.get(element_id)
            if previous is not None and previous != unit.id:
                raise IntegrityConsolidationError(
                    f"element {element_id!r} belongs to multiple logical units"
                )
            owners[element_id] = unit.id

    unresolved: list[str] = []
    for boundary in boundary_set.boundaries:
        reason_values = {
            getattr(reason, "value", str(reason))
            for reason in getattr(boundary, "reasons", ())
        }
        if "CONTENT_INTEGRITY_UNRESOLVED" not in reason_values:
            continue
        left_owner = owners.get(boundary.left_element_id)
        right_owner = owners.get(boundary.right_element_id)
        if left_owner is None or left_owner != right_owner:
            unresolved.append(boundary.id)
    return tuple(unresolved)


class IntegrityGroupConsolidator:
    """Preserve native multi-element table/list/code/formula/key-value integrity."""

    version = INTEGRITY_CONSOLIDATION_VERSION

    def __init__(self, policy: IntegrityConsolidationPolicy | None = None) -> None:
        self._policy = policy if policy is not None else IntegrityConsolidationPolicy()

    @property
    def policy(self) -> IntegrityConsolidationPolicy:
        return self._policy

    def consolidate(
        self,
        elements: Sequence[Element],
        boundary_set: "BoundarySet",
        grouping_result: GroupingResult,
    ) -> tuple[GroupingResult, IntegrityConsolidationReport]:
        snapshot = tuple(elements)
        self._validate_inputs(snapshot, boundary_set, grouping_result)
        spans = self._integrity_spans(snapshot, boundary_set)
        if not spans:
            return grouping_result, IntegrityConsolidationReport(
                element_count=len(snapshot),
                policy=self._policy,
            )

        by_id = {element.id: element for element in snapshot}
        order = {element.id: index for index, element in enumerate(snapshot)}
        existing = list(grouping_result.logical_units)
        replaced: list[str] = []
        created: list[LogicalUnit] = []
        family_counts: Counter[str] = Counter()

        for family, member_ids, boundary_ids, boundary_classes in spans:
            member_set = set(member_ids)
            overlapping = [
                unit for unit in existing if member_set.intersection(unit.element_ids)
            ]
            for unit in overlapping:
                outside = set(unit.element_ids) - member_set
                if outside:
                    raise IntegrityConsolidationError(
                        f"logical unit {unit.id!r} crosses {family.name!r} integrity span"
                    )
            if overlapping:
                replaced.extend(unit.id for unit in overlapping)
                existing = [unit for unit in existing if unit not in overlapping]

            created.append(
                self._make_unit(
                    family,
                    member_ids,
                    by_id,
                    overlapping,
                    boundary_ids,
                    boundary_classes,
                )
            )
            family_counts[family.name] += 1

        units = [*existing, *created]
        units.sort(key=lambda unit: order[unit.element_ids[0]])
        consolidated_members = {
            element_id for unit in created for element_id in unit.element_ids
        }
        ungrouped = tuple(
            element_id
            for element_id in grouping_result.ungrouped_element_ids
            if element_id not in consolidated_members
        )
        data = grouping_result.model_dump(mode="python")
        data["logical_units"] = tuple(units)
        data["ungrouped_element_ids"] = ungrouped
        consolidated = GroupingResult.model_validate(data)
        report = IntegrityConsolidationReport(
            element_count=len(snapshot),
            policy=self._policy,
            consolidated_unit_ids=tuple(unit.id for unit in created),
            family_counts=dict(sorted(family_counts.items())),
            replaced_unit_ids=tuple(dict.fromkeys(replaced)),
        )
        return consolidated, report

    def _integrity_spans(
        self,
        elements: tuple[Element, ...],
        boundary_set: "BoundarySet",
    ) -> tuple[tuple[_Family, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...]:
        spans = []
        index = 0
        while index < len(elements):
            family = _TYPE_TO_FAMILY.get(elements[index].type)
            if family is None:
                index += 1
                continue
            members = [elements[index].id]
            boundary_ids: list[str] = []
            boundary_classes: list[str] = []
            seen_container = elements[index].type in family.container_types
            cursor = index + 1
            while cursor < len(elements):
                candidate = elements[cursor]
                if candidate.type not in family.element_types:
                    break
                boundary = boundary_set.boundaries[cursor - 1]
                if not self._can_cross(boundary.classification):
                    break
                is_container = candidate.type in family.container_types
                if (
                    self._policy.split_on_repeated_container
                    and is_container
                    and seen_container
                ):
                    break
                seen_container = seen_container or is_container
                members.append(candidate.id)
                boundary_ids.append(boundary.id)
                boundary_classes.append(
                    getattr(boundary.classification, "value", str(boundary.classification))
                )
                cursor += 1
            spans.append(
                (
                    family,
                    tuple(members),
                    tuple(boundary_ids),
                    tuple(boundary_classes),
                )
            )
            index = cursor
        return tuple(spans)

    def _can_cross(self, boundary_class: Any) -> bool:
        value = getattr(boundary_class, "value", str(boundary_class))
        if value == "HARD":
            return False
        if value == "SOFT":
            return self._policy.merge_across_soft_boundaries
        if value == "UNKNOWN":
            return self._policy.merge_across_unknown_boundaries
        return True

    def _make_unit(
        self,
        family: _Family,
        member_ids: tuple[str, ...],
        by_id: dict[str, Element],
        replaced_units: list[LogicalUnit],
        boundary_ids: tuple[str, ...],
        boundary_classes: tuple[str, ...],
    ) -> LogicalUnit:
        confidences = [self._policy.confidence]
        confidences.extend(unit.confidence for unit in replaced_units)
        for element_id in member_ids:
            element = by_id[element_id]
            if element.confidence.type is not None:
                confidences.append(element.confidence.type)
            elif element.provenance.confidence is not None:
                confidences.append(element.provenance.confidence)
        digest = hashlib.sha256(
            "|".join((family.name, family.unit_type.value, *member_ids)).encode("utf-8")
        ).hexdigest()[:20]
        return LogicalUnit(
            id=f"lu_{digest}",
            type=family.unit_type,
            element_ids=member_ids,
            source=StructureSource.DERIVED,
            confidence=min(confidences),
            metadata={
                "grouping_rule": "contiguous_integrity_family",
                "integrity_family": family.name,
                "replaced_unit_ids": [unit.id for unit in replaced_units],
                "boundary_ids": list(boundary_ids),
                "boundary_classes": list(boundary_classes),
                "token_target_used": False,
                "confidence_policy": "uncalibrated_baseline_capped_by_upstream",
            },
        )

    @staticmethod
    def _validate_inputs(
        elements: tuple[Element, ...],
        boundary_set: "BoundarySet",
        grouping_result: GroupingResult,
    ) -> None:
        if not elements:
            raise IntegrityConsolidationError("cannot consolidate an empty element sequence")
        if boundary_set.element_count != len(elements):
            raise IntegrityConsolidationError("boundary element_count does not match integrity input")
        if grouping_result.element_count != len(elements):
            raise IntegrityConsolidationError("grouping element_count does not match integrity input")
        ids = [element.id for element in elements]
        if len(ids) != len(set(ids)):
            raise IntegrityConsolidationError("integrity consolidation requires unique element ids")
        if len(boundary_set.boundaries) != max(0, len(elements) - 1):
            raise IntegrityConsolidationError("boundary count does not match canonical adjacency")
        for index, boundary in enumerate(boundary_set.boundaries):
            if (
                boundary.left_element_id != elements[index].id
                or boundary.right_element_id != elements[index + 1].id
            ):
                raise IntegrityConsolidationError(
                    f"boundary {boundary.id!r} does not match canonical adjacency"
                )
