from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from ai_data_studio.datasets.splits import DatasetSplit
from source_understanding.schemas.context import (
    ContentHash,
    Identifier,
    JsonObject,
    SchemaModel,
)
from source_understanding.schemas.document import SemanticAnnotationType
from source_understanding.semantics.provider import (
    SemanticRequest,
    SemanticTargetKind,
)
from source_understanding.semantics.providers.role_classifier.provider import (
    ROLE_CLASSIFIER_ANNOTATION_TYPES,
)


ROLE_CLASSIFIER_DATASET_SCHEMA_VERSION = "2"


class RoleClassifierDatasetError(ValueError):
    """A role-classifier dataset cannot be loaded without violating its contract."""


RoleClassifierDatasetSplit = DatasetSplit


class RoleClassifierLabelSource(StrEnum):
    HUMAN_GOLD = "HUMAN_GOLD"
    LLM_SILVER = "LLM_SILVER"


class RoleClassifierTestPolicy(StrEnum):
    HUMAN_ONLY_FROZEN = "HUMAN_ONLY_FROZEN"


class RoleClassifierTrainingTarget(SchemaModel):
    kind: SemanticTargetKind = SemanticTargetKind.LOGICAL_UNIT
    element_orders: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> "RoleClassifierTrainingTarget":
        if self.kind != SemanticTargetKind.LOGICAL_UNIT:
            raise ValueError("role classifier training targets must be LOGICAL_UNIT")
        if len(self.element_orders) != len(set(self.element_orders)):
            raise ValueError("role classifier target element_orders must be unique")
        if self.element_orders != tuple(sorted(self.element_orders)):
            raise ValueError(
                "role classifier target element_orders must follow canonical order"
            )
        return self

    @property
    def key(self) -> str:
        return ",".join(str(order) for order in self.element_orders)


class RoleClassifierTeacher(SchemaModel):
    provider_name: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=128)
    configuration_hash: ContentHash


class RoleClassifierTrainingExample(SchemaModel):
    example_id: Identifier
    document_id: Identifier
    content_hash: ContentHash
    source_family_id: Identifier
    split_group_id: Identifier
    source_revision: str | None = Field(default=None, min_length=1, max_length=512)
    target: RoleClassifierTrainingTarget
    request: SemanticRequest
    labels: tuple[SemanticAnnotationType, ...] = Field(default_factory=tuple)
    split: DatasetSplit
    label_source: RoleClassifierLabelSource
    teacher: RoleClassifierTeacher | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_example(self) -> "RoleClassifierTrainingExample":
        if self.request.target_kind != SemanticTargetKind.LOGICAL_UNIT:
            raise ValueError(
                "role classifier training request must target a LOGICAL_UNIT"
            )
        if len(self.target.element_orders) != len(self.request.element_ids):
            raise ValueError(
                "training target element_orders must align one-to-one with request "
                "element_ids"
            )
        if len(self.labels) != len(set(self.labels)):
            raise ValueError("role classifier example labels must be unique")
        unsupported = set(self.labels) - set(ROLE_CLASSIFIER_ANNOTATION_TYPES)
        if unsupported:
            raise ValueError(
                "role classifier example contains labels outside Phase A: "
                f"{sorted(item.value for item in unsupported)}"
            )
        canonical_labels = tuple(
            annotation_type
            for annotation_type in ROLE_CLASSIFIER_ANNOTATION_TYPES
            if annotation_type in self.labels
        )
        if self.labels != canonical_labels:
            raise ValueError(
                "role classifier example labels must use canonical Phase A order"
            )
        if self.label_source == RoleClassifierLabelSource.HUMAN_GOLD:
            if self.teacher is not None:
                raise ValueError("HUMAN_GOLD examples cannot carry teacher identity")
        elif self.teacher is None:
            raise ValueError("LLM_SILVER examples require reproducible teacher identity")
        if (
            self.split == DatasetSplit.TEST
            and self.label_source != RoleClassifierLabelSource.HUMAN_GOLD
        ):
            raise ValueError("role classifier TEST examples must be human-only gold")
        return self

    @property
    def source_target_key(self) -> tuple[str, str]:
        return self.content_hash, self.target.key


