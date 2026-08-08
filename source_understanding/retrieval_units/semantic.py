from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pydantic import Field, model_validator

from source_understanding.schemas.context import Confidence, Identifier, SchemaModel
from source_understanding.schemas.document import (
    CanonicalDocument,
    SemanticAnnotation,
    SemanticAnnotationType,
)
from source_understanding.schemas.retrieval_unit import AnnotationRef, RetrievalUnit


SEMANTIC_RETRIEVAL_ENRICHER_VERSION = "1"


class SemanticRetrievalEnrichmentError(ValueError):
    """Semantic annotations cannot be projected safely into RetrievalUnits."""


_DEFAULT_ANNOTATION_TYPES = tuple(
    annotation_type
    for annotation_type in SemanticAnnotationType
    if annotation_type != SemanticAnnotationType.CUSTOM
)


class SemanticRetrievalPolicy(SchemaModel):
    """Bounded semantic projection policy; thresholds remain evaluation policy."""

    version: str = Field(default=SEMANTIC_RETRIEVAL_ENRICHER_VERSION, min_length=1, max_length=128)
    enabled: bool = True
    min_confidence: Confidence = 0.75
    max_annotations_per_unit: int = Field(default=6, ge=1, le=64)
    max_semantic_tokens: int | None = Field(default=96, ge=1)
    max_rendered_value_chars: int = Field(default=384, ge=32, le=4096)
    allowed_types: tuple[SemanticAnnotationType, ...] = _DEFAULT_ANNOTATION_TYPES
    include_context_annotations: bool = True
    include_region_annotations: bool = False
    include_subdocument_annotations: bool = False
    respect_existing_max_tokens: bool = True
    semantic_header: str = Field(default="Semantic context:", min_length=1, max_length=256)
    semantic_line_separator: str = "\n"
    semantic_block_separator: str = "\n"

    @model_validator(mode="after")
    def validate_policy(self) -> "SemanticRetrievalPolicy":
        if len(self.allowed_types) != len(set(self.allowed_types)):
            raise ValueError("allowed_types must be unique")
        for name in ("semantic_line_separator", "semantic_block_separator"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        return self


class SemanticRetrievalResult(SchemaModel):
    version: str = SEMANTIC_RETRIEVAL_ENRICHER_VERSION
    document_id: Identifier
    policy: SemanticRetrievalPolicy
    source_unit_count: int = Field(ge=0)
    enriched_unit_count: int = Field(ge=0)
    units: tuple[RetrievalUnit, ...] = Field(default_factory=tuple)
    referenced_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    rendered_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_low_confidence_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_disallowed_type_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_budget_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_result(self) -> "SemanticRetrievalResult":
        unit_ids = [unit.id for unit in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("semantic retrieval output unit ids must be unique")
        if self.enriched_unit_count > self.source_unit_count:
            raise ValueError("enriched_unit_count cannot exceed source_unit_count")
        for name in (
            "referenced_annotation_ids",
            "rendered_annotation_ids",
            "skipped_low_confidence_annotation_ids",
            "skipped_disallowed_type_annotation_ids",
            "skipped_budget_annotation_ids",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        return self


@dataclass(frozen=True, slots=True)
class _Candidate:
    annotation: SemanticAnnotation
    scope: str
    scope_rank: int
    document_order: int


class SemanticRetrievalEnricher:
    """Attach and optionally render relevant semantic annotations for retrieval.

    The canonical source remains authoritative. Semantic text is retrieval-only:
    display text and source anchors are preserved byte-for-byte/model-for-model.
    """

    version: str = SEMANTIC_RETRIEVAL_ENRICHER_VERSION

    def __init__(
        self,
        token_counter: Callable[[str], int],
        policy: SemanticRetrievalPolicy | None = None,
    ) -> None:
        if not callable(token_counter):
            raise TypeError("token_counter must be callable")
        self._token_counter = token_counter
        self._policy = policy if policy is not None else SemanticRetrievalPolicy()

    def enrich(
        self,
        document: CanonicalDocument,
        units: Iterable[RetrievalUnit],
    ) -> SemanticRetrievalResult:
        source_units = tuple(units)
        for unit in source_units:
            self._validate_base_unit(document, unit)

        if not self._policy.enabled:
            return SemanticRetrievalResult(
                document_id=document.document_id,
                policy=self._policy,
                source_unit_count=len(source_units),
                enriched_unit_count=0,
                units=source_units,
            )

        annotation_order = {
            annotation.id: index
            for index, annotation in enumerate(document.semantic_annotations)
        }
        type_rank = {
            annotation_type: index
            for index, annotation_type in enumerate(self._policy.allowed_types)
        }
        region_members = {
            region.id: frozenset(region.element_ids)
            for region in document.regions
        }

        output: list[RetrievalUnit] = []
        referenced: list[str] = []
        rendered: list[str] = []
        skipped_low_confidence: list[str] = []
        skipped_disallowed: list[str] = []
        skipped_budget: list[str] = []
        enriched_count = 0

        for unit in source_units:
            candidates, low_ids, disallowed_ids = self._candidates_for_unit(
                document,
                unit,
                annotation_order,
                type_rank,
                region_members,
            )
            skipped_low_confidence.extend(low_ids)
            skipped_disallowed.extend(disallowed_ids)

            selected = self._select_candidates(candidates)
            if not selected:
                output.append(unit)
                continue

            enriched, rendered_ids, budget_ids = self._enrich_unit(
                document,
                unit,
                selected,
            )
            output.append(enriched)
            enriched_count += 1
            referenced.extend(candidate.annotation.id for candidate in selected)
            rendered.extend(rendered_ids)
            skipped_budget.extend(budget_ids)

        return SemanticRetrievalResult(
            document_id=document.document_id,
            policy=self._policy,
            source_unit_count=len(source_units),
            enriched_unit_count=enriched_count,
            units=tuple(output),
            referenced_annotation_ids=self._unique(referenced),
            rendered_annotation_ids=self._unique(rendered),
            skipped_low_confidence_annotation_ids=self._unique(skipped_low_confidence),
            skipped_disallowed_type_annotation_ids=self._unique(skipped_disallowed),
            skipped_budget_annotation_ids=self._unique(skipped_budget),
        )

    def _validate_base_unit(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
    ) -> None:
        try:
            unit.validate_against_document(document)
        except ValueError as exc:
            raise SemanticRetrievalEnrichmentError(
                f"base retrieval unit {unit.id!r} is invalid for canonical document: {exc}"
            ) from exc
        if unit.metadata.get("semantic_enricher_version") is not None:
            raise SemanticRetrievalEnrichmentError(
                f"retrieval unit {unit.id!r} is already semantic-enriched; "
                "rebuild base RetrievalUnits before re-enrichment"
            )

    def _candidates_for_unit(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
        annotation_order: dict[str, int],
        type_rank: dict[SemanticAnnotationType, int],
        region_members: dict[str, frozenset[str]],
    ) -> tuple[list[_Candidate], list[str], list[str]]:
        relevant: list[tuple[SemanticAnnotation, str, int]] = []
        element_ids = frozenset(unit.element_ids)
        logical_ids = frozenset(unit.logical_unit_ids)
        context_ids = frozenset(ref.id for ref in unit.context_path)

        for annotation in document.semantic_annotations:
            scope = self._annotation_scope(
                annotation.target_id,
                unit,
                element_ids,
                logical_ids,
                context_ids,
                region_members,
            )
            if scope is None:
                continue
            relevant.append((annotation, scope[0], scope[1]))

        low_confidence: list[str] = []
        disallowed: list[str] = []
        candidates: list[_Candidate] = []
        for annotation, scope_name, scope_rank in relevant:
            if annotation.type not in type_rank:
                disallowed.append(annotation.id)
                continue
            if annotation.confidence < self._policy.min_confidence:
                low_confidence.append(annotation.id)
                continue
            candidates.append(
                _Candidate(
                    annotation=annotation,
                    scope=scope_name,
                    scope_rank=scope_rank,
                    document_order=annotation_order[annotation.id],
                )
            )

        candidates.sort(
            key=lambda candidate: (
                candidate.scope_rank,
                -candidate.annotation.confidence,
                type_rank[candidate.annotation.type],
                candidate.document_order,
                candidate.annotation.id,
            )
        )
        return candidates, low_confidence, disallowed

    def _annotation_scope(
        self,
        target_id: str,
        unit: RetrievalUnit,
        element_ids: frozenset[str],
        logical_ids: frozenset[str],
        context_ids: frozenset[str],
        region_members: dict[str, frozenset[str]],
    ) -> tuple[str, int] | None:
        if target_id in element_ids:
            return "ELEMENT", 0
        if target_id in logical_ids:
            return "LOGICAL_UNIT", 1
        if self._policy.include_context_annotations and target_id in context_ids:
            return "CONTEXT", 2
        if self._policy.include_region_annotations:
            members = region_members.get(target_id)
            if members is not None and element_ids.issubset(members):
                return "REGION", 3
        if (
            self._policy.include_subdocument_annotations
            and unit.subdocument_id is not None
            and target_id == unit.subdocument_id
        ):
            return "SUBDOCUMENT", 4
        return None

    def _select_candidates(self, candidates: list[_Candidate]) -> tuple[_Candidate, ...]:
        unique: list[_Candidate] = []
        seen_semantics: set[tuple[SemanticAnnotationType, str]] = set()
        for candidate in candidates:
            semantic_key = (
                candidate.annotation.type,
                self._compact_value(candidate.annotation.value).casefold(),
            )
            if semantic_key in seen_semantics:
                continue
            seen_semantics.add(semantic_key)
            unique.append(candidate)
            if len(unique) >= self._policy.max_annotations_per_unit:
                break
        return tuple(unique)

    def _enrich_unit(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
        selected: tuple[_Candidate, ...],
    ) -> tuple[RetrievalUnit, tuple[str, ...], tuple[str, ...]]:
        rendered_candidates: list[_Candidate] = []
        budget_skipped: list[str] = []
        retrieval_text = unit.retrieval_text
        token_count = unit.token_count
        existing_max_tokens = self._existing_max_tokens(unit)

        for candidate in selected:
            proposed_candidates = (*rendered_candidates, candidate)
            semantic_block = self._semantic_block(proposed_candidates)
            if (
                self._policy.max_semantic_tokens is not None
                and self._count_tokens(semantic_block) > self._policy.max_semantic_tokens
            ):
                budget_skipped.append(candidate.annotation.id)
                continue

            proposed_text = (
                semantic_block
                + self._policy.semantic_block_separator
                + unit.retrieval_text
            )
            proposed_count = self._count_tokens(proposed_text)
            if existing_max_tokens is not None and proposed_count > existing_max_tokens:
                budget_skipped.append(candidate.annotation.id)
                continue

            rendered_candidates.append(candidate)
            retrieval_text = proposed_text
            token_count = proposed_count

        refs = self._merge_annotation_refs(unit, selected)
        rendered_ids = tuple(
            candidate.annotation.id for candidate in rendered_candidates
        )
        selected_ids = tuple(candidate.annotation.id for candidate in selected)
        target_scopes = {
            candidate.annotation.id: candidate.scope for candidate in selected
        }

        metadata = dict(unit.metadata)
        metadata.update(
            {
                "semantic_enrichment_used": bool(rendered_ids),
                "semantic_enricher_version": self.version,
                "semantic_policy_version": self._policy.version,
                "semantic_min_confidence": self._policy.min_confidence,
                "semantic_annotation_count": len(selected_ids),
                "semantic_annotation_ids": list(selected_ids),
                "semantic_rendered_annotation_ids": list(rendered_ids),
                "semantic_skipped_budget_annotation_ids": list(budget_skipped),
                "semantic_annotation_target_scopes": target_scopes,
                "semantic_context_is_source_fact": False,
                "base_retrieval_unit_id": unit.id,
            }
        )

        enriched_id = self._unit_id(
            document,
            unit,
            selected_ids,
            rendered_ids,
            retrieval_text,
        )
        version = f"{unit.version}+sem{self.version}"
        payload = unit.model_dump(mode="python")
        payload.update(
            {
                "id": enriched_id,
                "retrieval_text": retrieval_text,
                "semantic_annotations": refs,
                "token_count": token_count,
                "version": version,
                "metadata": metadata,
            }
        )
        enriched = RetrievalUnit(**payload)
        try:
            enriched.validate_against_document(document)
        except ValueError as exc:
            raise SemanticRetrievalEnrichmentError(
                f"semantic retrieval unit {enriched.id!r} failed canonical validation: {exc}"
            ) from exc
        return enriched, rendered_ids, tuple(budget_skipped)

    def _merge_annotation_refs(
        self,
        unit: RetrievalUnit,
        selected: tuple[_Candidate, ...],
    ) -> tuple[AnnotationRef, ...]:
        refs = list(unit.semantic_annotations)
        existing_ids = {ref.id for ref in refs}
        for candidate in selected:
            annotation = candidate.annotation
            if annotation.id in existing_ids:
                continue
            refs.append(
                AnnotationRef(
                    id=annotation.id,
                    type=annotation.type.value,
                    value=annotation.value if len(annotation.value) <= 2048 else None,
                    source=annotation.source,
                    confidence=annotation.confidence,
                )
            )
            existing_ids.add(annotation.id)
        return tuple(refs)

    def _semantic_block(self, candidates: tuple[_Candidate, ...]) -> str:
        lines = [self._policy.semantic_header]
        lines.extend(self._render_annotation(candidate.annotation) for candidate in candidates)
        return self._policy.semantic_line_separator.join(lines)

    def _render_annotation(self, annotation: SemanticAnnotation) -> str:
        label = annotation.type.value.replace("_", " ").title()
        value = self._compact_value(annotation.value)
        max_chars = self._policy.max_rendered_value_chars
        if len(value) > max_chars:
            value = value[: max_chars - 1].rstrip() + "…"
        return f"{label}: {value}"

    @staticmethod
    def _compact_value(value: str) -> str:
        return " ".join(value.split())

    def _existing_max_tokens(self, unit: RetrievalUnit) -> int | None:
        if not self._policy.respect_existing_max_tokens:
            return None
        value = unit.metadata.get("max_tokens")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
        return value

    def _count_tokens(self, text: str) -> int:
        count = self._token_counter(text)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise SemanticRetrievalEnrichmentError(
                "token_counter must return a positive integer for non-blank retrieval text"
            )
        return count

    def _unit_id(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
        annotation_ids: tuple[str, ...],
        rendered_ids: tuple[str, ...],
        retrieval_text: str,
    ) -> str:
        payload = {
            "enricher_version": self.version,
            "policy": self._policy.model_dump(mode="json"),
            "document_id": document.document_id,
            "content_hash": document.content_hash,
            "source_revision": document.source_revision,
            "base_unit_id": unit.id,
            "annotation_ids": annotation_ids,
            "rendered_ids": rendered_ids,
            "retrieval_text": retrieval_text,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()[:32]
        return f"ru_{digest}"

    @staticmethod
    def _unique(values: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))
