from __future__ import annotations

import unittest

from source_understanding.adapters.pdf.table_grid_normalize import (
    PdfSegmentedGridNormalizationError,
    PdfSegmentedGridNormalizer,
)
from source_understanding.adapters.pdf.tables import PdfTablePolicy


class _Row:
    def __init__(self, cells) -> None:
        self.cells = tuple(cells)


class _Candidate:
    def __init__(self, x_boundaries, y_boundaries) -> None:
        self.bbox = (
            float(x_boundaries[0]),
            float(y_boundaries[0]),
            float(x_boundaries[-1]),
            float(y_boundaries[-1]),
        )
        self.row_count = len(y_boundaries) - 1
        self.col_count = len(x_boundaries) - 1
        self.rows = tuple(
            _Row(
                (
                    float(x_boundaries[column]),
                    float(y_boundaries[row]),
                    float(x_boundaries[column + 1]),
                    float(y_boundaries[row + 1]),
                )
                for column in range(self.col_count)
            )
            for row in range(self.row_count)
        )


def _path(lines):
    xs = [point[0] for line in lines for point in line]
    ys = [point[1] for line in lines for point in line]
    return {
        "rect": (min(xs), min(ys), max(xs), max(ys)),
        "items": [("l", start, end) for start, end in lines],
    }


def _full_grid(x_boundaries, y_boundaries):
    x0, x1 = x_boundaries[0], x_boundaries[-1]
    y0, y1 = y_boundaries[0], y_boundaries[-1]
    lines = [((x0, y), (x1, y)) for y in y_boundaries]
    lines.extend(((x, y0), (x, y1)) for x in x_boundaries)
    return (_path(lines),)


class PdfM25GridNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = PdfSegmentedGridNormalizer(PdfTablePolicy())

    def test_partial_header_rule_does_not_become_logical_row_boundary(self) -> None:
        x = (0.0, 30.0, 60.0, 90.0)
        raw_y = (0.0, 10.0, 20.0, 30.0, 40.0, 50.0)
        candidate = _Candidate(x, raw_y)
        lines = [((0.0, y), (90.0, y)) for y in (0.0, 20.0, 30.0, 40.0, 50.0)]
        lines.append(((0.0, 10.0), (30.0, 10.0)))
        lines.extend(((value, 0.0), (value, 50.0)) for value in x)

        normalized = self.normalizer.normalize(candidate, (_path(lines),))

        self.assertEqual((normalized.row_count, normalized.col_count), (4, 3))
        self.assertEqual(normalized.bbox, (0.0, 0.0, 90.0, 50.0))
        self.assertEqual(normalized.rows[0].cells[0], (0.0, 0.0, 30.0, 20.0))
        self.assertFalse(normalized.has_merged_slots)

    def test_weak_gutters_and_caption_area_are_trimmed_from_stable_grid(self) -> None:
        raw_x = (0.0, 10.0, 40.0, 70.0, 100.0, 110.0)
        raw_y = (0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0)
        candidate = _Candidate(raw_x, raw_y)
        lines = []
        for y in (10.0, 20.0, 30.0, 40.0, 50.0, 60.0):
            lines.append(((10.0, y), (100.0, y)))
        for x in (10.0, 40.0, 70.0, 100.0):
            lines.append(((x, 10.0), (x, 60.0)))
        lines.extend(
            [
                ((0.0, 0.0), (0.0, 5.0)),
                ((110.0, 55.0), (110.0, 60.0)),
                ((0.0, 0.0), (110.0, 0.0)),
            ]
        )

        normalized = self.normalizer.normalize(candidate, (_path(lines),))

        self.assertEqual((normalized.row_count, normalized.col_count), (5, 3))
        self.assertEqual(normalized.bbox, (10.0, 10.0, 100.0, 60.0))

    def test_missing_local_separator_becomes_rectangular_colspan(self) -> None:
        x = (0.0, 10.0, 20.0, 30.0)
        y = (0.0, 10.0, 20.0, 30.0, 40.0)
        candidate = _Candidate(x, y)
        lines = [((0.0, value), (30.0, value)) for value in y]
        lines.extend(
            [
                ((0.0, 0.0), (0.0, 40.0)),
                ((10.0, 10.0), (10.0, 40.0)),
                ((20.0, 0.0), (20.0, 40.0)),
                ((30.0, 0.0), (30.0, 40.0)),
            ]
        )

        normalized = self.normalizer.normalize(candidate, (_path(lines),))

        self.assertEqual((normalized.row_count, normalized.col_count), (4, 3))
        self.assertTrue(normalized.has_merged_slots)
        self.assertEqual(normalized.rows[0].cells[0], (0.0, 0.0, 20.0, 10.0))
        self.assertIsNone(normalized.rows[0].cells[1])
        self.assertIsNotNone(normalized.rows[1].cells[1])

    def test_multiple_stable_vertical_grid_cores_fail_closed(self) -> None:
        x = (0.0, 30.0, 60.0, 90.0)
        y = (0.0, 10.0, 20.0, 25.0, 35.0, 45.0)
        candidate = _Candidate(x, y)
        lines = [((0.0, value), (90.0, value)) for value in y]
        for value in x:
            lines.extend(
                [
                    ((value, 0.0), (value, 20.0)),
                    ((value, 25.0), (value, 45.0)),
                ]
            )

        with self.assertRaises(PdfSegmentedGridNormalizationError) as raised:
            self.normalizer.normalize(candidate, (_path(lines),))

        self.assertEqual(
            raised.exception.reason,
            "segmented_multiple_stable_vertical_grid_cores",
        )


if __name__ == "__main__":
    unittest.main()
