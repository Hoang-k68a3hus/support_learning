from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from importlib import import_module
from types import ModuleType
from typing import Any

from pydantic import Field, SecretStr, model_validator

from source_understanding.schemas.context import Identifier, JsonObject, SchemaModel

from .argilla_exchange import (
    ARGILLA_OUTCOME_QUESTION,
    ARGILLA_REVIEW_CONTRACT_VERSION,
    ArgillaQuestionKind,
    argilla_settings_spec,
    task_to_argilla_record,
)
from .contracts import HumanReviewTask
from .errors import (
    ArgillaDatasetContractError,
    ArgillaRemoteError,
    ArgillaRemoteReviewConflictError,
    ArgillaSdkUnavailableError,
)


DEFAULT_ARGILLA_WORKSPACE = "argilla"
DEFAULT_ARGILLA_REVIEW_DATASET = "support-learning-semantic-review"


class ArgillaReviewConfig(SchemaModel):
    """Runtime configuration for the concrete Argilla review adapter."""

    api_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr
    workspace: str = Field(default=DEFAULT_ARGILLA_WORKSPACE, min_length=1, max_length=256)
    dataset_name: str = Field(
        default=DEFAULT_ARGILLA_REVIEW_DATASET,
        min_length=1,
        max_length=256,
    )
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    retries: int = Field(default=5, ge=0, le=10)

    @model_validator(mode="after")
    def validate_config(self) -> "ArgillaReviewConfig":
        for field_name in ("api_url", "workspace", "dataset_name"):
            value = getattr(self, field_name)
            if not value.strip() or value.strip() != value:
                raise ValueError(f"{field_name} must be non-blank and trimmed")
        if not self.api_key.get_secret_value().strip():
            raise ValueError("api_key must not be blank")
        return self

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "ArgillaReviewConfig":
        values = os.environ if env is None else env
        api_url = _required_env(values, "ARGILLA_API_URL")
        api_key = _required_env(values, "ARGILLA_API_KEY")
        workspace = values.get("ARGILLA_WORKSPACE", DEFAULT_ARGILLA_WORKSPACE)
        dataset_name = values.get(
            "ARGILLA_REVIEW_DATASET",
            DEFAULT_ARGILLA_REVIEW_DATASET,
        )
        timeout_seconds = _optional_int_env(values, "ARGILLA_TIMEOUT_SECONDS", 60)
        retries = _optional_int_env(values, "ARGILLA_RETRIES", 5)
        return cls(
            api_url=api_url,
            api_key=SecretStr(api_key),
            workspace=workspace,
            dataset_name=dataset_name,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )


class ArgillaSyncReport(SchemaModel):
    dataset_name: str
    total: int = Field(ge=0)
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "ArgillaSyncReport":
        if self.created + self.updated + self.skipped != self.total:
            raise ValueError("Argilla sync counts must sum to total")
        return self


