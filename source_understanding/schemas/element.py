from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .context import Confidence, Identifier, SchemaModel, StructureSource


class ElementType(StrEnum):
    TITLE = "TITLE"
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    SENTENCE = "SENTENCE"
    LINE = "LINE"
    LIST = "LIST"
    LIST_ITEM = "LIST_ITEM"
    TABLE = "TABLE"
    TABLE_ROW = "TABLE_ROW"
    TABLE_CELL = "TABLE_CELL"
    CODE = "CODE"
    FORMULA = "FORMULA"
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    DIALOGUE_TURN = "DIALOGUE_TURN"
    LOG_ENTRY = "LOG_ENTRY"
    KEY_VALUE = "KEY_VALUE"
    FIGURE = "FIGURE"
    CHART = "CHART"
    CAPTION = "CAPTION"
    FOOTNOTE = "FOOTNOTE"
    SEPARATOR = "SEPARATOR"
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    PAGE_NUMBER = "PAGE_NUMBER"
    UNKNOWN = "UNKNOWN"


class BoundingBox(SchemaModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_extents(self) -> BoundingBox:
        if self.x1 < self.x0:
            raise ValueError("bbox x1 must be >= x0")
        if self.y1 < self.y0:
            raise ValueError("bbox y1 must be >= y0")
        return self


class SourceLocation(SchemaModel):
    page: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> SourceLocation:
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


class StyleInfo(SchemaModel):
    font_name: str | None = None
    font_size: float | None = Field(default=None, gt=0)
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None
    alignment: str | None = None
    indentation: float | None = None
    attributes: dict[str, object] = Field(default_factory=dict)


class ElementConfidence(SchemaModel):
    overall: Confidence = 1.0
    text: Confidence | None = None
    type: Confidence | None = None
    order: Confidence | None = None
    location: Confidence | None = None


class TransformationRecord(SchemaModel):
    operation: str = Field(min_length=1, max_length=128)
    before: str | None = None
    after: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class Provenance(SchemaModel):
    source: StructureSource = StructureSource.EXPLICIT
    extractor: str = Field(min_length=1, max_length=256)
    extractor_version: str | None = Field(default=None, max_length=128)
    confidence: Confidence = 1.0
    transformations: list[TransformationRecord] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class RawElement(SchemaModel):
    """Adapter-facing element before canonical normalization."""

    text: str | None = None
    type_hint: str | None = Field(default=None, max_length=128)
    order: int = Field(ge=0)
    location: SourceLocation | None = None
    style: StyleInfo | None = None
    attributes: dict[str, object] = Field(default_factory=dict)


class Element(SchemaModel):
    id: Identifier
    type: ElementType = ElementType.UNKNOWN
    order: int = Field(ge=0)
    raw_text: str | None = None
    normalized_text: str | None = None
    location: SourceLocation | None = None
    style: StyleInfo | None = None
    attributes: dict[str, object] = Field(default_factory=dict)
    confidence: ElementConfidence = Field(default_factory=ElementConfidence)
    provenance: Provenance
    exclude_from_retrieval: bool = False

    @property
    def text(self) -> str | None:
        return self.normalized_text if self.normalized_text is not None else self.raw_text
