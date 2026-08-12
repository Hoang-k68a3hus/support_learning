from __future__ import annotations

import unittest

import pymupdf

from source_understanding.adapters.pdf.models import (
    PdfBlockObservation,
    PdfLineObservation,
    PdfSpanObservation,
)
from source_understanding.adapters.pdf.table_regions import (
    PDF_SEGMENTED_LINES_TABLE_STRATEGY,
    PdfSegmentedTableDetector,
)


def make_block(
    native_order: int,
    text: str,
    bbox: tuple[float, float, float, float],
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


class _Row:
    def __init__(self, cells) -> None:
        self.cells = cells


class _Table:
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = bbox
        width = (x1 - x0) / 3.0
        height = (y1 - y0) / 3.0
        self.bbox = bbox
        self.row_count = 3
        self.col_count = 3
        self.rows = tuple(
            _Row(
                tuple(
                    (
                        x0 + column * width,
                        y0 + row * height,
                        x0 + (column + 1) * width,
                        y0 + (row + 1) * height,
                    )
                    for column in range(3)
                )
            )
            for row in range(3)
        )


class _Finder:
    def __init__(self, tables) -> None:
        self.tables = tuple(tables)


class _SegmentedPage:
    rect = pymupdf.Rect(0.0, 0.0, 400.0, 400.0)
    rotation = 0
    rotation_matrix = pymupdf.Matrix(1, 1)

    first = (20.0, 20.0, 320.0, 140.0)
    second = (20.0, 220.0, 320.0, 340.0)

    def __init__(self, *, expose_second: bool = True) -> None:
        self.expose_second = expose_second
        self.calls: list[tuple[str, tuple[float, float, float, float]]] = []

    def get_drawings(self):
        output = []
        for bbox in (self.first, self.second):
            x0, y0, x1, y1 = bbox
            width = (x1 - x0) / 3.0
            height = (y1 - y0) / 3.0
            items = []
            for row in range(4):
                y = y0 + row * height
                items.append(
                    (
                        "l",
                        pymupdf.Point(x0, y),
                        pymupdf.Point(x1, y),
                    )
                )
            for column in range(4):
                x = x0 + column * width
                items.append(
                    (
                        "l",
                        pymupdf.Point(x, y0),
                        pymupdf.Point(x, y1),
                    )
                )
            output.append(
                {
                    "rect": pymupdf.Rect(bbox),
                    "items": items,
                }
            )
        return output

    def cluster_drawings(self, **_kwargs):
        return [pymupdf.Rect(self.first), pymupdf.Rect(self.second)]

    def find_tables(self, **kwargs):
        strategy = str(kwargs["strategy"])
        clip = tuple(float(item) for item in kwargs["clip"])
        self.calls.append((strategy, clip))
        if strategy == "lines_strict":
            return _Finder(())
        if clip[1] < 150.0:
            return _Finder((_Table(self.first),))
        if self.expose_second:
            return _Finder((_Table(self.second),))
        return _Finder(())


def segmented_blocks() -> tuple[PdfBlockObservation, ...]:
    blocks: list[PdfBlockObservation] = []
    native_order = 0
    for table_bbox in (_SegmentedPage.first, _SegmentedPage.second):
        x0, y0, x1, y1 = table_bbox
        width = (x1 - x0) / 3.0
        height = (y1 - y0) / 3.0
        for row in range(3):
            for column in range(3):
                bbox = (
                    x0 + column * width + 5.0,
                    y0 + row * height + 5.0,
                    x0 + column * width + 30.0,
                    y0 + row * height + 20.0,
                )
                blocks.append(
                    make_block(
                        native_order,
                        f"T{1 if y0 < 150 else 2}-{row}-{column}",
                        bbox,
                    )
                )
                native_order += 1
    return tuple(blocks)


class PdfM25MultiTableSegmentationTests(unittest.TestCase):
    def test_disconnected_regions_retry_lines_locally_and_recover_two_tables(self) -> None:
        page = _SegmentedPage()
        result = PdfSegmentedTableDetector().detect(page, segmented_blocks())

        self.assertEqual(len(result.tables), 2)
        self.assertEqual(
            [(table.row_count, table.column_count) for table in result.tables],
            [(3, 3), (3, 3)],
        )
        self.assertEqual(
            {table.detection_strategy for table in result.tables},
            {PDF_SEGMENTED_LINES_TABLE_STRATEGY},
        )
        self.assertEqual(result.tables[0].source_native_orders, tuple(range(0, 9)))
        self.assertEqual(result.tables[1].source_native_orders, tuple(range(9, 18)))
        self.assertIn(("lines_strict", _SegmentedPage.first), page.calls)
        self.assertIn(("lines", _SegmentedPage.first), page.calls)
        self.assertIn(("lines_strict", _SegmentedPage.second), page.calls)
        self.assertIn(("lines", _SegmentedPage.second), page.calls)

    def test_one_surviving_region_is_not_promoted_as_multi_table_structure(self) -> None:
        page = _SegmentedPage(expose_second=False)
        result = PdfSegmentedTableDetector().detect(page, segmented_blocks())

        self.assertEqual(result.tables, ())
        self.assertTrue(result.rejected)
        self.assertEqual(result.rejected[-1].reason, "segmented_minimum_tables_not_met")

    def test_overlapping_vector_regions_fail_closed_before_table_detection(self) -> None:
        class OverlappingPage(_SegmentedPage):
            def cluster_drawings(self, **_kwargs):
                return [
                    pymupdf.Rect(20.0, 20.0, 320.0, 180.0),
                    pymupdf.Rect(20.0, 120.0, 320.0, 340.0),
                ]

        page = OverlappingPage()
        result = PdfSegmentedTableDetector().detect(page, segmented_blocks())
        self.assertEqual(result.tables, ())
        self.assertEqual(result.rejected[0].reason, "segmented_vector_regions_overlap")
        self.assertEqual(page.calls, [])


if __name__ == "__main__":
    unittest.main()