class ArgillaReviewRemote:
    """Concrete Argilla SDK adapter for idempotent review-task synchronization."""

    def __init__(
        self,
        config: ArgillaReviewConfig,
        *,
        sdk: ModuleType | Any | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._sdk = _load_argilla_sdk() if sdk is None else sdk
        self._client = client if client is not None else self._create_client()

    def ensure_dataset(self, *, guidelines: str) -> Any:
        normalized_guidelines = _required_trimmed(guidelines, "guidelines")
        try:
            dataset = self._client.datasets(
                name=self.config.dataset_name,
                workspace=self.config.workspace,
            )
        except Exception as exc:
            raise ArgillaRemoteError(
                "failed to retrieve Argilla review dataset "
                f"{self.config.workspace!r}/{self.config.dataset_name!r}: {exc}"
            ) from exc

        if dataset is None:
            try:
                settings = build_argilla_settings(
                    self._sdk,
                    guidelines=normalized_guidelines,
                    client=self._client,
                )
                dataset = self._sdk.Dataset(
                    name=self.config.dataset_name,
                    workspace=self.config.workspace,
                    settings=settings,
                    client=self._client,
                )
                created = dataset.create()
            except Exception as exc:
                raise ArgillaRemoteError(
                    "failed to create Argilla review dataset "
                    f"{self.config.workspace!r}/{self.config.dataset_name!r}: {exc}"
                ) from exc
            dataset = created if created is not None else dataset
        else:
            self._validate_dataset_contract(dataset)
        return dataset

    def sync_tasks(
        self,
        tasks: Iterable[HumanReviewTask],
        *,
        guidelines: str,
    ) -> ArgillaSyncReport:
        task_items = tuple(tasks)
        record_ids = [task.record.record_id for task in task_items]
        if len(record_ids) != len(set(record_ids)):
            raise ArgillaRemoteError("Argilla sync input contains duplicate record ids")

        dataset = self.ensure_dataset(guidelines=guidelines)
        remote_records = self._load_remote_records(dataset)
        remote_by_id: dict[str, Any] = {}
        for remote_record in remote_records:
            record_id = str(getattr(remote_record, "id", "") or "")
            if not record_id:
                raise ArgillaRemoteError("Argilla returned a review record without an external id")
            if record_id in remote_by_id:
                raise ArgillaRemoteError(
                    f"Argilla returned duplicate external record id {record_id!r}"
                )
            remote_by_id[record_id] = remote_record

        created = 0
        updated = 0
        skipped = 0
        records_to_log: list[Any] = []
        for task in task_items:
            payload = task_to_argilla_record(task)
            record_id = task.record.record_id
            existing = remote_by_id.get(record_id)
            if existing is None:
                created += 1
                records_to_log.append(build_argilla_record(self._sdk, payload))
                continue

            remote_metadata = _record_metadata(existing)
            local_metadata = _payload_metadata(payload)
            if (
                remote_metadata.get("review_contract_version")
                == ARGILLA_REVIEW_CONTRACT_VERSION
                and remote_metadata.get("review_task_hash")
                == local_metadata["review_task_hash"]
            ):
                skipped += 1
                continue

            if _has_active_response(existing):
                raise ArgillaRemoteReviewConflictError(record_id)

            updated += 1
            records_to_log.append(build_argilla_record(self._sdk, payload))

        if records_to_log:
            try:
                dataset.records.log(records_to_log)
            except Exception as exc:
                raise ArgillaRemoteError(
                    f"failed to log {len(records_to_log)} review records to Argilla: {exc}"
                ) from exc

        return ArgillaSyncReport(
            dataset_name=self.config.dataset_name,
            total=len(task_items),
            created=created,
            updated=updated,
            skipped=skipped,
        )

    def _create_client(self) -> Any:
        try:
            return self._sdk.Argilla(
                api_url=self.config.api_url,
                api_key=self.config.api_key.get_secret_value(),
                timeout=self.config.timeout_seconds,
                retries=self.config.retries,
            )
        except Exception as exc:
            raise ArgillaRemoteError(
                f"failed to initialize Argilla client for {self.config.api_url!r}: {exc}"
            ) from exc

    def _load_remote_records(self, dataset: Any) -> tuple[Any, ...]:
        try:
            return tuple(
                dataset.records(
                    with_responses=True,
                    with_metadata=True,
                )
            )
        except Exception as exc:
            raise ArgillaRemoteError(
                f"failed to fetch records from Argilla dataset {self.config.dataset_name!r}: {exc}"
            ) from exc

    def _validate_dataset_contract(self, dataset: Any) -> None:
        settings = getattr(dataset, "settings", None)
        if settings is None:
            raise ArgillaDatasetContractError("Argilla dataset does not expose settings")
        loader = getattr(settings, "get", None)
        if callable(loader):
            loaded = loader()
            if loaded is not None:
                settings = loaded

        expected = argilla_settings_spec()
        actual_fields = _collection_names(getattr(settings, "fields", ()))
        expected_fields = expected.fields
        if actual_fields != expected_fields:
            raise ArgillaDatasetContractError(
                "Argilla dataset fields do not match review contract: "
                f"expected={expected_fields!r}, actual={actual_fields!r}"
            )

        actual_questions = _collection_names(getattr(settings, "questions", ()))
        expected_questions = tuple(question.name for question in expected.questions)
        if actual_questions != expected_questions:
            raise ArgillaDatasetContractError(
                "Argilla dataset questions do not match review contract: "
                f"expected={expected_questions!r}, actual={actual_questions!r}"
            )

        outcome_question = _collection_lookup(
            getattr(settings, "questions", ()),
            ARGILLA_OUTCOME_QUESTION,
        )
        if outcome_question is None:
            raise ArgillaDatasetContractError("Argilla outcome question is missing")
        expected_labels = next(
            question.labels
            for question in expected.questions
            if question.name == ARGILLA_OUTCOME_QUESTION
        )
        actual_labels = _normalize_labels(getattr(outcome_question, "labels", ()))
        if actual_labels != expected_labels:
            raise ArgillaDatasetContractError(
                "Argilla outcome labels do not match review contract: "
                f"expected={expected_labels!r}, actual={actual_labels!r}"
            )
        if getattr(outcome_question, "required", None) is not True:
            raise ArgillaDatasetContractError("Argilla outcome question must be required")
        if getattr(settings, "allow_extra_metadata", None) is not True:
            raise ArgillaDatasetContractError(
                "Argilla review dataset must allow extra metadata for provenance fields"
            )


def build_argilla_settings(
    sdk: Any,
    *,
    guidelines: str,
    client: Any,
) -> Any:
    """Build Settings using the public Argilla 2.x SDK contract."""

    normalized_guidelines = _required_trimmed(guidelines, "guidelines")
    spec = argilla_settings_spec()
    fields = [
        sdk.TextField(
            name=name,
            title=name.replace("_", " ").title(),
            required=True,
            use_markdown=False,
            client=client,
        )
        for name in spec.fields
    ]
    questions: list[Any] = []
    for question in spec.questions:
        if question.kind == ArgillaQuestionKind.LABEL:
            questions.append(
                sdk.LabelQuestion(
                    name=question.name,
                    title=question.title,
                    labels=list(question.labels),
                    required=question.required,
                    client=client,
                )
            )
        else:
            questions.append(
                sdk.TextQuestion(
                    name=question.name,
                    title=question.title,
                    required=question.required,
                    use_markdown=False,
                    client=client,
                )
            )
    return sdk.Settings(
        guidelines=normalized_guidelines,
        fields=fields,
        questions=questions,
        allow_extra_metadata=True,
    )


def build_argilla_record(sdk: Any, payload: JsonObject) -> Any:
    fields = payload.get("fields")
    metadata = payload.get("metadata")
    record_id = payload.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise ArgillaRemoteError("Argilla record payload requires a non-blank string id")
    if not isinstance(fields, dict) or not isinstance(metadata, dict):
        raise ArgillaRemoteError("Argilla record payload requires fields and metadata mappings")
    return sdk.Record(id=record_id, fields=fields, metadata=metadata)


def _load_argilla_sdk() -> ModuleType:
    try:
        return import_module("argilla")
    except ModuleNotFoundError as exc:
        raise ArgillaSdkUnavailableError(
            'Argilla SDK is required for remote review sync; install "argilla==2.8.0"'
        ) from exc


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        raise ValueError(f"required environment variable {name} is missing or blank")
    return value.strip()


def _optional_int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"environment variable {name} must be an integer") from exc


