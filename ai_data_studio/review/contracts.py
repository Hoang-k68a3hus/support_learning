from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from ai_data_studio.schemas import (
    AnnotationDecision,
    ReviewOutcome,
    SemanticWorkingRecord,
    WorkingRecordStatus,
    annotation_decisions_hash,
)
from source_understanding.schemas.context import ContentHash, Identifier, SchemaModel


HUMAN_REVIEW_TASK_SCHEMA_VERSION = "1"
HUMAN_REVIEW_SUBMISSION_SCHEMA_VERSION = "1"


class HumanReviewTask(SchemaModel):
    """Immutable review snapshot exported to a human-review surface."""

    schema_version: str = HUMAN_REVIEW_TASK_SCHEMA_VERSION
    record: SemanticWorkingRecord
    guideline_version: str = Field(min_length=1, max_length=128)
    expected_decision_hash: ContentHash

    @model_validator(mode="after")
    def validate_task(self) -> "HumanReviewTask":
        if self.schema_version != HUMAN_REVIEW_TASK_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported human review task schema_version {self.schema_version!r}"
            )
        if self.record.status != WorkingRecordStatus.REVIEW_REQUIRED:
            raise ValueError("human review tasks require REVIEW_REQUIRED records")
        if (
            not self.guideline_version.strip()
            or self.guideline_version.strip() != self.guideline_version
        ):
            raise ValueError("review task guideline_version must be non-blank and trimmed")
        if self.expected_decision_hash != self.record.decision_hash:
            raise ValueError(
                "review task expected_decision_hash must match the exported record snapshot"
            )
        return self


class HumanReviewSubmission(SchemaModel):
    """Human feedback bound to the exact decision revision that was reviewed."""

    schema_version: str = HUMAN_REVIEW_SUBMISSION_SCHEMA_VERSION
    record_id: Identifier
    batch_id: Identifier
    expected_decision_hash: ContentHash
    reviewer_id: Identifier
    guideline_version: str = Field(min_length=1, max_length=128)
    reviewed_at: datetime
    outcome: ReviewOutcome
    decisions: tuple[AnnotationDecision, ...] | None = None
    notes: str | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def validate_submission(self) -> "HumanReviewSubmission":
        if self.schema_version != HUMAN_REVIEW_SUBMISSION_SCHEMA_VERSION:
            raise ValueError(
                "unsupported human review submission schema_version "
                f"{self.schema_version!r}"
            )
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("review submission reviewed_at must be timezone-aware")
        if (
            not self.guideline_version.strip()
            or self.guideline_version.strip() != self.guideline_version
        ):
            raise ValueError(
                "review submission guideline_version must be non-blank and trimmed"
            )
        if self.notes is not None and not self.notes.strip():
            raise ValueError("review submission notes must not be blank")
        if self.outcome == ReviewOutcome.MODIFY and self.decisions is None:
            raise ValueError("MODIFY review submissions require replacement decisions")
        if self.decisions is not None:
            submitted_hash = annotation_decisions_hash(self.decisions)
            if (
                self.outcome == ReviewOutcome.ACCEPT
                and submitted_hash != self.expected_decision_hash
            ):
                raise ValueError(
                    "ACCEPT review submissions cannot change the expected decision hash"
                )
            if (
                self.outcome == ReviewOutcome.MODIFY
                and submitted_hash == self.expected_decision_hash
            ):
                raise ValueError(
                    "MODIFY review submissions must change the expected decision hash"
                )
        return self
