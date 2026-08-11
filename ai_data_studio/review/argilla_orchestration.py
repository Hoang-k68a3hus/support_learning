from __future__ import annotations

from collections.abc import Mapping

from ai_data_studio.repositories import WorkingRecordRepository
from ai_data_studio.schemas import (
    SemanticWorkingRecord,
    WorkingBatch,
    annotation_decisions_hash,
)
from source_understanding.schemas.context import Identifier, SchemaModel
from source_understanding.schemas.document import CanonicalDocument

from .argilla_exchange import argilla_review_task_hash
from .argilla_remote import ArgillaReviewRemote, ArgillaSyncReport
from .argilla_webhook import parse_argilla_response_webhook
from .contracts import HumanReviewSubmission
from .errors import (
    ReviewRecordNotFoundError,
    ReviewStateError,
    StaleArgillaReviewTaskError,
)
from .service import HumanReviewWorkflow


class ArgillaImportResult(SchemaModel):
    response_id: Identifier
    record: SemanticWorkingRecord
    applied: bool
    duplicate: bool


class ArgillaReviewOrchestrator:
    """Bridge WorkingRecord authority with remote Argilla review operations."""

    def __init__(
        self,
        repository: WorkingRecordRepository,
        remote: ArgillaReviewRemote,
    ) -> None:
        self._repository = repository
        self._workflow = HumanReviewWorkflow(repository)
        self._remote = remote

    def export_batch(
        self,
        *,
        batch: WorkingBatch,
        documents: Mapping[Identifier, CanonicalDocument],
        guidelines: str,
    ) -> ArgillaSyncReport:
        tasks = []
        for record_id in batch.record_ids:
            record = self._require_record(record_id)
            document = self._require_document(record, documents)
            tasks.append(
                self._workflow.build_task(
                    record_id,
                    document=document,
                    batch=batch,
                )
            )
        return self._remote.sync_tasks(tasks, guidelines=guidelines)

    def apply_response_webhook(
        self,
        payload: Mapping[str, object],
        *,
        batch: WorkingBatch,
        documents: Mapping[Identifier, CanonicalDocument],
    ) -> ArgillaImportResult:
        webhook_review = parse_argilla_response_webhook(payload)
        submission = webhook_review.submission
        record = self._require_record(submission.record_id)

        if _matches_last_review(record, submission):
            return ArgillaImportResult(
                response_id=webhook_review.response_id,
                record=record,
                applied=False,
                duplicate=True,
            )

        document = self._require_document(record, documents)
        current_task = self._workflow.build_task(
            record.record_id,
            document=document,
            batch=batch,
        )
        current_task_hash = argilla_review_task_hash(current_task)
        if webhook_review.review_task_hash != current_task_hash:
            raise StaleArgillaReviewTaskError(
                record_id=record.record_id,
                remote_task_hash=webhook_review.review_task_hash,
                current_task_hash=current_task_hash,
            )

        updated = self._workflow.apply_submission(
            submission,
            document=document,
            batch=batch,
        )
        return ArgillaImportResult(
            response_id=webhook_review.response_id,
            record=updated,
            applied=True,
            duplicate=False,
        )

    def _require_record(self, record_id: Identifier) -> SemanticWorkingRecord:
        record = self._repository.get(record_id)
        if record is None:
            raise ReviewRecordNotFoundError(record_id)
        return record

    @staticmethod
    def _require_document(
        record: SemanticWorkingRecord,
        documents: Mapping[Identifier, CanonicalDocument],
    ) -> CanonicalDocument:
        document = documents.get(record.source.document_id)
        if document is None:
            raise ReviewStateError(
                "canonical document required for Argilla review orchestration is missing: "
                f"document_id={record.source.document_id!r}, record_id={record.record_id!r}"
            )
        return document


def _matches_last_review(
    record: SemanticWorkingRecord,
    submission: HumanReviewSubmission,
) -> bool:
    if not record.reviews:
        return False
    last = record.reviews[-1]
    if (
        last.reviewer_id != submission.reviewer_id
        or last.guideline_version != submission.guideline_version
        or last.reviewed_at != submission.reviewed_at
        or last.outcome != submission.outcome
        or last.decision_hash_before != submission.expected_decision_hash
    ):
        return False
    expected_after = (
        submission.expected_decision_hash
        if submission.decisions is None
        else annotation_decisions_hash(submission.decisions)
    )
    return last.decision_hash_after == expected_after
