from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
Label = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class SchemaModel(BaseModel):
    """Base model for source-understanding schemas.

    Models reject unknown fields so schema drift is explicit instead of silent.
    Assignment validation catches invalid mutations in long-running workers.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
    )


class StructureSource(StrEnum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    DERIVED = "DERIVED"


class StructureMode(StrEnum):
    FLAT = "FLAT"
    LOCAL = "LOCAL"
    GROUPED = "GROUPED"
    HIERARCHICAL = "HIERARCHICAL"
    MIXED = "MIXED"


class ContextNode(SchemaModel):
    id: Identifier
    type: Label
    label: Label
    level: int | None = Field(default=None, ge=0)
    source: StructureSource = StructureSource.EXPLICIT
    confidence: Confidence = 1.0
    parent_id: Identifier | None = None
    attributes: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_not_self_parent(self) -> ContextNode:
        if self.parent_id == self.id:
            raise ValueError("context node cannot be its own parent")
        return self


class ContextNodeRef(SchemaModel):
    id: Identifier
    type: Label | None = None
    label: Label | None = None
    source: StructureSource | None = None
    confidence: Confidence | None = None
