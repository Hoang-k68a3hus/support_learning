from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import ContentHash, Identifier, SchemaModel


class ReviewerKind(StrEnum):
    AI = "AI"
    HUMAN = "HUMAN"


class ReviewOutcome(StrEnum):
    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    CONFLICT = "CONFLICT"
    REJECT = "REJECT"


class ReviewAttempt(SchemaModel):
    reviewer_id: Identifier
    reviewer_kind: ReviewerKind
    guideline_version: str = Field(min_length=1, max_length=128)
    reviewed_at: datetime
    decision_hash_before: ContentHash
    decision_hash_after: ContentHash
    outcome: ReviewOutcome
    notes: str | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def validate_review(self) -> "ReviewAttempt":
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        if (
            not self.guideline_version.strip()
            or self.guideline_version.strip() != self.guideline_version
        ):
            raise ValueError("review guideline_version must be non-blank and trimmed")
        if self.notes is not None and not self.notes.strip():
            raise ValueError("review notes must not be blank")
        if (
            self.outcome == ReviewOutcome.ACCEPT
            and self.decision_hash_before != self.decision_hash_after
        ):
            raise ValueError("ACCEPT review cannot change the decision hash")
        if (
            self.outcome == ReviewOutcome.MODIFY
            and self.decision_hash_before == self.decision_hash_after
        ):
            raise ValueError("MODIFY review must change the decision hash")
        return self
