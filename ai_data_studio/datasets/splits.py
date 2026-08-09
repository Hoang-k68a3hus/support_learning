from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    ContentHash,
    Identifier,
    JsonObject,
    SchemaModel,
)


SPLIT_MANIFEST_SCHEMA_VERSION = "1"
DATASET_SPLIT_MANIFEST_HASH_VERSION = "1"


class DatasetSplit(StrEnum):
    TRAIN = "train"
    DEV = "dev"
    TEST = "test"


class SplitAssignment(SchemaModel):
    split_group_id: Identifier
    split: DatasetSplit


class DatasetSplitManifest(SchemaModel):
    schema_version: str = SPLIT_MANIFEST_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=256)
    dataset_version: str = Field(min_length=1, max_length=128)
    assignments: tuple[SplitAssignment, ...]
    created_by: Identifier
    created_at: datetime
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest(self) -> "DatasetSplitManifest":
        if self.schema_version != SPLIT_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported split manifest schema_version {self.schema_version!r}"
            )
        if not self.name.strip() or self.name.strip() != self.name:
            raise ValueError("split manifest name must be non-blank and trimmed")
        if (
            not self.dataset_version.strip()
            or self.dataset_version.strip() != self.dataset_version
        ):
            raise ValueError(
                "split manifest dataset_version must be non-blank and trimmed"
            )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("split manifest created_at must be timezone-aware")
        group_ids = tuple(item.split_group_id for item in self.assignments)
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("split manifest split_group_id assignments must be unique")
        if group_ids != tuple(sorted(group_ids)):
            raise ValueError(
                "split manifest assignments must use lexical split_group_id order"
            )
        return self


def dataset_split_manifest_hash(manifest: DatasetSplitManifest) -> ContentHash:
    assignments = sorted(
        manifest.assignments,
        key=lambda assignment: assignment.split_group_id,
    )
    payload = {
        "hash_version": DATASET_SPLIT_MANIFEST_HASH_VERSION,
        "schema_version": manifest.schema_version,
        "name": manifest.name,
        "dataset_version": manifest.dataset_version,
        "assignments": [
            {
                "split_group_id": assignment.split_group_id,
                "split": assignment.split.value,
            }
            for assignment in assignments
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
