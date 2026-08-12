from __future__ import annotations

import unittest

import pymupdf

from source_understanding.adapters import SourceAdapterRunner
from source_understanding.adapters.pdf.adapter_m23 import PdfAdapter, PdfAdapterPolicy
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import ElementType
from source_understanding.schemas.logical_unit import LogicalUnitType


def pdf_bytes(builder) -> bytes:
    document = pymupdf.open()
    try:
        builder(document)
        return document.tobytes()
    finally:
        document.close()


def draw_text_grid(
    page,
    values: tuple[tuple[str, ...], ...],
    *,
    x0: float = 48.0,
    y0: float = 80.0,
    column_step: float = 125.0,
    row_step: float = 30.0,
) -> None:
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            page.insert_text(
                (
                    x0 + column_index * column_step,
                    y0 + row_index * row_step,
                ),
                value,
                fontsize=10,
            )


class PdfM23TextAlignedTableTests(unittest.TestCase):
    def test_borderless_three_column_table_is_grounded_without_paragraph_duplication(self) -> None:
        values = (
            ("Name", "Score", "Grade"),
            ("Ada", "10", "A"),
            ("Bob", "9", "B"),
            ("Cara", "8", "B"),
        )

        def build(document) -> None:
            page = document.new_page(width=460, height=300)
            draw_text_grid(page, values)

        payload = pdf_bytes(build)
        result = PdfAdapter().adapt(payload)
        tables = [item for item in result.raw_elements if item.type_hint == "TABLE"]
        cells = [item for item in result.raw_elements if item.type_hint == "TABLE_CELL"]
        paragraphs = [item for item in result.raw_elements if item.type_hint == "PARAGRAPH"]

        self.assertEqual(len(tables), 1)
        self.assertEqual((tables[0].attributes["row_count"], tables[0].attributes["column_count"]), (4, 3))
        self.assertEqual(
            [item.text for item in cells],
            [value for row in values for value in row],
        )
        self.assertEqual(paragraphs, [])
        self.assertEqual(tables[0].attributes["pdf_table_detection_strategy"], "text_aligned")
        self.assertEqual(tables[0].attributes["integrity_evidence"], "pdf_text_alignment")
        self.assertEqual(tables[0].attributes["pdf_table_structure_version"], "multi-strategy-v2")
        self.assertEqual(tables[0].provenance.source, StructureSource.DERIVED)
        self.assertTrue(all(item.attributes["pdf_source_spans"] for item in cells))
        self.assertEqual(
            result.metadata.attributes["pdf"]["ocr_table_extraction"],
            "deferred_optional_extension",
        )
        self.assertNotIn("PDF_PAGE_NO_NATIVE_TEXT", {item.code for item in result.diagnostics})

        understood = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=PdfAdapter(),
            document_id="pdf-m23-borderless",
        )
        canonical_types = {
            item.type for item in understood.understanding.structural_document.elements
        }
        self.assertIn(ElementType.TABLE, canonical_types)
        table_units = [
            unit
            for unit in understood.understanding.grouping_result.logical_units
            if unit.type == LogicalUnitType.TABLE_BLOCK
        ]
        self.assertEqual(len(table_units), 1)
        self.assertTrue(understood.preservation_report.fully_preserved)

    def test_equation_array_with_operator_lane_stays_unstructured(self) -> None:
        values = (
            ("x1", "=", "10"),
            ("x2", "=", "20"),
            ("x3", "=", "30"),
            ("x4", "=", "40"),
        )

        def build(document) -> None:
            page = document.new_page(width=440, height=300)
            draw_text_grid(page, values)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertNotIn("TABLE", {item.type_hint for item in result.raw_elements})
        rejected = [
            item
            for item in result.diagnostics
            if item.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(
            rejected[0].metadata["reason_counts"],
            {"text_aligned_operator_lane": 1},
        )
        self.assertTrue(rejected[0].affects_structural_completeness)

    def test_key_value_form_with_colon_lane_stays_unstructured(self) -> None:
        values = (
            ("Name", ":", "Ada"),
            ("Course", ":", "Math"),
            ("Year", ":", "2026"),
        )

        def build(document) -> None:
            page = document.new_page(width=440, height=260)
            draw_text_grid(page, values)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertNotIn("TABLE", {item.type_hint for item in result.raw_elements})
        rejected = next(
            item
            for item in result.diagnostics
            if item.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2"
        )
        self.assertEqual(
            rejected.metadata["reason_counts"],
            {"text_aligned_operator_lane": 1},
        )

    def test_dense_parallel_prose_rows_do_not_become_table(self) -> None:
        values = (
            ("red", "green", "blue"),
            ("one", "two", "three"),
            ("cat", "dog", "bird"),
            ("sun", "moon", "star"),
        )

        def build(document) -> None:
            page = document.new_page(width=520, height=220)
            draw_text_grid(
                page,
                values,
                column_step=155.0,
                row_step=14.0,
            )

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertNotIn("TABLE", {item.type_hint for item in result.raw_elements})
        rejected = next(
            item
            for item in result.diagnostics
            if item.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2"
        )
        self.assertIn("text_aligned_dense_row_spacing", rejected.metadata["reason_counts"])

    def test_text_aligned_fallback_can_be_disabled_without_changing_source_text(self) -> None:
        values = (
            ("A", "B", "C"),
            ("1", "2", "3"),
            ("4", "5", "6"),
        )

        def build(document) -> None:
            page = document.new_page(width=440, height=260)
            draw_text_grid(page, values)

        payload = pdf_bytes(build)
        result = PdfAdapter(
            PdfAdapterPolicy(enable_text_aligned_table_structure=False)
        ).adapt(payload)
        self.assertNotIn("TABLE", {item.type_hint for item in result.raw_elements})
        preserved = "".join(item.text or "" for item in result.raw_elements).replace("\n", "")
        self.assertEqual(preserved, "ABC123456")


if __name__ == "__main__":
    unittest.main()
