from __future__ import annotations

import unittest
from datetime import timedelta

from ai_data_studio.schemas import (
    AnnotationDecision,
    AnnotationDecisionState,
    AdjudicationConfidence,
    ReviewAttempt,
    ReviewerKind,
    ReviewOutcome,
)
from ai_data_studio.validation import ValidationIssueCode, WorkingRecordValidator
from source_understanding.schemas.document import SemanticAnnotationType

from tests.ai_data_studio._validation_fixtures import (
    NOW,
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
)


H0 = "sha256:" + "b" * 64
H1 = "sha256:" + "c" * 64
H2 = "sha256:" + "d" * 64


def review(
    *,
    before: str,
    after: str,
    index: int,
    guideline: str = "roles-v1",
) -> ReviewAttempt:
    return ReviewAttempt(
        reviewer_id=f"reviewer-{index}",
        reviewer_kind=ReviewerKind.HUMAN,
        guideline_version=guideline,
        reviewed_at=NOW + timedelta(minutes=index),
        decision_hash_before=before,
        decision_hash_after=after,
        outcome=(
            ReviewOutcome.ACCEPT if before == after else ReviewOutcome.MODIFY
        ),
    )


class ReviewChainValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = canonical_document()
        self.batch = working_batch()
        self.validator = WorkingRecordValidator()

    def codes(self, record) -> tuple[ValidationIssueCode, ...]:
        report = self.validator.validate(
            record=record,
            document=self.document,
            batch=self.batch,
        )
        return tuple(issue.code for issue in report.issues)

    def test_empty_review_chain_is_valid(self) -> None:
        self.assertTrue(
            self.validator.validate(
                record=working_record(self.document),
                document=self.document,
                batch=self.batch,
            ).is_valid
        )

    def test_single_review_terminal_hash_matches(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        accepted = review(
            before=record.decision_hash,
            after=record.decision_hash,
            index=0,
        )
        record = record.model_copy(update={"reviews": (accepted,)})

        self.assertTrue(
            self.validator.validate(
                record=record,
                document=self.document,
                batch=self.batch,
            ).is_valid
        )

    def test_multiple_reviews_form_continuous_chain(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        first = review(before=H0, after=H1, index=0, guideline="roles-v0")
        final = review(
            before=H1,
            after=record.decision_hash,
            index=1,
        )
        record = record.model_copy(update={"reviews": (first, final)})

        self.assertTrue(
            self.validator.validate(
                record=record,
                document=self.document,
                batch=self.batch,
            ).is_valid
        )

    def test_review_after_before_mismatch_rejected(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        first = review(before=H0, after=H1, index=0)
        final = review(
            before=H2,
            after=record.decision_hash,
            index=1,
        )
        record = record.model_copy(update={"reviews": (first, final)})

        self.assertIn(ValidationIssueCode.REVIEW_CHAIN_BROKEN, self.codes(record))

    def test_final_review_hash_must_equal_current_decision_hash(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        accepted = review(before=H1, after=H1, index=0)
        record = record.model_copy(update={"reviews": (accepted,)})

        self.assertIn(
            ValidationIssueCode.REVIEW_FINAL_HASH_MISMATCH,
            self.codes(record),
        )

    def test_decisions_changed_after_review_are_detected(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        accepted = review(
            before=record.decision_hash,
            after=record.decision_hash,
            index=0,
        )
        changed_decision = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.NOT_APPLICABLE,
            confidence=AdjudicationConfidence.MEDIUM,
        )
        changed = record.model_copy(
            update={
                "reviews": (accepted,),
                "decisions": (changed_decision,),
            }
        )

        self.assertIn(
            ValidationIssueCode.REVIEW_FINAL_HASH_MISMATCH,
            self.codes(changed),
        )

    def test_old_historical_guideline_is_allowed(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        old = review(before=H0, after=H1, index=0, guideline="roles-v0")
        final = review(
            before=H1,
            after=record.decision_hash,
            index=1,
            guideline="roles-v1",
        )
        record = record.model_copy(update={"reviews": (old, final)})

        self.assertNotIn(
            ValidationIssueCode.REVIEW_GUIDELINE_MISMATCH,
            self.codes(record),
        )

    def test_final_review_guideline_must_match_batch(self) -> None:
        record = working_record(self.document, decisions=(positive_definition(),))
        final = review(
            before=record.decision_hash,
            after=record.decision_hash,
            index=0,
            guideline="roles-v0",
        )
        record = record.model_copy(update={"reviews": (final,)})

        self.assertIn(
            ValidationIssueCode.REVIEW_GUIDELINE_MISMATCH,
            self.codes(record),
        )


if __name__ == "__main__":
    unittest.main()
