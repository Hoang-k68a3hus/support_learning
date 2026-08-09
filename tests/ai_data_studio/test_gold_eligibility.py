from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    GoldEligibilityEvaluator,
    GoldEligibilityPolicy,
    GoldIneligibilityReason,
)
from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    WorkingRecordStatus,
)
from source_understanding.schemas.document import SemanticAnnotationType

from ._gold_compiler_fixtures import (
    adjudicated_record,
    positive_decision,
)


class GoldEligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = GoldEligibilityEvaluator()
        self.policy = GoldEligibilityPolicy()

    def reasons(self, record) -> tuple[GoldIneligibilityReason, ...]:
        return self.evaluator.evaluate(record, policy=self.policy).reasons

    def test_pass_high_reviewed_record_is_eligible(self) -> None:
        result = self.evaluator.evaluate(
            adjudicated_record(),
            policy=self.policy,
        )

        self.assertTrue(result.eligible)
        self.assertEqual(result.reasons, ())

    def test_non_pass_statuses_are_ineligible(self) -> None:
        for status in (
            WorkingRecordStatus.DRAFT,
            WorkingRecordStatus.REVIEW_REQUIRED,
            WorkingRecordStatus.REJECT,
        ):
            with self.subTest(status=status):
                record = adjudicated_record(status=status)
                self.assertIn(
                    GoldIneligibilityReason.STATUS_NOT_ALLOWED,
                    self.reasons(record),
                )

    def test_undecided_and_incomplete_decisions_are_ineligible(self) -> None:
        eligible = adjudicated_record()
        undecided = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.UNDECIDED,
            rationale="Two labels remain plausible.",
            confidence=AdjudicationConfidence.LOW,
        )
        undecided_record = eligible.model_copy(
            update={"decisions": (undecided,)}
        )
        incomplete_record = eligible.model_copy(update={"decisions": ()})

        self.assertIn(
            GoldIneligibilityReason.UNDECIDED_PRESENT,
            self.reasons(undecided_record),
        )
        self.assertIn(
            GoldIneligibilityReason.DECISIONS_INCOMPLETE,
            self.reasons(incomplete_record),
        )

    def test_confidence_review_and_rule_key_policy_are_independent(self) -> None:
        low_confidence = adjudicated_record(
            decisions=(
                positive_decision(confidence=AdjudicationConfidence.MEDIUM),
            )
        )
        missing_review = adjudicated_record(with_review=False)
        missing_rule_key = adjudicated_record(
            decisions=(positive_decision(rule_keys=()),)
        )

        self.assertIn(
            GoldIneligibilityReason.CONFIDENCE_TOO_LOW,
            self.reasons(low_confidence),
        )
        self.assertIn(
            GoldIneligibilityReason.MISSING_REVIEW,
            self.reasons(missing_review),
        )
        self.assertIn(
            GoldIneligibilityReason.MISSING_RULE_KEYS,
            self.reasons(missing_rule_key),
        )

    def test_generative_positive_is_disallowed_by_default(self) -> None:
        record = adjudicated_record(
            decisions=(
                positive_decision(
                    SemanticAnnotationType.SUMMARY,
                    value="Generated summary text.",
                ),
            )
        )

        self.assertIn(
            GoldIneligibilityReason.PAYLOAD_MODE_NOT_ALLOWED,
            self.reasons(record),
        )


if __name__ == "__main__":
    unittest.main()
