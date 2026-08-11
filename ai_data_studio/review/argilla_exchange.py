from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from ai_data_studio.schemas import AnnotationDecision, ReviewOutcome
from source_understanding.schemas.context import ContentHash, Identifier, JsonObject, SchemaModel

from .contracts import HumanReviewSubmission, HumanReviewTask
from .errors import ReviewContractError


ARGILLA_REVIEW_CONTRACT_VERSION = "1"
ARGILLA_OUTCOME_QUESTION = "review_outcome"
ARGILLA_DECISIONS_QUESTION = "review_decisions_json"
ARGILLA_NOTES_QUESTION = "review_notes"


class ArgillaQuestionKind(StrEnum):
    LABEL = "LABEL"
    TEXT = "TEXT"


class ArgillaQuestionSpec(SchemaModel):
    name: str = Field(min_length=1, max_length=128)
    kind: ArgillaQuestionKind
    title: str = Field(min_length=1, max_length=256)
    required: bool
    labels: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_question(self) -> "ArgillaQuestionSpec":
        if self.kind == ArgillaQuestionKind.LABEL and not self.labels:
            raise ValueError("LABEL Argilla questions require labels")
        if self.kind == ArgillaQuestionKind.TEXT and self.labels:
            raise ValueError("TEXT Argilla questions cannot carry labels")
        return self


class ArgillaReviewSettingsSpec(SchemaModel):
    contract_version: str = ARGILLA_REVIEW_CONTRACT_VERSION
    fields: tuple[str, ...]
    questions: tuple[ArgillaQuestionSpec, ...]


class ArgillaReviewResponse(SchemaModel):
    contract_version: str = ARGILLA_REVIEW_CONTRACT_VERSION
    record_id: Identifier
    batch_id: Identifier
    guideline_version: str = Field(min_length=1, max_length=128)
    expected_decision_hash: ContentHash
    outcome: ReviewOutcome
    decisions_json: str | None = Field(default=None, max_length=131072)
    notes: str | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def validate_response(self) -> "ArgillaReviewResponse":
        if self.contract_version != ARGILLA_REVIEW_CONTRACT_VERSION:
            raise ValueError(
                f"unsupported Argilla review contract_version {self.contract_version!r}"
            )
        if (
            not self.guideline_version.strip()
            or self.guideline_version.strip() != self.guideline_version
        ):
            raise ValueError("Argilla guideline_version must be non-blank and trimmed")
        if self.notes is not None and not self.notes.strip():
            raise ValueError("Argilla review notes must not be blank")
        return self


def argilla_settings_spec() -> ArgillaReviewSettingsSpec:
    return ArgillaReviewSettingsSpec(
        fields=("raw_text", "normalized_text", "review_context_json"),
        questions=(
            ArgillaQuestionSpec(
                name=ARGILLA_OUTCOME_QUESTION,
                kind=ArgillaQuestionKind.LABEL,
                title="Review outcome",
                required=True,
                labels=tuple(outcome.value for outcome in ReviewOutcome),
            ),
            ArgillaQuestionSpec(
                name=ARGILLA_DECISIONS_QUESTION,
                kind=ArgillaQuestionKind.TEXT,
                title="Canonical decisions JSON",
                required=False,
            ),
            ArgillaQuestionSpec(
                name=ARGILLA_NOTES_QUESTION,
                kind=ArgillaQuestionKind.TEXT,
                title="Review notes",
                required=False,
            ),
        ),
    )


def task_to_argilla_record(task: HumanReviewTask) -> JsonObject:
    record = task.record
    context = {
        "evaluated_types": [item.value for item in record.evaluated_types],
        "suggestions": [item.model_dump(mode="json") for item in record.suggestions],
        "current_decisions": [item.model_dump(mode="json") for item in record.decisions],
        "target": record.target.model_dump(mode="json"),
        "source": record.source.model_dump(mode="json"),
    }
    return {
        "id": record.record_id,
        "fields": {
            "raw_text": record.target.raw_text or "",
            "normalized_text": record.target.normalized_text or "",
            "review_context_json": _canonical_json(context),
        },
        "metadata": {
            "review_contract_version": ARGILLA_REVIEW_CONTRACT_VERSION,
            "record_id": record.record_id,
            "batch_id": record.batch_id,
            "guideline_version": task.guideline_version,
            "expected_decision_hash": task.expected_decision_hash,
            "document_id": record.source.document_id,
            "target_id": record.target.target_id,
        },
    }


def response_to_submission(
    response: ArgillaReviewResponse,
    *,
    reviewer_id: Identifier,
    reviewed_at: datetime,
) -> HumanReviewSubmission:
    decisions = _parse_decisions(response.decisions_json)
    return HumanReviewSubmission(
        record_id=response.record_id,
        batch_id=response.batch_id,
        expected_decision_hash=response.expected_decision_hash,
        reviewer_id=reviewer_id,
        guideline_version=response.guideline_version,
        reviewed_at=reviewed_at,
        outcome=response.outcome,
        decisions=decisions,
        notes=response.notes,
    )


def _parse_decisions(value: str | None) -> tuple[AnnotationDecision, ...] | None:
    if value is None or not value.strip():
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReviewContractError(
            f"Argilla decisions response is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, list):
        raise ReviewContractError("Argilla decisions response must be a JSON list")
    try:
        return tuple(AnnotationDecision.model_validate(item) for item in payload)
    except (TypeError, ValueError) as exc:
        raise ReviewContractError(
            f"Argilla decisions response does not match AnnotationDecision: {exc}"
        ) from exc


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
