from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ai_data_studio.repositories import JsonlWorkingRecordRepository
from ai_data_studio.review import (
    HumanReviewSubmission,
    HumanReviewWorkflow,
    ReviewStateError,
    StaleReviewSubmissionError,
)
from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    ReviewOutcome,
    ReviewerKind,
    WorkingRecordStatus,
)
from source_understanding.schemas.document import SemanticAnnotationType

from tests.ai_data_studio._validation_fixtures import (
    NOW,
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
)


class HumanReviewWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repository = JsonlWorkingRecordRepository(
            Path(self.temp_dir.name) / "working.jsonl"
        )
        self.workflow = HumanReviewWorkflow(self.repository)
        self.document = canonical_document()
        self.batch = working_batch()

    def save_review_required(self, *, decisions=()):
        record = working_record(
            self.document,
            decisions=decisions,
            status=WorkingRecordStatus.REVIEW_REQUIRED,
        )
        self.repository.save(record)
        return record

    def test_build_task_binds_exact_revision_and_guideline(self) -> None:
        record = self.save_review_required(decisions=(positive_definition(),))

        task = self.workflow.build_task(
            record.record_id,
            document=self.document,
            batch=self.batch,
        )

        self.assertEqual(task.record, record)
        self.assertEqual(task.expected_decision_hash, record.decision_hash)
        self.assertEqual(task.guideline_version, self.batch.guideline_version)

    def test_accept_appends_human_review_and_persists_pass(self) -> None:
        record = self.save_review_required(decisions=(positive_definition(),))
        submission = HumanReviewSubmission(
            record_id=record.record_id,
            batch_id=record.batch_id,
            expected_decision_hash=record.decision_hash,
            reviewer_id="human-1",
            guideline_version=self.batch.guideline_version,
            reviewed_at=NOW + timedelta(minutes=1),
            outcome=ReviewOutcome.ACCEPT,
            decisions=record.decisions,
        )

        updated = self.workflow.apply_submission(
            submission,
            document=self.document,
            batch=self.batch,
        )

        self.assertEqual(updated.status, WorkingRecordStatus.PASS)
        self.assertEqual(len(updated.reviews), 1)
        self.assertEqual(updated.reviews[0].reviewer_kind, ReviewerKind.HUMAN)
        self.assertEqual(updated.reviews[0].outcome, ReviewOutcome.ACCEPT)
        self.assertEqual(updated.reviews[0].decision_hash_after, updated.decision_hash)
        self.assertEqual(self.repository.get(record.record_id), updated)

    def test_modify_replaces_decision_and_records_hash_transition(self) -> None:
        original = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.NOT_APPLICABLE,
            confidence=AdjudicationConfidence.MEDIUM,
        )
        record = self.save_review_required(decisions=(original,))
        replacement = positive_definition()
        submission = HumanReviewSubmission(
            record_id=record.record_id,
            batch_id=record.batch_id,
            expected_decision_hash=record.decision_hash,
            reviewer_id="human-1",
            guideline_version=self.batch.guideline_version,
            reviewed_at=NOW + timedelta(minutes=1),
            outcome=ReviewOutcome.MODIFY,
            decisions=(replacement,),
        )

        updated = self.workflow.apply_submission(
            submission,
            document=self.document,
            batch=self.batch,
        )

        self.assertEqual(updated.decisions, (replacement,))
        self.assertEqual(updated.status, WorkingRecordStatus.PASS)
        self.assertNotEqual(updated.reviews[0].decision_hash_before, updated.decision_hash)
        self.assertEqual(updated.reviews[0].decision_hash_after, updated.decision_hash)

    def test_reject_without_decisions_preserves_current_snapshot(self) -> None:
        record = self.save_review_required(decisions=(positive_definition(),))
        submission = HumanReviewSubmission(
            record_id=record.record_id,
            batch_id=record.batch_id,
            expected_decision_hash=record.decision_hash,
            reviewer_id="human-1",
            guideline_version=self.batch.guideline_version,
            reviewed_at=NOW + timedelta(minutes=1),
            outcome=ReviewOutcome.REJECT,
        )

        updated = self.workflow.apply_submission(
            submission,
            document=self.document,
            batch=self.batch,
        )

        self.assertEqual(updated.status, WorkingRecordStatus.REJECT)
        self.assertEqual(updated.decisions, record.decisions)
        self.assertEqual(updated.reviews[0].decision_hash_before, record.decision_hash)
        self.assertEqual(updated.reviews[0].decision_hash_after, record.decision_hash)

    def test_stale_submission_fails_without_persisting(self) -> None:
        record = self.save_review_required(decisions=(positive_definition(),))
        stale_hash = "sha256:" + "f" * 64
        submission = HumanReviewSubmission(
            record_id=record.record_id,
            batch_id=record.batch_id,
            expected_decision_hash=stale_hash,
            reviewer_id="human-1",
            guideline_version=self.batch.guideline_version,
            reviewed_at=NOW + timedelta(minutes=1),
            outcome=ReviewOutcome.REJECT,
        )

        with self.assertRaises(StaleReviewSubmissionError):
            self.workflow.apply_submission(
                submission,
                document=self.document,
                batch=self.batch,
            )

        self.assertEqual(self.repository.get(record.record_id), record)

    def test_wrong_guideline_is_rejected_before_write(self) -> None:
        record = self.save_review_required(decisions=(positive_definition(),))
        submission = HumanReviewSubmission(
            record_id=record.record_id,
            batch_id=record.batch_id,
            expected_decision_hash=record.decision_hash,
            reviewer_id="human-1",
            guideline_version="roles-v0",
            reviewed_at=NOW + timedelta(minutes=1),
            outcome=ReviewOutcome.REJECT,
        )

        with self.assertRaises(ReviewStateError):
            self.workflow.apply_submission(
                submission,
                document=self.document,
                batch=self.batch,
            )

        self.assertEqual(self.repository.get(record.record_id), record)


if __name__ == "__main__":
    unittest.main()
