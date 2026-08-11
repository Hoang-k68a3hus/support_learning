from __future__ import annotations

from collections import Counter

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import (
    BoundingBox,
    Provenance,
    RawElement,
    SourceLocation,
    StyleInfo,
)
from source_understanding.source_attributes import (
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)

from ..base import AdapterError
from .models import PdfBlockObservation, PdfPageObservation, PdfSpanObservation


class PdfRawElementEmitter:
    """Project one native text block into an auditable derived RawElement."""

    def __init__(
        self,
        *,
        adapter_name: str,
        adapter_version: str,
        reading_order_version: str,
        block_reconstruction_version: str,
        bbox_tolerance_points: float,
        preserve_span_metadata: bool,
    ) -> None:
        self.adapter_name = adapter_name
        self.adapter_version = adapter_version
        self.reading_order_version = reading_order_version
        self.block_reconstruction_version = block_reconstruction_version
        self.bbox_tolerance_points = bbox_tolerance_points
        self.preserve_span_metadata = preserve_span_metadata

    def emit(
        self,
        block: PdfBlockObservation,
        *,
        page: PdfPageObservation,
        reading_index: int,
        global_order: int,
        backend: object,
    ) -> RawElement | None:
        text, line_metadata, span_metadata, newline_offsets = self.reconstruct_block(
            block, page=page
        )
        if not text.strip():
            return None
        bbox, clipped = self.normalized_bbox(
            block.displayed_bbox,
            width=page.width_points,
            height=page.height_points,
        )
        attributes: dict[str, object] = {
            SOURCE_ZONE_ATTRIBUTE: "body",
            SOURCE_ANCHOR_ATTRIBUTE: {
                "kind": "pdf_native_block",
                "id": f"page:{block.page_number}:block:{block.native_block_number}",
            },
            "pdf_page": block.page_number,
            "pdf_native_block_number": block.native_block_number,
            "pdf_native_order": block.native_order,
            "pdf_reading_order": reading_index,
            "pdf_reading_order_version": self.reading_order_version,
            "pdf_block_reconstruction_version": self.block_reconstruction_version,
            "pdf_native_bbox_points": list(block.bbox),
            "pdf_displayed_bbox_points": list(block.displayed_bbox),
            "pdf_bbox_clipped_to_visible_page": clipped,
            "pdf_inserted_line_break_offsets": newline_offsets,
            "pdf_line_count": len(block.lines),
            "pdf_lines": line_metadata,
            "pdf_span_count": sum(len(line.spans) for line in block.lines),
            "pdf_text_character_count": block.text_character_count,
        }
        if self.preserve_span_metadata:
            attributes["pdf_spans"] = span_metadata

        backend_name = str(getattr(backend, "name"))
        backend_version = str(getattr(backend, "version"))
        mupdf_version = getattr(backend, "mupdf_version", None)
        return RawElement(
            text=text,
            type_hint="PARAGRAPH",
            order=global_order,
            location=SourceLocation(
                source=StructureSource.DERIVED,
                page=block.page_number,
                bbox=bbox,
            ),
            style=self.dominant_style(block),
            attributes=attributes,
            provenance=Provenance(
                source=StructureSource.DERIVED,
                extractor=backend_name,
                extractor_version=backend_version,
                metadata={
                    "adapter": self.adapter_name,
                    "adapter_version": self.adapter_version,
                    "mupdf_version": mupdf_version,
                    "text_extraction": "TextPage DICT sort=False",
                    "reading_order": self.reading_order_version,
                    "block_reconstruction": self.block_reconstruction_version,
                },
            ),
        )

    def reconstruct_block(
        self,
        block: PdfBlockObservation,
        *,
        page: PdfPageObservation,
    ) -> tuple[
        str,
        list[dict[str, object]],
        list[dict[str, object]],
        list[int],
    ]:
        parts: list[str] = []
        lines_out: list[dict[str, object]] = []
        spans_out: list[dict[str, object]] = []
        newlines: list[int] = []
        cursor = 0

        for line_index, line in enumerate(block.lines):
            line_bbox, line_clipped = self.normalized_bbox(
                line.displayed_bbox,
                width=page.width_points,
                height=page.height_points,
            )
            lines_out.append(
                {
                    "line_index": line_index,
                    "native_order": line.native_order,
                    "bbox": line_bbox.model_dump(mode="json"),
                    "native_bbox_points": list(line.bbox),
                    "displayed_bbox_points": list(line.displayed_bbox),
                    "bbox_clipped_to_visible_page": line_clipped,
                    "writing_mode": line.writing_mode,
                    "direction": (
                        list(line.direction) if line.direction is not None else None
                    ),
                    "span_count": len(line.spans),
                }
            )
            if line_index:
                parts.append("\n")
                newlines.append(cursor)
                cursor += 1
            for span in line.spans:
                start = cursor
                parts.append(span.text)
                cursor += len(span.text)
                if self.preserve_span_metadata:
                    span_bbox, clipped = self.normalized_bbox(
                        span.displayed_bbox,
                        width=page.width_points,
                        height=page.height_points,
                    )
                    spans_out.append(
                        self.span_metadata(
                            span,
                            start=start,
                            end=cursor,
                            bbox=span_bbox,
                            clipped=clipped,
                        )
                    )
        return "".join(parts), lines_out, spans_out, newlines

    @staticmethod
    def span_metadata(
        span: PdfSpanObservation,
        *,
        start: int,
        end: int,
        bbox: BoundingBox,
        clipped: bool,
    ) -> dict[str, object]:
        return {
            "native_order": span.native_order,
            "line_index": span.line_index,
            "span_index": span.span_index,
            "start_char": start,
            "end_char": end,
            "bbox": bbox.model_dump(mode="json"),
            "native_bbox_points": list(span.bbox),
            "displayed_bbox_points": list(span.displayed_bbox),
            "bbox_clipped_to_visible_page": clipped,
            "font_name": span.font_name,
            "font_size": span.font_size,
            "flags": span.flags,
            "color": span.color,
            "alpha": span.alpha,
            "origin_points": list(span.origin) if span.origin is not None else None,
        }

    def normalized_bbox(
        self,
        bbox: tuple[float, float, float, float],
        *,
        width: float,
        height: float,
    ) -> tuple[BoundingBox, bool]:
        if width <= 0 or height <= 0:
            raise AdapterError("cannot normalize PDF bbox against non-positive page size")
        x0, y0, x1, y1 = bbox
        tolerance = self.bbox_tolerance_points
        if (
            x1 < -tolerance
            or y1 < -tolerance
            or x0 > width + tolerance
            or y0 > height + tolerance
        ):
            raise AdapterError(
                "PDF text bbox lies outside the visible displayed page by more than tolerance"
            )
        clipped_coords = (
            min(width, max(0.0, x0)),
            min(height, max(0.0, y0)),
            min(width, max(0.0, x1)),
            min(height, max(0.0, y1)),
        )
        clipped = clipped_coords != bbox
        cx0, cy0, cx1, cy1 = clipped_coords
        if cx1 < cx0 or cy1 < cy0:
            raise AdapterError("PDF bbox becomes invalid after visible-page clipping")
        return (
            BoundingBox(
                x0=cx0 / width,
                y0=cy0 / height,
                x1=cx1 / width,
                y1=cy1 / height,
            ),
            clipped,
        )

    @staticmethod
    def dominant_style(block: PdfBlockObservation) -> StyleInfo | None:
        weighted: Counter[
            tuple[str | None, float | None, bool, bool, int | None]
        ] = Counter()
        for line in block.lines:
            for span in line.spans:
                if not span.text:
                    continue
                key = (
                    span.font_name,
                    round(span.font_size, 4) if span.font_size is not None else None,
                    bool(span.flags & (1 << 4)),
                    bool(span.flags & (1 << 1)),
                    span.color,
                )
                weighted[key] += max(1, len(span.text))
        if not weighted:
            return None
        (font_name, font_size, bold, italic, color), _weight = weighted.most_common(1)[0]
        return StyleInfo(
            font_name=font_name,
            font_size=font_size,
            bold=bold,
            italic=italic,
            color=(
                f"#{color:06x}"
                if color is not None and 0 <= color <= 0xFFFFFF
                else None
            ),
            attributes={
                "style_source": "pymupdf_span_flags",
                "dominance": "character_weighted_mode",
            },
        )
