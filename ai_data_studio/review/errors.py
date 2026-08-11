from __future__ import annotations

from typing import TYPE_CHECKING

from source_understanding.schemas.context import Identifier

if TYPE_CHECKING:
    from ai_data_studio.validation.issues import ValidationReport


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


class ArgillaReviewError(ReviewWorkflowError):
    """Base error for concrete Argilla integration failures."""


class ArgillaSdkUnavailableError(ArgillaReviewError):
    """Raised when the optional Argilla SDK dependency is unavailable."""


class ArgillaRemoteError(ArgillaReviewError):
    """Raised when an Argilla remote operation fails."""


class ArgillaDatasetContractError(ArgillaReviewError):
    """Raised when an existing Argilla dataset has an incompatible schema."""


class ArgillaWebhookTransportError(ArgillaReviewError):
    """Raised when an incoming webhook cannot be safely transported or decoded."""


class ArgillaWebhookAuthenticationError(ArgillaWebhookTransportError):
    """Raised when Standard Webhooks signature verification fails."""


class ArgillaReviewContextNotFoundError(ArgillaReviewError):
    def __init__(self, batch_id: Identifier) -> None:
        self.batch_id = batch_id
        super().__init__(f"review application context for batch_id={batch_id!r} was not found")


class ArgillaRemoteReviewConflictError(ArgillaReviewError):
    def __init__(self, record_id: Identifier) -> None:
        self.record_id = record_id
        super().__init__(
            "refusing to replace Argilla review task because the remote record already "
            f"has a submitted response: record_id={record_id!r}"
        )


class StaleArgillaReviewTaskError(ArgillaReviewError):
    def __init__(
        self,
        *,
        record_id: Identifier,
        remote_task_hash: str,
        current_task_hash: str,
    ) -> None:
        self.record_id = record_id
        self.remote_task_hash = remote_task_hash
        self.current_task_hash = current_task_hash
        super().__init__(
            "stale Argilla review task for "
            f"record_id={record_id!r}: remote task hash {remote_task_hash!r}, "
            f"current task hash {current_task_hash!r}"
        )


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
