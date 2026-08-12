from __future__ import annotations

from collections import Counter

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Provenance, RawElement, SourceLocation, StyleInfo
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)

from .emit import PdfRawElementEmitter
from .models import PdfPageObservation
from .tables import (
    PDF_TABLE_STRUCTURE_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfTableCellObservation,
    PdfTableObservation,
)


class PdfTableRawElementEmitter:
    """Project one verified geometry-derived table without losing source-span audit facts."""

    def __init__(
        self,
        *,
        adapter_name: str,
        adapter_version: str,
        base_emitter: PdfRawElementEmitter,
        reading_order_version: str,
    ) -> None:
        self.adapter_name = adapter_name
        self.adapter_version = adapter_version
        self.base_emitter = base_emitter
        self.reading_order_version = reading_order_version

    def emit(
        self,
        table: PdfTableObservation,
        *,
        page: PdfPageObservation,
        global_order: int,
        reading_index: int,
        backend: object,
    ) -> tuple[RawElement, ...]:
        group_id = f"pdf-table:p{page.page_number}:t{table.table_index}"
        common = {
            SOURCE_ZONE_ATTRIBUTE: "body",
            INTEGRITY_GROUP_ID_ATTRIBUTE: group_id,
            "native_integrity_kind": "table",
            "integrity_evidence": "pdf_vector_geometry",
            "pdf_table_structure_version": PDF_TABLE_STRUCTURE_VERSION,
            "pdf_table_text_reconstruction_version": (
                PDF_TABLE_TEXT_RECONSTRUCTION_VERSION
            ),
            "pdf_table_detection_strategy": table.detection_strategy,
            "pdf_page": page.page_number,
            "pdf_reading_order": reading_index,
            "pdf_reading_order_version": self.reading_order_version,
            "pdf_reading_order_action": "preserve_native_table_anchor",
            "pdf_table_index": table.table_index,
            "pdf_source_block_numbers": list(table.source_block_numbers),
            "pdf_source_native_orders": list(table.source_native_orders),
        }
        backend_name = str(getattr(backend, "name"))
        backend_version = str(getattr(backend, "version"))
        raw_mupdf_version = getattr(backend, "mupdf_version", None)
        mupdf_version = (
            str(raw_mupdf_version) if raw_mupdf_version is not None else None
        )

        output: list[RawElement] = []
        table_bbox, table_clipped = self.base_emitter.normalized_bbox(
            table.displayed_bbox,
            width=page.width_points,
            height=page.height_points,
        )
        output.append(
            RawElement(
                text=None,
                type_hint="TABLE",
                order=global_order,
                location=SourceLocation(
                    source=StructureSource.DERIVED,
                    page=page.page_number,
                    bbox=table_bbox,
                ),
                attributes={
                    **common,
                    SOURCE_ANCHOR_ATTRIBUTE: {
                        "kind": "pdf_table",
                        "id": f"page:{page.page_number}:table:{table.table_index}",
                    },
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "pdf_native_bbox_points": list(table.bbox),
                    "pdf_displayed_bbox_points": list(table.displayed_bbox),
                    "pdf_bbox_clipped_to_visible_page": table_clipped,
                },
                provenance=self._provenance(
                    backend_name=backend_name,
                    backend_version=backend_version,
                    mupdf_version=mupdf_version,
                ),
            )
        )

        for row in table.rows:
            row_bbox, row_clipped = self.base_emitter.normalized_bbox(
                row.displayed_bbox,
                width=page.width_points,
                height=page.height_points,
            )
            row_text = "\t".join(cell.text for cell in row.cells)
            output.append(
                RawElement(
                    text=row_text,
                    type_hint="TABLE_ROW",
                    order=global_order + len(output),
                    location=SourceLocation(
                        source=StructureSource.DERIVED,
                        page=page.page_number,
                        bbox=row_bbox,
                    ),
                    attributes={
                        **common,
                        SOURCE_ANCHOR_ATTRIBUTE: {
                            "kind": "pdf_table_row",
                            "id": (
                                f"page:{page.page_number}:table:{table.table_index}:"
                                f"row:{row.row_index}"
                            ),
                        },
                        "row_index": row.row_index,
                        "pdf_native_bbox_points": list(row.bbox),
                        "pdf_displayed_bbox_points": list(row.displayed_bbox),
                        "pdf_bbox_clipped_to_visible_page": row_clipped,
                    },
                    provenance=self._provenance(
                        backend_name=backend_name,
                        backend_version=backend_version,
                        mupdf_version=mupdf_version,
                    ),
                )
            )

            for cell in row.cells:
                cell_bbox, cell_clipped = self.base_emitter.normalized_bbox(
                    cell.displayed_bbox,
                    width=page.width_points,
                    height=page.height_points,
                )
                output.append(
                    RawElement(
                        text=cell.text,
                        type_hint="TABLE_CELL",
                        order=global_order + len(output),
                        location=SourceLocation(
                            source=StructureSource.DERIVED,
                            page=page.page_number,
                            bbox=cell_bbox,
                        ),
                        style=self._dominant_style(cell),
                        attributes={
                            **common,
                            SOURCE_ANCHOR_ATTRIBUTE: {
                                "kind": "pdf_table_cell",
                                "id": (
                                    f"page:{page.page_number}:table:{table.table_index}:"
                                    f"row:{cell.row_index}:cell:{cell.cell_index}"
                                ),
                            },
                            "row_index": cell.row_index,
                            "cell_index": cell.cell_index,
                            "pdf_native_bbox_points": list(cell.bbox),
                            "pdf_displayed_bbox_points": list(cell.displayed_bbox),
                            "pdf_bbox_clipped_to_visible_page": cell_clipped,
                            "pdf_source_spans": self._source_spans(
                                cell,
                                page=page,
                            ),
                        },
                        provenance=self._provenance(
                            backend_name=backend_name,
                            backend_version=backend_version,
                            mupdf_version=mupdf_version,
                        ),
                    )
                )
        return tuple(output)

    def _source_spans(
        self,
        cell: PdfTableCellObservation,
        *,
        page: PdfPageObservation,
    ) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for fragment in cell.fragments:
            span = fragment.span
            bbox, clipped = self.base_emitter.normalized_bbox(
                span.displayed_bbox,
                width=page.width_points,
                height=page.height_points,
            )
            output.append(
                {
                    "block_number": fragment.block_number,
                    "block_native_order": fragment.block_native_order,
                    "line_native_order": fragment.line_native_order,
                    "span_native_order": span.native_order,
                    "line_index": span.line_index,
                    "span_index": span.span_index,
                    "text": span.text,
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
            )
        return output

    def _provenance(
        self,
        *,
        backend_name: str,
        backend_version: str,
        mupdf_version: str | None,
    ) -> Provenance:
        return Provenance(
            source=StructureSource.DERIVED,
            extractor=backend_name,
            extractor_version=backend_version,
            metadata={
                "adapter": self.adapter_name,
                "adapter_version": self.adapter_version,
                "mupdf_version": mupdf_version,
                "table_detection": PDF_TABLE_STRUCTURE_VERSION,
                "table_text_reconstruction": PDF_TABLE_TEXT_RECONSTRUCTION_VERSION,
                "source_binding": "TextPage spans to verified cell geometry",
            },
        )

    @staticmethod
    def _dominant_style(cell: PdfTableCellObservation) -> StyleInfo | None:
        weighted: Counter[
            tuple[str | None, float | None, bool, bool, int | None]
        ] = Counter()
        for fragment in cell.fragments:
            span = fragment.span
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
                "style_source": "pymupdf_table_source_spans",
                "dominance": "character_weighted_mode",
            },
        )
