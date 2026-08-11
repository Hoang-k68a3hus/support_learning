from __future__ import annotations

import unittest

import pymupdf

from source_understanding.adapters import AdapterError, PdfAdapter, SourceAdapterRunner
from source_understanding.adapters.pdf.models import (
    PdfBlockObservation,
    PdfLineObservation,
    PdfSpanObservation,
)
from source_understanding.adapters.pdf.order import PdfReadingOrderResolver
from source_understanding.schemas.context import StructureSource


def pdf_bytes(builder) -> bytes:
    document = pymupdf.open()
    try:
        builder(document)
        return document.tobytes()
    finally:
        document.close()


def pdf_block(
    native_order: int,
    bbox: tuple[float, float, float, float],
    text: str,
) -> PdfBlockObservation:
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


class PdfAdapterM1Tests(unittest.TestCase):
    def test_native_pdf_preserves_metadata_bbox_style_span_and_provenance(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=600, height=800)
            page.insert_text((72, 100), "Native PDF text", fontsize=14, fontname="helv")
            document.set_metadata({"title": "PDF M1", "author": "Ada"})

        payload = pdf_bytes(build)
        result = PdfAdapter().adapt(payload, source_name="native.pdf")

        self.assertEqual(result.media_type, "application/pdf")
        self.assertEqual(result.metadata.title, "PDF M1")
        self.assertEqual(result.metadata.authors, ("Ada",))
        self.assertEqual(result.metadata.source_name, "native.pdf")
        self.assertEqual(len(result.raw_elements), 1)

        element = result.raw_elements[0]
        self.assertEqual(element.text, "Native PDF text")
        self.assertEqual(element.type_hint, "PARAGRAPH")
        self.assertEqual(element.provenance.source, StructureSource.DERIVED)
        self.assertEqual(element.location.source, StructureSource.DERIVED)
        self.assertEqual(element.location.page, 1)
        self.assertIsNotNone(element.location.bbox)
        bbox = element.location.bbox
        assert bbox is not None
        self.assertGreaterEqual(bbox.x0, 0.0)
        self.assertGreaterEqual(bbox.y0, 0.0)
        self.assertLessEqual(bbox.x1, 1.0)
        self.assertLessEqual(bbox.y1, 1.0)
        self.assertIsNotNone(element.style)
        assert element.style is not None
        self.assertAlmostEqual(element.style.font_size or 0.0, 14.0, places=3)
        self.assertEqual(element.attributes["pdf_reading_order"], 0)
        self.assertEqual(element.attributes["pdf_native_order"], 0)
        self.assertEqual(element.attributes["pdf_span_count"], 1)
        spans = element.attributes["pdf_spans"]
        self.assertIsInstance(spans, list)
        assert isinstance(spans, list)
        self.assertEqual(spans[0]["start_char"], 0)
        self.assertEqual(spans[0]["end_char"], len("Native PDF text"))

        pdf_metadata = result.metadata.attributes["pdf"]
        self.assertEqual(pdf_metadata["page_count"], 1)
        self.assertEqual(pdf_metadata["pages_with_native_text"], 1)
        self.assertEqual(pdf_metadata["pages"][0]["width_points"], 600.0)
        self.assertEqual(pdf_metadata["pages"][0]["height_points"], 800.0)

    def test_reading_order_is_geometry_first_not_native_stream_order(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=600, height=800)
            # A short centered title is not wide enough to be a naive full-width block.
            page.insert_text((260, 50), "TITLE", fontsize=12)
            # Deliberately write the two-column content stream in a scrambled order.
            page.insert_text((350, 100), "R1", fontsize=12)
            page.insert_text((70, 200), "L2", fontsize=12)
            page.insert_text((70, 100), "L1", fontsize=12)
            page.insert_text((350, 200), "R2", fontsize=12)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertEqual(
            [item.text for item in result.raw_elements],
            ["TITLE", "L1", "L2", "R1", "R2"],
        )
        self.assertEqual(
            [item.attributes["pdf_native_order"] for item in result.raw_elements],
            [0, 3, 2, 1, 4],
        )
        self.assertEqual(
            [item.attributes["pdf_reading_order"] for item in result.raw_elements],
            [0, 1, 2, 3, 4],
        )

    def test_ambiguous_formula_fragments_preserve_native_order(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=600, height=800)
            page.insert_text((40, 80), "Intro", fontsize=12)
            # A display equation / BNF production can be split into blocks whose
            # top coordinates do not reflect logical sequence. There is no
            # defensible page-column evidence here, so native order must win.
            page.insert_text((75, 220), "(7)", fontsize=12)
            page.insert_text((180, 195), "<TLINK eventInstanceID=ei0", fontsize=12)
            page.insert_text((180, 220), "relatedToEventInstance=ei", fontsize=12)
            page.insert_text((340, 210), "=> sigma", fontsize=12)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertEqual(
            [item.text for item in result.raw_elements],
            [
                "Intro",
                "(7)",
                "<TLINK eventInstanceID=ei0",
                "relatedToEventInstance=ei",
                "=> sigma",
            ],
        )
        self.assertEqual(
            [item.attributes["pdf_native_order"] for item in result.raw_elements],
            [0, 1, 2, 3, 4],
        )

    def test_aligned_grid_layout_preserves_native_row_major_order(self) -> None:
        blocks: list[PdfBlockObservation] = []
        native_order = 0
        for y0 in (100.0, 150.0, 200.0):
            for x0 in (40.0, 180.0, 320.0, 460.0):
                blocks.append(
                    pdf_block(
                        native_order,
                        (x0, y0, x0 + 80.0, y0 + 20.0),
                        f"cell-{native_order}",
                    )
                )
                native_order += 1

        resolver = PdfReadingOrderResolver()
        source_order = tuple(blocks)
        self.assertTrue(
            resolver.looks_aligned_layout(source_order, page_width=600.0)
        )
        self.assertEqual(
            resolver.resolve(source_order, page_width=600.0),
            source_order,
        )

    def test_overlapping_wide_formula_is_not_treated_as_vertical_separator(self) -> None:
        source_order = (
            pdf_block(0, (40.0, 100.0, 180.0, 120.0), "intro"),
            pdf_block(1, (90.0, 300.0, 330.0, 330.0), "lead-fragment"),
            pdf_block(2, (40.0, 315.0, 560.0, 350.0), "wide-formula-fragment"),
        )

        resolver = PdfReadingOrderResolver()
        self.assertFalse(
            resolver.looks_aligned_layout(source_order, page_width=600.0)
        )
        self.assertEqual(
            resolver.resolve(source_order, page_width=600.0),
            source_order,
        )

    def test_suspect_native_font_mapping_is_diagnostic_not_silently_cleaned(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=300, height=300)
            page.insert_text((50, 80), "A\x1bB", fontsize=12)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertEqual(len(result.raw_elements), 1)
        self.assertEqual(result.raw_elements[0].text, "A\x1bB")
        diagnostics = [
            item
            for item in result.diagnostics
            if item.code == "PDF_NATIVE_TEXT_MAPPING_SUSPECT"
        ]
        self.assertEqual(len(diagnostics), 1)
        diagnostic = diagnostics[0]
        self.assertTrue(diagnostic.affects_structural_completeness)
        self.assertEqual(diagnostic.part, "page:1")
        self.assertEqual(diagnostic.metadata["affected_block_count"], 1)
        self.assertEqual(diagnostic.metadata["codepoint_counts"], {"U+001B": 1})

    def test_rotated_page_bbox_is_normalized_in_displayed_page_view(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=300, height=500)
            page.insert_text((50, 100), "Rotated", fontsize=12)
            page.set_rotation(90)

        result = PdfAdapter().adapt(pdf_bytes(build))
        page_metadata = result.metadata.attributes["pdf"]["pages"][0]
        self.assertEqual(page_metadata["rotation_degrees"], 90)
        self.assertEqual(page_metadata["width_points"], 500.0)
        self.assertEqual(page_metadata["height_points"], 300.0)
        bbox = result.raw_elements[0].location.bbox
        assert bbox is not None
        self.assertTrue(0.0 <= bbox.x0 <= bbox.x1 <= 1.0)
        self.assertTrue(0.0 <= bbox.y0 <= bbox.y1 <= 1.0)

    def test_image_only_page_is_not_silently_claimed_as_parsed_text(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=200, height=200)
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
            pixmap.clear_with(255)
            page.insert_image(pymupdf.Rect(20, 20, 80, 80), pixmap=pixmap)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertEqual(result.raw_elements, ())
        codes = {item.code for item in result.diagnostics}
        self.assertIn("PDF_PAGE_NO_NATIVE_TEXT", codes)
        self.assertIn("PDF_IMAGE_CONTENT_NOT_EXTRACTED_M1", codes)
        self.assertTrue(
            all(
                item.affects_structural_completeness
                for item in result.diagnostics
                if item.code in {
                    "PDF_PAGE_NO_NATIVE_TEXT",
                    "PDF_IMAGE_CONTENT_NOT_EXTRACTED_M1",
                }
            )
        )

    def test_non_pdf_and_password_required_pdf_fail_closed(self) -> None:
        with self.assertRaisesRegex(AdapterError, "PDF header"):
            PdfAdapter().adapt(b"not a pdf")

        document = pymupdf.open()
        try:
            page = document.new_page()
            page.insert_text((50, 50), "secret")
            encrypted = document.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw="user",
                owner_pw="owner",
            )
        finally:
            document.close()
        with self.assertRaisesRegex(AdapterError, "non-empty password"):
            PdfAdapter().adapt(encrypted)

    def test_same_pdf_same_policy_is_deterministic_and_runner_preserves_locations(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=400, height=400)
            page.insert_text((40, 80), "Stable source", fontsize=11)

        payload = pdf_bytes(build)
        adapter = PdfAdapter()
        first = adapter.adapt(payload)
        second = adapter.adapt(payload)
        self.assertEqual(first, second)

        understood = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=adapter,
            document_id="pdf-m1-stable",
        )
        self.assertTrue(understood.preservation_report.fully_preserved)
        self.assertEqual(len(understood.understanding.structural_document.elements), 1)
        canonical = understood.understanding.structural_document.elements[0]
        self.assertEqual(canonical.location, first.raw_elements[0].location)
        self.assertEqual(canonical.provenance.source, StructureSource.DERIVED)


if __name__ == "__main__":
    unittest.main()
