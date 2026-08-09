from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    ContentHash,
    Identifier,
    JsonObject,
    SchemaModel,
)
from source_understanding.schemas.document import SemanticAnnotationType
from source_understanding.semantics.provider import SemanticTargetKind

from .decision import (
    AnnotationDecision,
    AnnotationDecisionState,
    AnnotationSuggestion,
    annotation_decisions_hash,
)
from .review import ReviewAttempt, ReviewOutcome


WORKING_RECORD_SCHEMA_VERSION = "1"


class WorkingRecordStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PASS = "PASS"
    REJECT = "REJECT"


class WorkingSourceSnapshot(SchemaModel):
    document_id: Identifier
    content_hash: ContentHash
    element_snapshot_hash: ContentHash
    language: str = Field(min_length=2, max_length=64)
    source_family_id: Identifier
    split_group_id: Identifier

    @model_validator(mode="after")
    def validate_language(self) -> "WorkingSourceSnapshot":
        if not self.language.strip() or self.language.strip() != self.language:
            raise ValueError("working source language must be non-blank and trimmed")
        return self


class WorkingTarget(SchemaModel):
    target_id: Identifier
    target_kind: SemanticTargetKind
    element_ids: tuple[Identifier, ...] = Field(min_length=1)
    element_orders: tuple[int, ...] = Field(min_length=1)
    raw_text: str | None = Field(default=None, max_length=32768)
    normalized_text: str | None = Field(default=None, max_length=32768)
    logical_unit_type: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_target(self) -> "WorkingTarget":
        if len(self.element_ids) != len(set(self.element_ids)):
            raise ValueError("working target element_ids must be unique")
        if len(self.element_orders) != len(set(self.element_orders)):
            raise ValueError("working target element_orders must be unique")
        if len(self.element_ids) != len(self.element_orders):
            raise ValueError(
                "working target element_ids and element_orders must align one-to-one"
            )
        if any(order < 0 for order in self.element_orders):
            raise ValueError("working target element_orders must be non-negative")
        if self.element_orders != tuple(sorted(self.element_orders)):
            raise ValueError("working target element_orders must follow canonical order")
        if self.target_kind == SemanticTargetKind.ELEMENT and len(self.element_ids) != 1:
            raise ValueError("ELEMENT working targets require exactly one element")
        if (
            self.logical_unit_type is not None
            and (
                not self.logical_unit_type.strip()
                or self.logical_unit_type.strip() != self.logical_unit_type
            )
        ):
            raise ValueError("working target logical_unit_type must be non-blank and trimmed")
        return self


class SemanticWorkingRecord(SchemaModel):
    schema_version: str = WORKING_RECORD_SCHEMA_VERSION
    record_id: Identifier
    batch_id: Identifier
    source: WorkingSourceSnapshot
    target: WorkingTarget
    evaluated_types: tuple[SemanticAnnotationType, ...] = Field(min_length=1)
    suggestions: tuple[AnnotationSuggestion, ...] = Field(default_factory=tuple)
    decisions: tuple[AnnotationDecision, ...] = Field(default_factory=tuple)
    reviews: tuple[ReviewAttempt, ...] = Field(default_factory=tuple)
    status: WorkingRecordStatus = WorkingRecordStatus.DRAFT
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_record(self) -> "SemanticWorkingRecord":
        if self.schema_version != WORKING_RECORD_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported working record schema_version {self.schema_version!r}"
            )
        if len(self.evaluated_types) != len(set(self.evaluated_types)):
            raise ValueError("working record evaluated_types must be unique")
        canonical_types = tuple(
            annotation_type
            for annotation_type in SemanticAnnotationType
            if annotation_type in self.evaluated_types
        )
        if self.evaluated_types != canonical_types:
            raise ValueError(
                "working record evaluated_types must use canonical semantic order"
            )
        evaluated_set = set(self.evaluated_types)
        suggestion_types = {item.annotation_type for item in self.suggestions}
        if not suggestion_types.issubset(evaluated_set):
            raise ValueError(
                "working record suggestions must target evaluated annotation types"
            )
        decision_types = tuple(item.annotation_type for item in self.decisions)
        if len(decision_types) != len(set(decision_types)):
            raise ValueError("working record allows one decision per annotation type")
        if not set(decision_types).issubset(evaluated_set):
            raise ValueError(
                "working record decisions must target evaluated annotation types"
            )
        canonical_decisions = tuple(
            annotation_type
            for annotation_type in self.evaluated_types
            if annotation_type in decision_types
        )
        if decision_types != canonical_decisions:
            raise ValueError(
                "working record decisions must follow evaluated_types order"
            )
        review_times = tuple(item.reviewed_at for item in self.reviews)
        if review_times != tuple(sorted(review_times)):
            raise ValueError("working record reviews must be chronological")

        if self.status == WorkingRecordStatus.PASS:
            if set(decision_types) != evaluated_set:
                raise ValueError(
                    "PASS working records require one decision for every evaluated type"
                )
            if any(
                item.state == AnnotationDecisionState.UNDECIDED
                for item in self.decisions
            ):
                raise ValueError("PASS working records cannot contain UNDECIDED decisions")
            if self.reviews and self.reviews[-1].outcome in {
                ReviewOutcome.CONFLICT,
                ReviewOutcome.REJECT,
            }:
                raise ValueError(
                    "PASS working records cannot have an unresolved review outcome"
                )
        return self

    @property
    def decision_hash(self) -> ContentHash:
        return annotation_decisions_hash(self.decisions)

