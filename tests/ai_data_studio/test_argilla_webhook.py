from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ai_data_studio.repositories import JsonlWorkingRecordRepository
from ai_data_studio.review.argilla_exchange import task_to_argilla_record
from ai_data_studio.review.argilla_orchestration import ArgillaReviewOrchestrator
from ai_data_studio.review.argilla_remote import ArgillaSyncReport
from ai_data_studio.review.argilla_webhook import parse_argilla_response_webhook
from ai_data_studio.review.contracts import HumanReviewTask
from ai_data_studio.review.errors import ReviewContractError, StaleArgillaReviewTaskError
from ai_data_studio.schemas import ReviewOutcome, WorkingRecordStatus

from tests.ai_data_studio._validation_fixtures import (
    NOW,
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
)


class _CapturingRemote:
    def __init__(self) -> None:
        self.tasks = ()
        self.guidelines = None

    def sync_tasks(self, tasks, *, guidelines):
        self.tasks = tuple(tasks)
        self.guidelines = guidelines
        return ArgillaSyncReport(
            dataset_name="semantic-review",
            total=len(self.tasks),
            created=len(self.tasks),
            updated=0,
            skipped=0,
        )


class ArgillaWebhookTests(unittest.TestCase):
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

    def payload(self, *, outcome="ACCEPT", status="submitted"):
        exported = task_to_argilla_record(self.task)
        metadata = dict(exported["metadata"])
        return {
            "type": "response.created",
            "version": 1,
            "timestamp": (NOW + timedelta(minutes=1)).isoformat(),
            "data": {
                "id": "response-1",
                "status": status,
                "updated_at": (NOW + timedelta(minutes=1)).isoformat(),
                "values": {
                    "review_outcome": {"value": outcome},
                    "review_decisions_json": {"value": ""},
                    "review_notes": {"value": "Reviewed in Argilla."},
                },
                "record": {
                    "id": "server-record-id",
                    "metadata": metadata,
                },
                "user": {
                    "id": "user-uuid-1",
                    "username": "reviewer-a",
                },
            },
        }

    def test_webhook_uses_response_updated_at_and_stable_user_id(self) -> None:
        parsed = parse_argilla_response_webhook(self.payload())

        self.assertEqual(parsed.response_id, "response-1")
        self.assertEqual(parsed.submission.reviewer_id, "argilla:user-uuid-1")
        self.assertEqual(parsed.submission.outcome, ReviewOutcome.ACCEPT)
        self.assertEqual(parsed.submission.reviewed_at, NOW + timedelta(minutes=1))
        self.assertEqual(parsed.submission.notes, "Reviewed in Argilla.")

    def test_webhook_rejects_draft_and_missing_provenance_timestamp(self) -> None:
        with self.assertRaises(ReviewContractError):
            parse_argilla_response_webhook(self.payload(status="draft"))

        payload = self.payload()
        del payload["data"]["updated_at"]
        with self.assertRaises(ReviewContractError):
            parse_argilla_response_webhook(payload)

    def test_orchestrator_applies_once_and_deduplicates_same_webhook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonlWorkingRecordRepository(Path(temp_dir) / "working.jsonl")
            repository.save(self.record)
            orchestrator = ArgillaReviewOrchestrator(repository, _CapturingRemote())
            documents = {self.document.document_id: self.document}

            first = orchestrator.apply_response_webhook(
                self.payload(),
                batch=self.batch,
                documents=documents,
            )
            second = orchestrator.apply_response_webhook(
                self.payload(),
                batch=self.batch,
                documents=documents,
            )

            self.assertTrue(first.applied)
            self.assertFalse(first.duplicate)
            self.assertFalse(second.applied)
            self.assertTrue(second.duplicate)
            stored = repository.get(self.record.record_id)
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.status, WorkingRecordStatus.PASS)
            self.assertEqual(len(stored.reviews), 1)

    def test_orchestrator_rejects_stale_remote_task_hash_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonlWorkingRecordRepository(Path(temp_dir) / "working.jsonl")
            repository.save(self.record)
            orchestrator = ArgillaReviewOrchestrator(repository, _CapturingRemote())
            payload = self.payload()
            payload["data"]["record"]["metadata"]["review_task_hash"] = (
                "sha256:" + "f" * 64
            )

            with self.assertRaises(StaleArgillaReviewTaskError):
                orchestrator.apply_response_webhook(
                    payload,
                    batch=self.batch,
                    documents={self.document.document_id: self.document},
                )

            self.assertEqual(repository.get(self.record.record_id), self.record)

    def test_export_batch_builds_validated_tasks_before_remote_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonlWorkingRecordRepository(Path(temp_dir) / "working.jsonl")
            repository.save(self.record)
            remote = _CapturingRemote()
            orchestrator = ArgillaReviewOrchestrator(repository, remote)

            report = orchestrator.export_batch(
                batch=self.batch,
                documents={self.document.document_id: self.document},
                guidelines="Review semantic roles using roles-v1.",
            )

            self.assertEqual(report.created, 1)
            self.assertEqual(len(remote.tasks), 1)
            self.assertEqual(remote.tasks[0].record, self.record)
            self.assertEqual(remote.guidelines, "Review semantic roles using roles-v1.")


if __name__ == "__main__":
    unittest.main()