class RoleClassifierTrainingDataset(SchemaModel):
    name: str = Field(min_length=1, max_length=256)
    schema_version: str = ROLE_CLASSIFIER_DATASET_SCHEMA_VERSION
    dataset_version: str = Field(min_length=1, max_length=128)
    label_space: tuple[SemanticAnnotationType, ...] = (
        ROLE_CLASSIFIER_ANNOTATION_TYPES
    )
    test_policy: RoleClassifierTestPolicy = (
        RoleClassifierTestPolicy.HUMAN_ONLY_FROZEN
    )
    examples: tuple[RoleClassifierTrainingExample, ...] = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dataset(self) -> "RoleClassifierTrainingDataset":
        if self.schema_version != ROLE_CLASSIFIER_DATASET_SCHEMA_VERSION:
            raise ValueError(
                "unsupported role classifier dataset schema_version: "
                f"{self.schema_version!r}"
            )
        if self.label_space != ROLE_CLASSIFIER_ANNOTATION_TYPES:
            raise ValueError(
                "role classifier label_space must use the canonical Phase A order"
            )
        example_ids = tuple(item.example_id for item in self.examples)
        if len(example_ids) != len(set(example_ids)):
            raise ValueError("role classifier dataset example_ids must be unique")

        seen_targets: dict[tuple[str, str], DatasetSplit] = {}
        split_group_splits: dict[str, DatasetSplit] = {}
        source_family_splits: dict[str, DatasetSplit] = {}
        content_hash_splits: dict[str, DatasetSplit] = {}
        document_id_splits: dict[str, DatasetSplit] = {}
        source_family_groups: dict[str, str] = {}
        content_hash_groups: dict[str, str] = {}
        document_id_groups: dict[str, str] = {}
        for example in self.examples:
            previous_split = seen_targets.get(example.source_target_key)
            if previous_split is not None:
                raise ValueError(
                    "role classifier source target occurs more than once: "
                    f"content_hash={example.content_hash!r}, "
                    f"element_orders={example.target.element_orders!r}, "
                    f"splits={previous_split.value!r}/{example.split.value!r}"
                )
            seen_targets[example.source_target_key] = example.split

            leakage_keys = (
                ("split_group_id", example.split_group_id, split_group_splits),
                ("source_family_id", example.source_family_id, source_family_splits),
                ("content_hash", example.content_hash, content_hash_splits),
                ("document_id", example.document_id, document_id_splits),
            )
            for key_name, key_value, assigned_splits in leakage_keys:
                assigned_split = assigned_splits.get(key_value)
                if assigned_split is not None and assigned_split != example.split:
                    raise ValueError(
                        f"role classifier {key_name} leaks across splits: "
                        f"{key_value!r} is assigned to "
                        f"{assigned_split.value!r}/{example.split.value!r}"
                    )
                assigned_splits[key_value] = example.split

            group_identity_keys = (
                (
                    "source_family_id",
                    example.source_family_id,
                    source_family_groups,
                ),
                ("content_hash", example.content_hash, content_hash_groups),
                ("document_id", example.document_id, document_id_groups),
            )
            for key_name, key_value, assigned_groups in group_identity_keys:
                assigned_group = assigned_groups.get(key_value)
                if (
                    assigned_group is not None
                    and assigned_group != example.split_group_id
                ):
                    raise ValueError(
                        f"role classifier {key_name} crosses split groups: "
                        f"{key_value!r} is assigned to "
                        f"{assigned_group!r}/{example.split_group_id!r}"
                    )
                assigned_groups[key_value] = example.split_group_id
        return self


def load_role_classifier_training_dataset(
    path: str | Path,
) -> RoleClassifierTrainingDataset:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RoleClassifierDatasetError(
            f"cannot read role classifier dataset {source}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RoleClassifierDatasetError(
            f"invalid JSON in role classifier dataset {source}: {exc}"
        ) from exc
    try:
        return RoleClassifierTrainingDataset.model_validate(payload)
    except ValueError as exc:
        raise RoleClassifierDatasetError(
            f"invalid role classifier dataset {source}: {exc}"
        ) from exc
