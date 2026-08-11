from __future__ import annotations

from collections.abc import Mapping
from types import ModuleType

from .models import (
    PdfBlockObservation,
    PdfLineObservation,
    PdfPageObservation,
    PdfRect,
    PdfSpanObservation,
)


class PdfBackendError(ValueError):
    pass


def load_pymupdf() -> ModuleType:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised in environments without optional dep
        raise PdfBackendError(
            "PdfAdapter requires PyMuPDF; install a supported pymupdf release"
        ) from exc
    return pymupdf


class PyMuPdfNativeBackend:
    """Source-near native text observations backed by PyMuPDF TextPage DICT."""

    name = "pymupdf-native-text"

    def __init__(self) -> None:
        self._pymupdf = load_pymupdf()

    @property
    def version(self) -> str:
        value = getattr(self._pymupdf, "pymupdf_version", None)
        if isinstance(value, str) and value:
            return value
        legacy = getattr(self._pymupdf, "VersionFitz", None)
        return str(legacy) if legacy is not None else "unknown"

    @property
    def mupdf_version(self) -> str | None:
        value = getattr(self._pymupdf, "mupdf_version", None)
        return str(value) if value is not None else None

    def open(self, payload: bytes):
        try:
            return self._pymupdf.open(stream=payload, filetype="pdf")
        except Exception as exc:
            raise PdfBackendError(f"PyMuPDF could not open PDF bytes: {exc}") from exc

    def page_observation(self, page) -> PdfPageObservation:
        page_rect = page.rect
        width = float(page_rect.width)
        height = float(page_rect.height)
        if width <= 0 or height <= 0:
            raise PdfBackendError(
                f"PDF page {page.number + 1} has non-positive visible dimensions"
            )

        try:
            flags = self._pymupdf.TEXTFLAGS_DICT & ~self._pymupdf.TEXT_PRESERVE_IMAGES
            extracted = page.get_text("dict", sort=False, flags=flags)
        except Exception as exc:
            raise PdfBackendError(
                f"native text extraction failed on PDF page {page.number + 1}: {exc}"
            ) from exc
        if not isinstance(extracted, Mapping):
            raise PdfBackendError(
                f"native text extraction returned non-mapping on PDF page {page.number + 1}"
            )

        blocks: list[PdfBlockObservation] = []
        try:
            image_blocks = len(page.get_image_info(hashes=False, xrefs=False))
        except Exception as exc:
            raise PdfBackendError(
                f"image-presence inspection failed on PDF page {page.number + 1}: {exc}"
            ) from exc
        native_order = 0
        line_order = 0
        span_order = 0
        for fallback_block_number, raw_block in enumerate(extracted.get("blocks", ())):
            if not isinstance(raw_block, Mapping):
                continue
            block_type = int(raw_block.get("type", 0))
            if block_type != 0:
                continue
            raw_lines = raw_block.get("lines", ())
            if not isinstance(raw_lines, (list, tuple)):
                continue

            line_items: list[PdfLineObservation] = []
            for line_index, raw_line in enumerate(raw_lines):
                if not isinstance(raw_line, Mapping):
                    continue
                raw_spans = raw_line.get("spans", ())
                if not isinstance(raw_spans, (list, tuple)):
                    continue
                spans: list[PdfSpanObservation] = []
                for span_index, raw_span in enumerate(raw_spans):
                    if not isinstance(raw_span, Mapping):
                        continue
                    text = raw_span.get("text")
                    if not isinstance(text, str):
                        continue
                    bbox = self._rect(raw_span.get("bbox"), context="span")
                    displayed = self._displayed_rect(page, bbox)
                    origin = self._point(raw_span.get("origin"))
                    font = raw_span.get("font")
                    size = raw_span.get("size")
                    color = raw_span.get("color")
                    alpha = raw_span.get("alpha")
                    spans.append(
                        PdfSpanObservation(
                            text=text,
                            bbox=bbox,
                            displayed_bbox=displayed,
                            font_name=str(font) if isinstance(font, str) and font else None,
                            font_size=float(size) if isinstance(size, (int, float)) else None,
                            flags=int(raw_span.get("flags", 0)),
                            color=int(color) if isinstance(color, int) else None,
                            alpha=int(alpha) if isinstance(alpha, int) else None,
                            origin=origin,
                            native_order=span_order,
                            line_index=line_index,
                            span_index=span_index,
                        )
                    )
                    span_order += 1
                if not spans:
                    continue
                line_bbox = self._rect(raw_line.get("bbox"), context="line")
                raw_direction = raw_line.get("dir")
                direction = self._point(raw_direction)
                writing_mode = raw_line.get("wmode")
                line_items.append(
                    PdfLineObservation(
                        bbox=line_bbox,
                        displayed_bbox=self._displayed_rect(page, line_bbox),
                        writing_mode=(
                            int(writing_mode) if isinstance(writing_mode, int) else None
                        ),
                        direction=direction,
                        spans=tuple(spans),
                        native_order=line_order,
                    )
                )
                line_order += 1
            if not line_items:
                continue
            block_bbox = self._rect(raw_block.get("bbox"), context="block")
            number = raw_block.get("number")
            block_number = (
                int(number) if isinstance(number, int) else fallback_block_number
            )
            blocks.append(
                PdfBlockObservation(
                    page_number=page.number + 1,
                    native_block_number=block_number,
                    native_order=native_order,
                    bbox=block_bbox,
                    displayed_bbox=self._displayed_rect(page, block_bbox),
                    lines=tuple(line_items),
                )
            )
            native_order += 1

        cropbox = page.cropbox
        mediabox = page.mediabox
        cropbox_position = page.cropbox_position
        return PdfPageObservation(
            page_number=page.number + 1,
            width_points=width,
            height_points=height,
            rotation=int(page.rotation),
            cropbox=(
                float(cropbox.x0),
                float(cropbox.y0),
                float(cropbox.x1),
                float(cropbox.y1),
            ),
            mediabox=(
                float(mediabox.x0),
                float(mediabox.y0),
                float(mediabox.x1),
                float(mediabox.y1),
            ),
            cropbox_position=(
                float(cropbox_position.x),
                float(cropbox_position.y),
            ),
            native_text_blocks=tuple(blocks),
            image_block_count=image_blocks,
        )

    def _displayed_rect(self, page, bbox: PdfRect) -> PdfRect:
        rect = self._pymupdf.Rect(bbox)
        if int(page.rotation) % 360:
            rect = rect * page.rotation_matrix
        return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))

    @staticmethod
    def _point(value: object) -> tuple[float, float] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        x, y = value
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return (float(x), float(y))

    @staticmethod
    def _rect(value: object, *, context: str) -> PdfRect:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise PdfBackendError(f"PDF {context} is missing a valid bbox")
        coords: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)):
                raise PdfBackendError(f"PDF {context} bbox contains a non-numeric coordinate")
            coords.append(float(item))
        x0, y0, x1, y1 = coords
        if x1 < x0 or y1 < y0:
            raise PdfBackendError(f"PDF {context} bbox has inverted extents")
        return (x0, y0, x1, y1)
