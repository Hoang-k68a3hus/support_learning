from __future__ import annotations

from ai_data_studio.repositories import WorkingRecordRepository
from ai_data_studio.schemas import (
    ReviewAttempt,
    ReviewerKind,
    ReviewOutcome,
    SemanticWorkingRecord,
    WorkingBatch,
    WorkingRecordStatus,
    annotation_decisions_hash,
)
from ai_data_studio.validation.working_record import WorkingRecordValidator
from source_understanding.schemas.context import Identifier
from source_understanding.schemas.document import CanonicalDocument

from .contracts import HumanReviewSubmission, HumanReviewTask
from .errors import (
    ReviewRecordNotFoundError,
    ReviewStateError,
    ReviewValidationError,
    StaleReviewSubmissionError,
)


class HumanReviewWorkflow:
    """Apply human reviews without making the review UI the source of truth."""

    def __init__(self, repository: WorkingRecordRepository) -> None:
        self._repository = repository
        self._validator = WorkingRecordValidator()

    def build_task(
        self,
        record_id: Identifier,
        *,
        document: CanonicalDocument,
        batch: WorkingBatch,
    ) -> HumanReviewTask:
        record = self._require_record(record_id)
        self._require_reviewable(record)
        self._validate(record=record, document=document, batch=batch)
        return HumanReviewTask(
            record=record,
            guideline_version=batch.guideline_version,
            expected_decision_hash=record.decision_hash,
        )

    def apply_submission(
        self,
        submission: HumanReviewSubmission,
        *,
        document: CanonicalDocument,
        batch: WorkingBatch,
    ) -> SemanticWorkingRecord:
        record = self._require_record(submission.record_id)
        self._require_reviewable(record)

        if submission.batch_id != record.batch_id:
            raise ReviewStateError(
                f"review submission batch_id {submission.batch_id!r} does not match "
                f"record batch_id {record.batch_id!r}"
            )
        if batch.batch_id != record.batch_id:
            raise ReviewStateError(
                f"review batch {batch.batch_id!r} does not match record batch_id "
                f"{record.batch_id!r}"
            )
        if submission.guideline_version != batch.guideline_version:
            raise ReviewStateError(
                f"review submission guideline_version {submission.guideline_version!r} "
                f"does not match batch guideline_version {batch.guideline_version!r}"
            )
        if submission.expected_decision_hash != record.decision_hash:
            raise StaleReviewSubmissionError(
                record_id=record.record_id,
                expected_decision_hash=submission.expected_decision_hash,
                current_decision_hash=record.decision_hash,
            )

        decisions = (
            record.decisions if submission.decisions is None else submission.decisions
        )
        candidate_status = _status_after_review(submission.outcome)
        candidate_values = record.model_dump(mode="python")
        candidate_values.update(
            {
                "decisions": decisions,
                "reviews": (
                    *record.reviews,
                    ReviewAttempt(
                        reviewer_id=submission.reviewer_id,
                        reviewer_kind=ReviewerKind.HUMAN,
                        guideline_version=submission.guideline_version,
                        reviewed_at=submission.reviewed_at,
                        decision_hash_before=record.decision_hash,
                        decision_hash_after=annotation_decisions_hash(decisions),
                        outcome=submission.outcome,
                        notes=submission.notes,
                    ),
                ),
                "status": candidate_status,
            }
        )
        candidate = SemanticWorkingRecord.model_validate(candidate_values)
        self._validate(record=candidate, document=document, batch=batch)
        self._repository.save(candidate)
        return candidate

    def _require_record(self, record_id: Identifier) -> SemanticWorkingRecord:
        record = self._repository.get(record_id)
        if record is None:
            raise ReviewRecordNotFoundError(record_id)
        return record

    @staticmethod
    def _require_reviewable(record: SemanticWorkingRecord) -> None:
        if record.status != WorkingRecordStatus.REVIEW_REQUIRED:
            raise ReviewStateError(
                f"working record {record.record_id!r} is {record.status.value}, "
                "expected REVIEW_REQUIRED"
            )

    def _validate(
        self,
        *,
        record: SemanticWorkingRecord,
        document: CanonicalDocument,
        batch: WorkingBatch,
    ) -> None:
        report = self._validator.validate(
            record=record,
            document=document,
            batch=batch,
        )
        if not report.is_valid:
            raise ReviewValidationError(report)


def _status_after_review(outcome: ReviewOutcome) -> WorkingRecordStatus:
    if outcome in {ReviewOutcome.ACCEPT, ReviewOutcome.MODIFY}:
        return WorkingRecordStatus.PASS
    if outcome == ReviewOutcome.CONFLICT:
        return WorkingRecordStatus.REVIEW_REQUIRED
    return WorkingRecordStatus.REJECT
