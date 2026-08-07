from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from .context import Confidence, ContextNodeRef, Identifier, JsonObject, SchemaModel
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

    def identity_key(self) -> tuple[object, ...]:
        bbox_key = None
        if self.bbox is not None:
            bbox_key = (self.bbox.x0, self.bbox.y0, self.bbox.x1, self.bbox.y1)
        return (
            self.source_id,
            self.element_id,
            self.page,
            bbox_key,
            self.start_char,
            self.end_char,
            self.line_start,
            self.line_end,
        )


class RetrievalUnit(SchemaModel):
    """Task-facing projection that remains fully traceable to one source."""

    id: Identifier
    document_id: Identifier
    subdocument_id: Identifier | None = None
    logical_unit_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    element_ids: tuple[Identifier, ...] = Field(min_length=1)
    retrieval_text: str = Field(min_length=1)
    display_text: str = Field(min_length=1)
    context_path: tuple[ContextNodeRef, ...] = Field(default_factory=tuple)
    semantic_annotations: tuple[AnnotationRef, ...] = Field(default_factory=tuple)
    source_anchors: tuple[SourceAnchor, ...] = Field(min_length=1)
    unit_type: RetrievalUnitType = RetrievalUnitType.TEXT
    token_count: int = Field(ge=1)
    quality: Confidence = 1.0
    version: str = Field(min_length=1, max_length=128)
    metadata: JsonObject = Field(default_factory=dict)

    @property
    def source_id(self) -> str:
        """Alias matching SourceAnchor/source-scope terminology."""
        return self.document_id

    @field_validator("retrieval_text", "display_text", "version")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace characters")
        return value

    @model_validator(mode="after")
    def validate_refs_and_anchors(self) -> RetrievalUnit:
        for name, values in (
            ("logical_unit_ids", self.logical_unit_ids),
            ("element_ids", self.element_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")

        context_ids = [ref.id for ref in self.context_path]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("context_path ids must be unique")

        annotation_ids = [ref.id for ref in self.semantic_annotations]
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("semantic annotation ids must be unique")

        anchor_keys = [anchor.identity_key() for anchor in self.source_anchors]
        if len(anchor_keys) != len(set(anchor_keys)):
            raise ValueError("source_anchors must be unique")

        element_ids = set(self.element_ids)
        covered_elements: set[str] = set()
        for anchor in self.source_anchors:
            if anchor.source_id != self.document_id:
                raise ValueError(
                    f"source anchor {anchor.element_id!r} uses source_id "
                    f"{anchor.source_id!r}, expected {self.document_id!r}"
                )
            if anchor.element_id not in element_ids:
                raise ValueError(
                    f"source anchor references element {anchor.element_id!r} "
                    "outside retrieval unit element_ids"
                )
            covered_elements.add(anchor.element_id)

        missing_anchors = element_ids - covered_elements
        if missing_anchors:
            raise ValueError(
                "every retrieval element must have at least one source anchor; "
                f"missing: {sorted(missing_anchors)}"
            )
        return self
