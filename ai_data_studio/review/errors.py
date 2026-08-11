from __future__ import annotations

from ai_data_studio.validation import ValidationReport
from source_understanding.schemas.context import Identifier


class ReviewWorkflowError(RuntimeError):
    """Base error for human-review workflow failures."""


class ReviewRecordNotFoundError(ReviewWorkflowError):
    def __init__(self, record_id: Identifier) -> None:
        self.record_id = record_id
        super().__init__(f"working record {record_id!r} was not found")


class ReviewStateError(ReviewWorkflowError):
    """Raised when a record is not currently reviewable."""


class ReviewContractError(ReviewWorkflowError):
    """Raised when an external review payload violates the exchange contract."""


class StaleReviewSubmissionError(ReviewWorkflowError):
    def __init__(
        self,
        *,
        record_id: Identifier,
        expected_decision_hash: str,
        current_decision_hash: str,
    ) -> None:
        self.record_id = record_id
        self.expected_decision_hash = expected_decision_hash
        self.current_decision_hash = current_decision_hash
        super().__init__(
            "stale review submission for "
            f"record_id={record_id!r}: expected decision hash "
            f"{expected_decision_hash!r}, current hash is {current_decision_hash!r}"
        )


class ReviewValidationError(ReviewWorkflowError):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        codes = ", ".join(issue.code.value for issue in report.errors)
        super().__init__(
            "reviewed working record failed cross-object validation"
            + (f": {codes}" if codes else "")
        )
