from __future__ import annotations

import json
import unittest
from datetime import timedelta

from ai_data_studio.review import (
    ARGILLA_DECISIONS_QUESTION,
    ARGILLA_OUTCOME_QUESTION,
    ArgillaQuestionKind,
    ArgillaReviewResponse,
    HumanReviewTask,
    ReviewContractError,
    argilla_settings_spec,
    response_to_submission,
    task_to_argilla_record,
)
from ai_data_studio.schemas import ReviewOutcome, WorkingRecordStatus

from tests.ai_data_studio._validation_fixtures import (
    NOW,
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
)


class ArgillaReviewExchangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = canonical_document()
        self.batch = working_batch()
        self.record = working_record(
            self.document,
            decisions=(positive_definition(),),
            status=WorkingRecordStatus.REVIEW_REQUIRED,
        )
        self.task = HumanReviewTask(
            record=self.record,
            guideline_version=self.batch.guideline_version,
            expected_decision_hash=self.record.decision_hash,
        )

    def test_settings_spec_exposes_stable_review_questions(self) -> None:
        spec = argilla_settings_spec()
        by_name = {question.name: question for question in spec.questions}

        self.assertEqual(by_name[ARGILLA_OUTCOME_QUESTION].kind, ArgillaQuestionKind.LABEL)
        self.assertEqual(
            by_name[ARGILLA_OUTCOME_QUESTION].labels,
            tuple(outcome.value for outcome in ReviewOutcome),
        )
        self.assertEqual(by_name[ARGILLA_DECISIONS_QUESTION].kind, ArgillaQuestionKind.TEXT)

    def test_task_payload_preserves_source_target_and_revision_metadata(self) -> None:
        payload = task_to_argilla_record(self.task)
        fields = payload["fields"]
        metadata = payload["metadata"]

        self.assertIsInstance(fields, dict)
        self.assertIsInstance(metadata, dict)
        assert isinstance(fields, dict)
        assert isinstance(metadata, dict)
        self.assertEqual(payload["id"], self.record.record_id)
        self.assertEqual(fields["raw_text"], self.record.target.raw_text)
        self.assertEqual(fields["normalized_text"], self.record.target.normalized_text)
        context = json.loads(str(fields["review_context_json"]))
        self.assertEqual(context["target"]["target_id"], self.record.target.target_id)
        self.assertEqual(
            metadata["expected_decision_hash"],
            self.record.decision_hash,
        )
        self.assertEqual(metadata["document_id"], self.record.source.document_id)

    def test_argilla_response_round_trips_to_submission(self) -> None:
        decisions_json = json.dumps(
            [item.model_dump(mode="json") for item in self.record.decisions]
        )
        response = ArgillaReviewResponse(
            record_id=self.record.record_id,
            batch_id=self.record.batch_id,
            guideline_version=self.batch.guideline_version,
            expected_decision_hash=self.record.decision_hash,
            outcome=ReviewOutcome.ACCEPT,
            decisions_json=decisions_json,
            notes="Reviewed in Argilla.",
        )

        submission = response_to_submission(
            response,
            reviewer_id="human-1",
            reviewed_at=NOW + timedelta(minutes=1),
        )

        self.assertEqual(submission.decisions, self.record.decisions)
        self.assertEqual(submission.expected_decision_hash, self.record.decision_hash)
        self.assertEqual(submission.reviewer_id, "human-1")

    def test_invalid_decision_json_fails_closed(self) -> None:
        response = ArgillaReviewResponse(
            record_id=self.record.record_id,
            batch_id=self.record.batch_id,
            guideline_version=self.batch.guideline_version,
            expected_decision_hash=self.record.decision_hash,
            outcome=ReviewOutcome.REJECT,
            decisions_json="{not-json}",
        )

        with self.assertRaises(ReviewContractError):
            response_to_submission(
                response,
                reviewer_id="human-1",
                reviewed_at=NOW + timedelta(minutes=1),
            )


if __name__ == "__main__":
    unittest.main()
