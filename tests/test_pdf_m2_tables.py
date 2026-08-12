from __future__ import annotations

import unittest

import pymupdf

from source_understanding.adapters import PdfAdapter, SourceAdapterRunner
from source_understanding.adapters.pdf.models import (
    PdfBlockObservation,
    PdfLineObservation,
    PdfSpanObservation,
)
from source_understanding.adapters.pdf.tables import PdfTableDetector
from source_understanding.schemas.element import ElementType
from source_understanding.schemas.logical_unit import LogicalUnitType
from source_understanding.source_attributes import INTEGRITY_GROUP_ID_ATTRIBUTE


def pdf_bytes(builder) -> bytes:
    document = pymupdf.open()
    try:
        builder(document)
        return document.tobytes()
    finally:
        document.close()


def draw_grid_table(
    page,
    values: tuple[tuple[str, ...], ...],
    *,
    x0: float = 40.0,
    y0: float = 80.0,
    cell_width: float = 120.0,
    cell_height: float = 45.0,
) -> None:
    rows = len(values)
    columns = len(values[0])
    for column in range(columns + 1):
        x = x0 + column * cell_width
        page.draw_line((x, y0), (x, y0 + rows * cell_height))
    for row in range(rows + 1):
        y = y0 + row * cell_height
        page.draw_line((x0, y), (x0 + columns * cell_width, y))
    for row, row_values in enumerate(values):
        for column, value in enumerate(row_values):
            page.insert_text(
                (
                    x0 + column * cell_width + 8.0,
                    y0 + row * cell_height + 27.0,
                ),
                value,
                fontsize=10,
            )


