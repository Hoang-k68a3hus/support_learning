from __future__ import annotations

import unittest

import pymupdf

from source_understanding.adapters import PdfAdapter, SourceAdapterRunner
from source_understanding.adapters.pdf.models import (
    PdfBlockObservation,
    PdfLineObservation,
    PdfSpanObservation,
)
from source_understanding.adapters.pdf.table_merged import PdfMergedTableDetector
from source_understanding.schemas.logical_unit import LogicalUnitType


def pdf_bytes(builder) -> bytes:
    document = pymupdf.open()
    try:
        builder(document)
        return document.tobytes()
    finally:
        document.close()


def draw_colspan_table(page) -> None:
    x0, y0 = 40.0, 80.0
    width, height = 100.0, 45.0
    rows, columns = 3, 3
    for x in (x0, x0 + 2 * width, x0 + 3 * width):
        page.draw_line((x, y0), (x, y0 + rows * height))
    page.draw_line((x0 + width, y0 + height), (x0 + width, y0 + rows * height))
    for row in range(rows + 1):
        y = y0 + row * height
        page.draw_line((x0, y), (x0 + columns * width, y))
    values = (
        ((0, "Merged header"), (2, "H3")),
        ((0, "A1"), (1, "B1"), (2, "C1")),
        ((0, "A2"), (1, "B2"), (2, "C2")),
    )
    for row, cells in enumerate(values):
        for column, text in cells:
            page.insert_text(
                (x0 + column * width + 8.0, y0 + row * height + 27.0),
                text,
                fontsize=10,
            )


def draw_rowspan_table(page) -> None:
    x0, y0 = 40.0, 80.0
    width, height = 100.0, 45.0
    rows, columns = 3, 3
    for column in range(columns + 1):
        x = x0 + column * width
        page.draw_line((x, y0), (x, y0 + rows * height))
    page.draw_line((x0 + width, y0 + height), (x0 + columns * width, y0 + height))
    for y in (y0, y0 + 2 * height, y0 + 3 * height):
        page.draw_line((x0, y), (x0 + columns * width, y))
    values = (
        ((0, "Merged side"), (1, "B0"), (2, "C0")),
        ((1, "B1"), (2, "C1")),
        ((0, "A2"), (1, "B2"), (2, "C2")),
    )
    for row, cells in enumerate(values):
        for column, text in cells:
            page.insert_text(
                (x0 + column * width + 8.0, y0 + row * height + 27.0),
                text,
                fontsize=10,
            )


def make_block(native_order: int, text: str, bbox: tuple[float, float, float, float]) -> PdfBlockObservation:
    span = PdfSpanObservation(
        text=text,
        bbox=bbox,
        displayed_bbox=bbox,
        font_name=None,
        font_size=10.0,
        flags=0,
        color=None,
        alpha=None,
        origin=None,
        native_order=native_order,
        line_index=0,
        span_index=0,
    )
    line = PdfLineObservation(
        bbox=bbox,
        displayed_bbox=bbox,
        writing_mode=0,
        direction=(1.0, 0.0),
        spans=(span,),
        native_order=native_order,
    )
    return PdfBlockObservation(
        page_number=1,
        native_block_number=native_order,
        native_order=native_order,
        bbox=bbox,
        displayed_bbox=bbox,
        lines=(line,),
    )