def _required_trimmed(value: str, name: str) -> str:
    if not value.strip() or value.strip() != value:
        raise ValueError(f"{name} must be non-blank and trimmed")
    return value


def _collection_names(collection: Any) -> tuple[str, ...]:
    return tuple(
        str(name)
        for name in (
            getattr(item, "name", None)
            for item in collection
        )
        if name is not None
    )


def _collection_lookup(collection: Any, name: str) -> Any | None:
    try:
        return collection[name]
    except (KeyError, IndexError, TypeError):
        pass
    for item in collection:
        if getattr(item, "name", None) == name:
            return item
    return None


def _normalize_labels(labels: Any) -> tuple[str, ...]:
    if isinstance(labels, Mapping):
        return tuple(str(value) for value in labels.keys())
    normalized: list[str] = []
    for label in labels:
        value = getattr(label, "value", label)
        normalized.append(str(value))
    return tuple(normalized)


def _record_metadata(record: Any) -> dict[str, Any]:
    metadata = getattr(record, "metadata", None)
    if metadata is None:
        return {}
    to_dict = getattr(metadata, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return result
    if isinstance(metadata, Mapping):
        return dict(metadata)
    raise ArgillaRemoteError("Argilla record metadata is not mapping-compatible")


def _payload_metadata(payload: JsonObject) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ArgillaRemoteError("Argilla payload metadata is not a mapping")
    return metadata


def _has_active_response(record: Any) -> bool:
    responses = getattr(record, "responses", None)
    if responses is None:
        return False
    spec = argilla_settings_spec()
    for question in spec.questions:
        try:
            question_responses = responses[question.name]
        except (KeyError, IndexError, TypeError):
            continue
        for response in question_responses:
            status = getattr(response, "status", None)
            status_value = getattr(status, "value", status)
            if status_value != "discarded":
                return True
    return False
