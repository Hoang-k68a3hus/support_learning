from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from source_understanding.schemas.context import Identifier, JsonObject, SchemaModel
from source_understanding.schemas.document import SemanticAnnotationType


WORKING_BATCH_SCHEMA_VERSION = "1"


class WorkingBatch(SchemaModel):
    schema_version: str = WORKING_BATCH_SCHEMA_VERSION
    batch_id: Identifier
    name: str = Field(min_length=1, max_length=256)
    guideline_version: str = Field(min_length=1, max_length=128)
    created_by: Identifier
    created_at: datetime
    evaluated_types: tuple[SemanticAnnotationType, ...] = Field(min_length=1)
    record_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_batch(self) -> "WorkingBatch":
        if self.schema_version != WORKING_BATCH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported working batch schema_version {self.schema_version!r}"
            )
        if not self.name.strip() or self.name.strip() != self.name:
            raise ValueError("working batch name must be non-blank and trimmed")
        if (
            not self.guideline_version.strip()
            or self.guideline_version.strip() != self.guideline_version
        ):
            raise ValueError(
                "working batch guideline_version must be non-blank and trimmed"
            )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("working batch created_at must be timezone-aware")
        if len(self.record_ids) != len(set(self.record_ids)):
            raise ValueError("working batch record_ids must be unique")
        if len(self.evaluated_types) != len(set(self.evaluated_types)):
            raise ValueError("working batch evaluated_types must be unique")
        canonical_types = tuple(
            annotation_type
            for annotation_type in SemanticAnnotationType
            if annotation_type in self.evaluated_types
        )
        if self.evaluated_types != canonical_types:
            raise ValueError(
                "working batch evaluated_types must use canonical semantic order"
            )
        return self

