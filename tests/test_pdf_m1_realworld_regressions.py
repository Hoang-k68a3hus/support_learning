from __future__ import annotations

import unittest

import pymupdf

from source_understanding.adapters import PdfAdapter
from source_understanding.adapters.pdf.models import (
    PdfBlockObservation,
    PdfLineObservation,
    PdfSpanObservation,
)
from source_understanding.adapters.pdf.order_v3 import PdfReadingOrderResolverV3


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


class PdfM1RealWorldRegressionTests(unittest.TestCase):
    def test_later_opaque_rectangle_excludes_fully_occluded_native_text(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=300, height=300)
            page.insert_text((40, 50), "prepress hidden text", fontsize=12)
            page.draw_rect(
                pymupdf.Rect(25, 25, 180, 70),
                color=None,
                fill=(1.0, 1.0, 1.0),
                overlay=True,
            )
            page.insert_text((40, 100), "visible text", fontsize=12)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertEqual([item.text for item in result.raw_elements], ["visible text"])

        diagnostics = [
            item
            for item in result.diagnostics
            if item.code == "PDF_OCCLUDED_TEXT_EXCLUDED_M1"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertFalse(diagnostics[0].affects_structural_completeness)
        self.assertEqual(diagnostics[0].metadata["occluded_block_count"], 1)

        page_metadata = result.metadata.attributes["pdf"]["pages"][0]
        self.assertEqual(page_metadata["native_text_block_count"], 2)
        self.assertEqual(page_metadata["visible_native_text_block_count"], 1)
        self.assertEqual(page_metadata["occluded_native_text_block_count"], 1)

    def test_opaque_background_painted_before_text_does_not_hide_text(self) -> None:
        def build(document) -> None:
            page = document.new_page(width=300, height=300)
            page.draw_rect(
                pymupdf.Rect(25, 25, 180, 70),
                color=None,
                fill=(1.0, 1.0, 1.0),
                overlay=True,
            )
            page.insert_text((40, 50), "visible over background", fontsize=12)

        result = PdfAdapter().adapt(pdf_bytes(build))
        self.assertEqual(
            [item.text for item in result.raw_elements],
            ["visible over background"],
        )
        self.assertNotIn(
            "PDF_OCCLUDED_TEXT_EXCLUDED_M1",
            {item.code for item in result.diagnostics},
        )

    def test_math_equation_lanes_do_not_create_false_prose_columns(self) -> None:
        source_order = (
            pdf_block(0, (40.0, 70.0, 560.0, 120.0), "body paragraph"),
            pdf_block(1, (175.0, 150.0, 290.0, 175.0), "equation fragment A"),
            pdf_block(2, (500.0, 150.0, 550.0, 175.0), "(7.16)"),
            pdf_block(3, (40.0, 190.0, 125.0, 210.0), "see (6.17), where"),
            pdf_block(4, (160.0, 225.0, 305.0, 250.0), "equation fragment B"),
            pdf_block(5, (500.0, 225.0, 550.0, 250.0), "(7.17)"),
            pdf_block(6, (40.0, 270.0, 65.0, 290.0), "and"),
            pdf_block(7, (150.0, 315.0, 550.0, 340.0), "equation (7.18)"),
        )

        resolver = PdfReadingOrderResolverV3()
        self.assertEqual(
            resolver.resolve(source_order, page_width=600.0),
            source_order,
        )

    def test_balanced_repeated_prose_columns_still_reorder(self) -> None:
        source_order = (
            pdf_block(0, (350.0, 100.0, 520.0, 120.0), "R1"),
            pdf_block(1, (60.0, 200.0, 230.0, 220.0), "L2"),
            pdf_block(2, (60.0, 100.0, 230.0, 120.0), "L1"),
            pdf_block(3, (350.0, 200.0, 520.0, 220.0), "R2"),
        )

        resolved = PdfReadingOrderResolverV3().resolve(
            source_order,
            page_width=600.0,
        )
        self.assertEqual(
            [item.native_order for item in resolved],
            [2, 1, 0, 3],
        )


if __name__ == "__main__":
    unittest.main()
