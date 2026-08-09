from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePath

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    ContentHash,
    SchemaModel,
)

from .splits import DatasetSplit


FROZEN_DATASET_MANIFEST_SCHEMA_VERSION = "1"


class FrozenSplitArtifact(SchemaModel):
    split: DatasetSplit
    filename: str = Field(min_length=1, max_length=256)
    content_hash: ContentHash
    document_count: int = Field(ge=1)
    target_count: int = Field(ge=1)
    annotation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_artifact(self) -> "FrozenSplitArtifact":
        expected_filename = f"{self.split.value}.json"
        if self.filename != expected_filename:
            raise ValueError(
                f"frozen {self.split.value} artifact filename must be "
                f"{expected_filename!r}"
            )
        if PurePath(self.filename).name != self.filename:
            raise ValueError("frozen split artifact filename must be relative")
        return self


class FreezeProvenance(SchemaModel):
    compiler_version: str = Field(min_length=1, max_length=128)
    guideline_version: str = Field(min_length=1, max_length=128)
    working_record_schema_version: str = Field(min_length=1, max_length=128)
    eligibility_policy_name: str = Field(min_length=1, max_length=128)
    eligibility_policy_version: str = Field(min_length=1, max_length=128)
    producer_revision: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_provenance(self) -> "FreezeProvenance":
        for field_name in (
            "compiler_version",
            "guideline_version",
            "working_record_schema_version",
            "eligibility_policy_name",
            "eligibility_policy_version",
        ):
            value = getattr(self, field_name)
            if not value.strip() or value.strip() != value:
                raise ValueError(f"freeze provenance {field_name} must be trimmed")
        if self.producer_revision is not None and (
            not self.producer_revision.strip()
            or self.producer_revision.strip() != self.producer_revision
        ):
            raise ValueError(
                "freeze provenance producer_revision must be non-blank and trimmed"
            )
        return self


class FreezePolicy(SchemaModel):
    required_splits: tuple[DatasetSplit, ...] = (
        DatasetSplit.TRAIN,
        DatasetSplit.DEV,
        DatasetSplit.TEST,
    )

    @model_validator(mode="after")
    def validate_policy(self) -> "FreezePolicy":
        if len(self.required_splits) != len(set(self.required_splits)):
            raise ValueError("freeze policy required_splits must be unique")
        canonical = tuple(
            split for split in DatasetSplit if split in self.required_splits
        )
        if self.required_splits != canonical:
            raise ValueError(
                "freeze policy required_splits must use train/dev/test order"
            )
        return self


class FrozenDatasetManifest(SchemaModel):
    schema_version: str = FROZEN_DATASET_MANIFEST_SCHEMA_VERSION
    dataset_name: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    dataset_version: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    gold_schema_version: str = Field(min_length=1, max_length=128)
    compiler_version: str = Field(min_length=1, max_length=128)
    working_record_schema_version: str = Field(min_length=1, max_length=128)
    split_manifest_schema_version: str = Field(min_length=1, max_length=128)
    guideline_version: str = Field(min_length=1, max_length=128)
    eligibility_policy_name: str = Field(min_length=1, max_length=128)
    eligibility_policy_version: str = Field(min_length=1, max_length=128)
    producer_revision: str | None = Field(default=None, max_length=256)
    split_manifest_hash: ContentHash
    source_corpus_hash: ContentHash
    dataset_hash: ContentHash
    train: FrozenSplitArtifact | None = None
    dev: FrozenSplitArtifact | None = None
    test: FrozenSplitArtifact | None = None
    document_count: int = Field(ge=1)
    target_count: int = Field(ge=1)
    annotation_count: int = Field(ge=0)
    created_at: datetime

    @model_validator(mode="after")
    def validate_manifest(self) -> "FrozenDatasetManifest":
        if self.schema_version != FROZEN_DATASET_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported frozen manifest schema_version "
                f"{self.schema_version!r}"
            )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("frozen manifest created_at must be timezone-aware")
        artifacts = tuple(
            artifact
            for artifact in (self.train, self.dev, self.test)
            if artifact is not None
        )
        if not artifacts:
            raise ValueError("frozen manifest requires at least one split artifact")
        for expected_split, artifact in (
            (DatasetSplit.TRAIN, self.train),
            (DatasetSplit.DEV, self.dev),
            (DatasetSplit.TEST, self.test),
        ):
            if artifact is not None and artifact.split != expected_split:
                raise ValueError(
                    f"frozen manifest {expected_split.value} field contains "
                    f"{artifact.split.value} artifact"
                )
        expected_counts = (
            sum(artifact.document_count for artifact in artifacts),
            sum(artifact.target_count for artifact in artifacts),
            sum(artifact.annotation_count for artifact in artifacts),
        )
        actual_counts = (
            self.document_count,
            self.target_count,
            self.annotation_count,
        )
        if actual_counts != expected_counts:
            raise ValueError(
                "frozen manifest total counts must equal per-split counts: "
                f"{actual_counts!r} != {expected_counts!r}"
            )
        return self

    def artifact_for(
        self,
        split: DatasetSplit,
    ) -> FrozenSplitArtifact | None:
        return {
            DatasetSplit.TRAIN: self.train,
            DatasetSplit.DEV: self.dev,
            DatasetSplit.TEST: self.test,
        }[split]


class FrozenDatasetVerificationIssueCode(StrEnum):
    MANIFEST_MISSING = "MANIFEST_MISSING"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    SPLIT_FILE_MISSING = "SPLIT_FILE_MISSING"
    SPLIT_FILE_UNEXPECTED = "SPLIT_FILE_UNEXPECTED"
    SPLIT_HASH_MISMATCH = "SPLIT_HASH_MISMATCH"
    DATASET_HASH_MISMATCH = "DATASET_HASH_MISMATCH"
    SOURCE_CORPUS_HASH_MISMATCH = "SOURCE_CORPUS_HASH_MISMATCH"
    DATASET_SCHEMA_INVALID = "DATASET_SCHEMA_INVALID"
    DATASET_IDENTITY_MISMATCH = "DATASET_IDENTITY_MISMATCH"
    SPLIT_CASE_MISMATCH = "SPLIT_CASE_MISMATCH"
    MANIFEST_COUNT_MISMATCH = "MANIFEST_COUNT_MISMATCH"


class FrozenDatasetVerificationIssue(SchemaModel):
    code: FrozenDatasetVerificationIssueCode
    message: str = Field(min_length=1, max_length=4096)
    path: str | None = Field(default=None, max_length=4096)


class FrozenDatasetVerificationReport(SchemaModel):
    valid: bool
    issues: tuple[FrozenDatasetVerificationIssue, ...] = ()

    @model_validator(mode="after")
    def validate_report(self) -> "FrozenDatasetVerificationReport":
        if self.valid == bool(self.issues):
            raise ValueError(
                "frozen verification report must be valid exactly when issues "
                "are empty"
            )
        return self