class PdfM24MergedTableTests(unittest.TestCase):
    def test_detector_accepts_exact_rectangular_colspan_without_duplicate_anchor(self) -> None:
        class Row:
            def __init__(self, cells) -> None:
                self.cells = cells

        class Table:
            bbox = (0.0, 0.0, 300.0, 150.0)
            row_count = 3
            col_count = 3
            rows = (
                Row(((0.0, 0.0, 200.0, 50.0), None, (200.0, 0.0, 300.0, 50.0))),
                Row(((0.0, 50.0, 100.0, 100.0), (100.0, 50.0, 200.0, 100.0), (200.0, 50.0, 300.0, 100.0))),
                Row(((0.0, 100.0, 100.0, 150.0), (100.0, 100.0, 200.0, 150.0), (200.0, 100.0, 300.0, 150.0))),
            )

        class Finder:
            tables = (Table(),)

        class FakePage:
            rect = pymupdf.Rect(0.0, 0.0, 320.0, 180.0)
            rotation = 0
            rotation_matrix = pymupdf.Matrix(1, 1)

            def get_drawings(self):
                return [
                    {
                        "items": [
                            ("re", pymupdf.Rect(0, 0, 300, 150)),
                            ("l", pymupdf.Point(100, 50), pymupdf.Point(100, 150)),
                            ("l", pymupdf.Point(0, 50), pymupdf.Point(300, 50)),
                        ]
                    }
                ]

            def find_tables(self, **_kwargs):
                return Finder()

        blocks = (
            make_block(0, "Merged", (10.0, 10.0, 80.0, 25.0)),
            make_block(1, "H3", (210.0, 10.0, 240.0, 25.0)),
            make_block(2, "A1", (10.0, 60.0, 30.0, 75.0)),
            make_block(3, "B1", (110.0, 60.0, 130.0, 75.0)),
            make_block(4, "C1", (210.0, 60.0, 230.0, 75.0)),
            make_block(5, "A2", (10.0, 110.0, 30.0, 125.0)),
            make_block(6, "B2", (110.0, 110.0, 130.0, 125.0)),
            make_block(7, "C2", (210.0, 110.0, 230.0, 125.0)),
        )
        result = PdfMergedTableDetector().detect(
            FakePage(),
            blocks,
            candidate_indexes=frozenset({0}),
        )
        self.assertEqual(len(result.tables), 1)
        table = result.tables[0]
        self.assertEqual((table.row_count, table.column_count), (3, 3))
        self.assertEqual([cell.cell_index for cell in table.rows[0].cells], [0, 2])
        self.assertEqual([cell.text for cell in table.rows[0].cells], ["Merged", "H3"])
        self.assertEqual(len([cell for row in table.rows for cell in row.cells]), 8)

    def test_unexplained_missing_slot_is_rejected_fail_closed(self) -> None:
        class Row:
            def __init__(self, cells) -> None:
                self.cells = cells

        class Table:
            bbox = (0.0, 0.0, 300.0, 150.0)
            row_count = 3
            col_count = 3
            rows = (
                Row(((0.0, 0.0, 100.0, 50.0), None, (200.0, 0.0, 300.0, 50.0))),
                Row(((0.0, 50.0, 100.0, 100.0), (100.0, 50.0, 200.0, 100.0), (200.0, 50.0, 300.0, 100.0))),
                Row(((0.0, 100.0, 100.0, 150.0), (100.0, 100.0, 200.0, 150.0), (200.0, 100.0, 300.0, 150.0))),
            )

        class Finder:
            tables = (Table(),)

        class FakePage:
            rect = pymupdf.Rect(0.0, 0.0, 320.0, 180.0)
            rotation = 0
            rotation_matrix = pymupdf.Matrix(1, 1)

            def get_drawings(self):
                return [
                    {
                        "items": [
                            ("re", pymupdf.Rect(0, 0, 300, 150)),
                            ("l", pymupdf.Point(100, 50), pymupdf.Point(100, 150)),
                            ("l", pymupdf.Point(0, 50), pymupdf.Point(300, 50)),
                        ]
                    }
                ]

            def find_tables(self, **_kwargs):
                return Finder()

        result = PdfMergedTableDetector().detect(
            FakePage(),
            (make_block(0, "A", (10.0, 10.0, 20.0, 20.0)),),
            candidate_indexes=frozenset({0}),
        )
        self.assertEqual(result.tables, ())
        self.assertEqual(len(result.rejected), 1)
        self.assertIn(
            result.rejected[0].reason,
            {"missing_slots_not_explained_by_span", "merged_grid_hole"},
        )

    def test_colspan_pdf_emits_span_metadata_once_and_preserves_source(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=400, height=300)
            draw_colspan_table(page)

        payload = pdf_bytes(build)
        result = PdfAdapter().adapt(payload)
        tables = [item for item in result.raw_elements if item.type_hint == "TABLE"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].attributes["column_count"], 3)
        self.assertTrue(tables[0].attributes["has_merged_cells"])
        merged = [
            item
            for item in result.raw_elements
            if item.type_hint == "TABLE_CELL" and item.attributes.get("column_span") == 2
        ]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "Merged header")
        self.assertEqual(merged[0].attributes["row_span"], 1)
        self.assertEqual(
            merged[0].attributes["logical_slots"],
            [
                {"row_index": 0, "cell_index": 0},
                {"row_index": 0, "cell_index": 1},
            ],
        )
        self.assertEqual(
            sum(item.text == "Merged header" for item in result.raw_elements),
            1,
        )

    def test_rowspan_pdf_emits_row_span_and_consolidates_to_one_table_block(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=400, height=300)
            draw_rowspan_table(page)

        payload = pdf_bytes(build)
        result = PdfAdapter().adapt(payload)
        merged = [
            item
            for item in result.raw_elements
            if item.type_hint == "TABLE_CELL" and item.attributes.get("row_span") == 2
        ]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "Merged side")
        self.assertEqual(merged[0].attributes["column_span"], 1)

        understood = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=PdfAdapter(),
            document_id="pdf-m24-rowspan",
        )
        table_units = [
            unit
            for unit in understood.understanding.grouping_result.logical_units
            if unit.type == LogicalUnitType.TABLE_BLOCK
        ]
        self.assertEqual(len(table_units), 1)
        self.assertTrue(understood.preservation_report.fully_preserved)

    def test_policy_can_disable_merged_support_without_losing_native_text(self) -> None:
        from source_understanding.adapters.pdf import PdfAdapterPolicy

        def build(document) -> None:
            page = document.new_page(width=400, height=300)
            draw_colspan_table(page)

        payload = pdf_bytes(build)
        result = PdfAdapter(PdfAdapterPolicy(enable_merged_table_structure=False)).adapt(payload)
        self.assertNotIn("TABLE", {item.type_hint for item in result.raw_elements})
        joined = " ".join(item.text or "" for item in result.raw_elements)
        self.assertIn("Merged header", joined)
        self.assertIn("C2", joined)


if __name__ == "__main__":
    unittest.main()
