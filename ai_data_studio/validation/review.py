from __future__ import annotations

from collections.abc import Sequence

from source_understanding.schemas.context import ContentHash, Identifier

from ai_data_studio.schemas.review import ReviewAttempt

from .issues import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationSeverity,
)


def validate_review_chain(
    *,
    reviews: Sequence[ReviewAttempt],
    current_decision_hash: ContentHash,
    record_id: Identifier | None = None,
) -> tuple[ValidationIssue, ...]:
    if not reviews:
        return ()
    issues: list[ValidationIssue] = []
    for index in range(1, len(reviews)):
        previous = reviews[index - 1]
        current = reviews[index]
        if previous.decision_hash_after != current.decision_hash_before:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.REVIEW_CHAIN_BROKEN,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Review {index - 1} terminal hash does not match "
                        f"review {index} initial hash."
                    ),
                    record_id=record_id,
                    path=f"reviews[{index}].decision_hash_before",
                    related_ids=tuple(
                        dict.fromkeys(
                            (previous.reviewer_id, current.reviewer_id)
                        )
                    ),
                )
            )
    if reviews[-1].decision_hash_after != current_decision_hash:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.REVIEW_FINAL_HASH_MISMATCH,
                severity=ValidationSeverity.ERROR,
                message=(
                    "Final review hash does not match the record's current "
                    "decision hash."
                ),
                record_id=record_id,
                path=f"reviews[{len(reviews) - 1}].decision_hash_after",
                related_ids=(reviews[-1].reviewer_id,),
            )
        )
    return tuple(issues)


def validate_review_guideline(
    *,
    reviews: Sequence[ReviewAttempt],
    batch_guideline_version: str,
    record_id: Identifier | None = None,
) -> tuple[ValidationIssue, ...]:
    if not reviews or reviews[-1].guideline_version == batch_guideline_version:
        return ()
    return (
        ValidationIssue(
            code=ValidationIssueCode.REVIEW_GUIDELINE_MISMATCH,
            severity=ValidationSeverity.ERROR,
            message=(
                f"Final review guideline {reviews[-1].guideline_version!r} does "
                f"not match batch guideline {batch_guideline_version!r}."
            ),
            record_id=record_id,
            path=f"reviews[{len(reviews) - 1}].guideline_version",
            related_ids=(reviews[-1].reviewer_id,),
        ),
    )
