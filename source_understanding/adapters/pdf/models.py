from __future__ import annotations

from dataclasses import dataclass


PdfRect = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PdfSpanObservation:
    text: str
    bbox: PdfRect
    displayed_bbox: PdfRect
    font_name: str | None
    font_size: float | None
    flags: int
    color: int | None
    alpha: int | None
    origin: tuple[float, float] | None
    native_order: int
    line_index: int
    span_index: int


@dataclass(frozen=True, slots=True)
class PdfLineObservation:
    bbox: PdfRect
    displayed_bbox: PdfRect
    writing_mode: int | None
    direction: tuple[float, float] | None
    spans: tuple[PdfSpanObservation, ...]
    native_order: int


@dataclass(frozen=True, slots=True)
class PdfBlockObservation:
    page_number: int
    native_block_number: int
    native_order: int
    bbox: PdfRect
    displayed_bbox: PdfRect
    lines: tuple[PdfLineObservation, ...]

    @property
    def text_character_count(self) -> int:
        return sum(len(span.text) for line in self.lines for span in line.spans)


@dataclass(frozen=True, slots=True)
class PdfOccludedTextObservation:
    native_block_number: int
    native_order: int
    bbox: PdfRect
    displayed_bbox: PdfRect
    text_character_count: int
    paint_seqno: int
    occluder_seqno: int
    occluder_bbox: PdfRect
    coverage_ratio: float


@dataclass(frozen=True, slots=True)
class PdfPageObservation:
    page_number: int
    width_points: float
    height_points: float
    rotation: int
    cropbox: PdfRect
    mediabox: PdfRect
    cropbox_position: tuple[float, float]
    native_text_blocks: tuple[PdfBlockObservation, ...]
    image_block_count: int
    occluded_text_blocks: tuple[PdfOccludedTextObservation, ...] = ()
