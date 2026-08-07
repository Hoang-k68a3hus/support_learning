from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .context import Confidence, ContextNodeRef, Identifier, SchemaModel
from .element import BoundingBox


class RetrievalUnitType(StrEnum):
    TEXT = "TEXT"
    SECTION = "SECTION"
    QA_PAIR = "QA_PAIR"
    DIALOGUE = "DIALOGUE"
    PROCEDURE = "PROCEDURE"
    DEFINITION = "DEFINITION"
    EXAMPLE = "EXAMPLE"
    EXERCISE = "EXERCISE"
    CODE = "CODE"
    TABLE = "TABLE"
    LOG = "LOG"
    LIST = "LIST"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class AnnotationRef(SchemaModel):
    id: Identifier
    type: str | None = Field(default=None, max_length=128)
    value: str | None = Field(default=None, max_length=2048)
    confidence: Confidence | None = None


class SourceAnchor(SchemaModel):
    source_id: Identifier
    element_id: Identifier
    page: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_location(self) -> SourceAnchor:
        if self.bbox is not None and self.page is None:
            raise ValueError("bbox requires page")
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("start_char and end_char must be provided together")
        if self.start_char is not None and self.end_char < self.start_char:
            raise ValueError("end_char must be >= start_char")
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must be provided together")
        if self.line_start is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class RetrievalUnit(SchemaModel):
    id: Identifier
    document_id: Identifier
    subdocument_id: Identifier | None = None
    logical_unit_ids: list[Identifier] = Field(default_factory=list)
    element_ids: list[Identifier] = Field(min_length=1)
    retrieval_text: str = Field(min_length=1)
    display_text: str = Field(min_length=1)
    context_path: list[ContextNodeRef] = Field(default_factory=list)
    semantic_annotations: list[AnnotationRef] = Field(default_factory=list)
    source_anchors: list[SourceAnchor] = Field(default_factory=list)
    unit_type: RetrievalUnitType = RetrievalUnitType.TEXT
    token_count: int = Field(ge=0)
    quality: Confidence = 1.0
    version: str = Field(min_length=1, max_length=128)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> RetrievalUnit:
        for name, values in (
            ("logical_unit_ids", self.logical_unit_ids),
            ("element_ids", self.element_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        anchor_keys = [
            (
                a.source_id,
                a.element_id,
                a.page,
                a.start_char,
                a.end_char,
                a.line_start,
                a.line_end,
            )
            for a in self.source_anchors
        ]
        if len(anchor_keys) != len(set(anchor_keys)):
            raise ValueError("source_anchors must be unique")
        return self
