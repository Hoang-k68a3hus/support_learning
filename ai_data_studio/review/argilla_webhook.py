from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from ai_data_studio.schemas import ReviewOutcome
from source_understanding.schemas.context import ContentHash, Identifier, SchemaModel

from .argilla_exchange import (
    ARGILLA_DECISIONS_QUESTION,
    ARGILLA_NOTES_QUESTION,
    ARGILLA_OUTCOME_QUESTION,
    ARGILLA_REVIEW_CONTRACT_VERSION,
    ArgillaReviewResponse,
    response_to_submission,
)
from .contracts import HumanReviewSubmission
from .errors import ReviewContractError


ARGILLA_WEBHOOK_VERSION = 1
ARGILLA_RESPONSE_EVENT_TYPES = frozenset({"response.created", "response.updated"})


class ArgillaWebhookReview(SchemaModel):
    response_id: Identifier
    review_task_hash: ContentHash
    submission: HumanReviewSubmission


def parse_argilla_response_webhook(
    payload: Mapping[str, object],
) -> ArgillaWebhookReview:
    """Parse one submitted Argilla response webhook without inventing review time."""

    event_type = _required_string(payload, "type", "webhook")
    if event_type not in ARGILLA_RESPONSE_EVENT_TYPES:
        raise ReviewContractError(
            f"unsupported Argilla webhook type {event_type!r}; expected response.created/updated"
        )
    version = payload.get("version")
    if version != ARGILLA_WEBHOOK_VERSION:
        raise ReviewContractError(
            f"unsupported Argilla webhook version {version!r}; expected {ARGILLA_WEBHOOK_VERSION}"
        )

    data = _required_mapping(payload, "data", "webhook")
    response_id = _required_string(data, "id", "webhook response")
    status = _required_string(data, "status", "webhook response")
    if status != "submitted":
        raise ReviewContractError(
            f"Argilla webhook response status must be 'submitted', got {status!r}"
        )
    reviewed_at = _required_datetime(data, "updated_at", "webhook response")

    values = _required_mapping(data, "values", "webhook response")
    record = _required_mapping(data, "record", "webhook response")
    metadata = _required_mapping(record, "metadata", "webhook record")
    user = _required_mapping(data, "user", "webhook response")

    contract_version = _required_string(
        metadata,
        "review_contract_version",
        "webhook record metadata",
    )
    if contract_version != ARGILLA_REVIEW_CONTRACT_VERSION:
        raise ReviewContractError(
            f"unsupported Argilla review contract version {contract_version!r}"
        )

    outcome_raw = _question_value(values, ARGILLA_OUTCOME_QUESTION, required=True)
    if not isinstance(outcome_raw, str):
        raise ReviewContractError("Argilla review outcome must be a string")
    try:
        outcome = ReviewOutcome(outcome_raw)
    except ValueError as exc:
        raise ReviewContractError(
            f"unsupported Argilla review outcome {outcome_raw!r}"
        ) from exc

    decisions_json = _optional_text_question(values, ARGILLA_DECISIONS_QUESTION)
    notes = _optional_text_question(values, ARGILLA_NOTES_QUESTION)
    reviewer_user_id = _required_string(user, "id", "webhook user")

    response = ArgillaReviewResponse(
        contract_version=contract_version,
        record_id=_required_string(metadata, "record_id", "webhook record metadata"),
        batch_id=_required_string(metadata, "batch_id", "webhook record metadata"),
        guideline_version=_required_string(
            metadata,
            "guideline_version",
            "webhook record metadata",
        ),
        expected_decision_hash=_required_string(
            metadata,
            "expected_decision_hash",
            "webhook record metadata",
        ),
        outcome=outcome,
        decisions_json=decisions_json,
        notes=notes,
    )
    submission = response_to_submission(
        response,
        reviewer_id=f"argilla:{reviewer_user_id}",
        reviewed_at=reviewed_at,
    )
    return ArgillaWebhookReview(
        response_id=response_id,
        review_task_hash=_required_string(
            metadata,
            "review_task_hash",
            "webhook record metadata",
        ),
        submission=submission,
    )


def _required_mapping(
    value: Mapping[str, object],
    key: str,
    context: str,
) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise ReviewContractError(f"{context} field {key!r} must be an object")
    return item


def _required_string(
    value: Mapping[str, object],
    key: str,
    context: str,
) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ReviewContractError(f"{context} field {key!r} must be a non-blank string")
    return item.strip()


def _required_datetime(
    value: Mapping[str, object],
    key: str,
    context: str,
) -> datetime:
    item = value.get(key)
    if isinstance(item, datetime):
        parsed = item
    elif isinstance(item, str):
        try:
            parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReviewContractError(
                f"{context} field {key!r} must be an ISO-8601 datetime"
            ) from exc
    else:
        raise ReviewContractError(f"{context} field {key!r} must be a datetime string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewContractError(f"{context} field {key!r} must be timezone-aware")
    return parsed


def _question_value(
    values: Mapping[str, object],
    question_name: str,
    *,
    required: bool,
) -> object | None:
    raw = values.get(question_name)
    if raw is None:
        if required:
            raise ReviewContractError(
                f"Argilla webhook is missing required question {question_name!r}"
            )
        return None
    if not isinstance(raw, Mapping) or "value" not in raw:
        raise ReviewContractError(
            f"Argilla webhook question {question_name!r} must contain a value"
        )
    return raw.get("value")


def _optional_text_question(
    values: Mapping[str, object],
    question_name: str,
) -> str | None:
    raw = _question_value(values, question_name, required=False)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ReviewContractError(
            f"Argilla webhook question {question_name!r} must be text"
        )
    return raw if raw.strip() else None