class PdfM2TableTests(unittest.TestCase):
    def test_bordered_table_becomes_integrity_structure_without_duplicate_paragraphs(self) -> None:
        values = (
            ("Name", "Score"),
            ("Ada", "10"),
            ("Bob", "9"),
        )

        def build(document) -> None:
            page = document.new_page(width=400, height=320)
            page.insert_text((40, 40), "Results", fontsize=12)
            draw_grid_table(page, values)

        result = PdfAdapter().adapt(pdf_bytes(build))
        type_hints = [item.type_hint for item in result.raw_elements]
        self.assertEqual(type_hints[0], "PARAGRAPH")
        self.assertEqual(type_hints[1], "TABLE")
        self.assertEqual(type_hints.count("TABLE_ROW"), 3)
        self.assertEqual(type_hints.count("TABLE_CELL"), 6)
        self.assertEqual(type_hints.count("PARAGRAPH"), 1)

        table_elements = [item for item in result.raw_elements if item.type_hint != "PARAGRAPH"]
        group_ids = {
            item.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] for item in table_elements
        }
        self.assertEqual(len(group_ids), 1)
        self.assertEqual(
            [item.text for item in result.raw_elements if item.type_hint == "TABLE_CELL"],
            ["Name", "Score", "Ada", "10", "Bob", "9"],
        )
        cell_values = {value for row in values for value in row}
        self.assertFalse(
            any(
                item.type_hint == "PARAGRAPH" and item.text in cell_values
                for item in result.raw_elements
            )
        )
        first_cell = next(item for item in result.raw_elements if item.type_hint == "TABLE_CELL")
        self.assertEqual(first_cell.attributes["row_index"], 0)
        self.assertEqual(first_cell.attributes["cell_index"], 0)
        self.assertTrue(first_cell.attributes["pdf_source_spans"])
        self.assertEqual(first_cell.location.page, 1)

        codes = {item.code for item in result.diagnostics}
        self.assertIn("PDF_TABLE_STRUCTURE_EXTRACTED_M2", codes)
        self.assertNotIn("PDF_ALIGNED_LAYOUT_NOT_STRUCTURED_M1", codes)
        pdf_metadata = result.metadata.attributes["pdf"]
        self.assertEqual(pdf_metadata["extracted_table_count"], 1)
        self.assertEqual(pdf_metadata["pages_with_extracted_tables"], 1)
        self.assertEqual(pdf_metadata["pages"][0]["extracted_table_count"], 1)

    def test_small_2x2_grid_stays_unstructured_and_reports_limit(self) -> None:
        values = (("A", "B"), ("C", "D"))

        def build(document) -> None:
            page = document.new_page(width=400, height=260)
            draw_grid_table(page, values)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertNotIn("TABLE", {item.type_hint for item in result.raw_elements})
        self.assertEqual(
            "".join(item.text or "" for item in result.raw_elements).replace("\n", ""),
            "ABCD",
        )
        rejected = [
            item
            for item in result.diagnostics
            if item.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertTrue(rejected[0].affects_structural_completeness)
        self.assertEqual(rejected[0].metadata["reason_counts"], {"candidate_too_small": 1})

    def test_source_block_crossing_table_boundary_is_rejected_fail_closed(self) -> None:
        cells = (
            ((40.0, 80.0, 160.0, 125.0), (160.0, 80.0, 280.0, 125.0)),
            ((40.0, 125.0, 160.0, 170.0), (160.0, 125.0, 280.0, 170.0)),
            ((40.0, 170.0, 160.0, 215.0), (160.0, 170.0, 280.0, 215.0)),
        )

        class Row:
            def __init__(self, row_cells) -> None:
                self.cells = row_cells

        class Table:
            bbox = (40.0, 80.0, 280.0, 215.0)
            row_count = 3
            col_count = 2
            rows = tuple(Row(row) for row in cells)

        class Finder:
            tables = (Table(),)

        class FakePage:
            rect = pymupdf.Rect(0.0, 0.0, 400.0, 300.0)
            rotation = 0
            rotation_matrix = pymupdf.Matrix(1, 1)

            def get_drawings(self):
                return [
                    {
                        "items": [
                            ("re", pymupdf.Rect(40.0, 80.0, 280.0, 215.0)),
                            ("l", pymupdf.Point(160.0, 80.0), pymupdf.Point(160.0, 215.0)),
                            ("l", pymupdf.Point(40.0, 125.0), pymupdf.Point(280.0, 125.0)),
                        ]
                    }
                ]

            def find_tables(self, **_kwargs):
                return Finder()

        inside = PdfSpanObservation(
            text="inside",
            bbox=(50.0, 90.0, 100.0, 105.0),
            displayed_bbox=(50.0, 90.0, 100.0, 105.0),
            font_name=None,
            font_size=10.0,
            flags=0,
            color=None,
            alpha=None,
            origin=None,
            native_order=0,
            line_index=0,
            span_index=0,
        )
        outside = PdfSpanObservation(
            text="outside",
            bbox=(300.0, 90.0, 350.0, 105.0),
            displayed_bbox=(300.0, 90.0, 350.0, 105.0),
            font_name=None,
            font_size=10.0,
            flags=0,
            color=None,
            alpha=None,
            origin=None,
            native_order=1,
            line_index=0,
            span_index=1,
        )
        line = PdfLineObservation(
            bbox=(50.0, 90.0, 350.0, 105.0),
            displayed_bbox=(50.0, 90.0, 350.0, 105.0),
            writing_mode=0,
            direction=(1.0, 0.0),
            spans=(inside, outside),
            native_order=0,
        )
        block = PdfBlockObservation(
            page_number=1,
            native_block_number=0,
            native_order=0,
            bbox=line.bbox,
            displayed_bbox=line.displayed_bbox,
            lines=(line,),
        )
        detection = PdfTableDetector().detect(FakePage(), (block,))
        self.assertEqual(detection.tables, ())
        self.assertEqual(len(detection.rejected), 1)
        self.assertEqual(
            detection.rejected[0].reason,
            "source_block_crosses_table_boundary",
        )

    def test_malformed_candidate_is_rejected_without_crashing_page_detection(self) -> None:
        class BrokenTable:
            @property
            def bbox(self):
                raise IndexError("malformed candidate geometry")

        class Finder:
            tables = (BrokenTable(),)

        class FakePage:
            rect = pymupdf.Rect(0.0, 0.0, 400.0, 300.0)
            rotation = 0
            rotation_matrix = pymupdf.Matrix(1, 1)

            def get_drawings(self):
                return [
                    {
                        "items": [
                            ("re", pymupdf.Rect(40.0, 80.0, 280.0, 215.0)),
                            ("l", pymupdf.Point(160.0, 80.0), pymupdf.Point(160.0, 215.0)),
                            ("l", pymupdf.Point(40.0, 125.0), pymupdf.Point(280.0, 125.0)),
                        ]
                    }
                ]

            def find_tables(self, **_kwargs):
                return Finder()

        span = PdfSpanObservation(
            text="preserve me",
            bbox=(50.0, 90.0, 120.0, 105.0),
            displayed_bbox=(50.0, 90.0, 120.0, 105.0),
            font_name=None,
            font_size=10.0,
            flags=0,
            color=None,
            alpha=None,
            origin=None,
            native_order=0,
            line_index=0,
            span_index=0,
        )
        line = PdfLineObservation(
            bbox=span.bbox,
            displayed_bbox=span.displayed_bbox,
            writing_mode=0,
            direction=(1.0, 0.0),
            spans=(span,),
            native_order=0,
        )
        block = PdfBlockObservation(
            page_number=1,
            native_block_number=0,
            native_order=0,
            bbox=line.bbox,
            displayed_bbox=line.displayed_bbox,
            lines=(line,),
        )

        detection = PdfTableDetector().detect(FakePage(), (block,))
        self.assertEqual(detection.tables, ())
        self.assertEqual(len(detection.rejected), 1)
        self.assertEqual(detection.rejected[0].reason, "candidate_inspection_failed")
        self.assertIn("IndexError", detection.rejected[0].detail or "")

    def test_table_structure_is_deterministic_and_consolidates_to_table_block(self) -> None:
        values = (("K", "V"), ("A", "1"), ("B", "2"))

        def build(document) -> None:
            page = document.new_page(width=400, height=300)
            draw_grid_table(page, values)

        payload = pdf_bytes(build)
        adapter = PdfAdapter()
        first = adapter.adapt(payload)
        second = adapter.adapt(payload)
        self.assertEqual(first, second)

        understood = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=adapter,
            document_id="pdf-m2-table",
        )
        canonical_types = {
            element.type for element in understood.understanding.structural_document.elements
        }
        self.assertIn(ElementType.TABLE, canonical_types)
        self.assertIn(ElementType.TABLE_ROW, canonical_types)
        self.assertIn(ElementType.TABLE_CELL, canonical_types)
        table_units = [
            unit
            for unit in understood.understanding.grouping_result.logical_units
            if unit.type == LogicalUnitType.TABLE_BLOCK
        ]
        self.assertEqual(len(table_units), 1)
        self.assertTrue(understood.preservation_report.fully_preserved)


if __name__ == "__main__":
    unittest.main()