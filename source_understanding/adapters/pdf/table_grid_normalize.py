from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isclose
from typing import Any

from .models import PdfRect
from .tables import PdfTablePolicy


@dataclass(frozen=True, slots=True)
class PdfNormalizedTableRow:
    cells: tuple[PdfRect | None, ...]


@dataclass(frozen=True, slots=True)
class PdfNormalizedTableCandidate:
    bbox: PdfRect
    row_count: int
    col_count: int
    rows: tuple[PdfNormalizedTableRow, ...]
    has_merged_slots: bool


class PdfSegmentedGridNormalizationError(ValueError):
    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _VectorSegments:
    horizontal: tuple[tuple[float, float, float], ...]
    vertical: tuple[tuple[float, float, float], ...]


class PdfSegmentedGridNormalizer:
    """Recover a logical ruled-table grid from source vector strokes.

    PyMuPDF's permissive ``strategy="lines"`` may turn short decorative or partial
    rules into global row / column boundaries. M2.5 never trusts those inferred
    boundaries directly. Instead it keeps only boundaries supported by source vector
    strokes, trims leading / trailing material that lacks a stable vertical grid,
    and reconstructs rectangular merged cells from missing local separators.

    This is a structural inference layer, not a source fact. Any ambiguous grid is
    rejected so the adapter can preserve the original native text blocks.
    """

    def __init__(
        self,
        policy: PdfTablePolicy,
        *,
        boundary_support_ratio: float = 0.75,
        vector_alignment_tolerance_points: float = 0.75,
        active_vertical_boundary_fraction: float = 0.40,
        minimum_active_vertical_boundaries: int = 3,
    ) -> None:
        if not 0.0 < boundary_support_ratio <= 1.0:
            raise ValueError("boundary_support_ratio must be in (0, 1]")
        if vector_alignment_tolerance_points < 0.0:
            raise ValueError("vector_alignment_tolerance_points must be nonnegative")
        if not 0.0 < active_vertical_boundary_fraction <= 1.0:
            raise ValueError("active_vertical_boundary_fraction must be in (0, 1]")
        if minimum_active_vertical_boundaries < 2:
            raise ValueError("minimum_active_vertical_boundaries must be >= 2")
        self.policy = policy
        self.boundary_support_ratio = boundary_support_ratio
        self.vector_alignment_tolerance_points = vector_alignment_tolerance_points
        self.active_vertical_boundary_fraction = active_vertical_boundary_fraction
        self.minimum_active_vertical_boundaries = minimum_active_vertical_boundaries

    def normalize(
        self,
        candidate: Any,
        paths: tuple[object, ...],
    ) -> PdfNormalizedTableCandidate:
        bbox = self._rect(getattr(candidate, "bbox", None))
        if bbox is None or self._area(bbox) <= 0:
            raise PdfSegmentedGridNormalizationError("segmented_invalid_candidate_bbox")

        row_count = self._positive_int(getattr(candidate, "row_count", None))
        column_count = self._positive_int(getattr(candidate, "col_count", None))
        if row_count is None or column_count is None:
            raise PdfSegmentedGridNormalizationError(
                "segmented_invalid_candidate_shape"
            )
        raw_rows = tuple(getattr(candidate, "rows", ()) or ())
        if len(raw_rows) != row_count:
            raise PdfSegmentedGridNormalizationError(
                "segmented_candidate_row_topology_mismatch"
            )

        rects: list[PdfRect] = []
        for row in raw_rows:
            raw_cells = tuple(getattr(row, "cells", ()) or ())
            if len(raw_cells) != column_count:
                raise PdfSegmentedGridNormalizationError(
                    "segmented_candidate_column_topology_mismatch"
                )
            for raw_cell in raw_cells:
                rect = self._rect(raw_cell)
                if rect is not None and self._area(rect) > 0:
                    rects.append(rect)
        if not rects:
            raise PdfSegmentedGridNormalizationError(
                "segmented_candidate_has_no_cell_geometry"
            )

        x_boundaries = self._cluster_boundaries(
            [bbox[0], bbox[2], *(value for rect in rects for value in (rect[0], rect[2]))]
        )
        y_boundaries = self._cluster_boundaries(
            [bbox[1], bbox[3], *(value for rect in rects for value in (rect[1], rect[3]))]
        )
        if len(x_boundaries) < self.policy.minimum_columns + 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_insufficient_raw_column_boundaries"
            )
        if len(y_boundaries) < self.policy.minimum_rows + 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_insufficient_raw_row_boundaries"
            )

        segments = self._vector_segments(paths)
        if not segments.horizontal or not segments.vertical:
            raise PdfSegmentedGridNormalizationError(
                "segmented_insufficient_source_vector_segments"
            )

        preliminary_x = self._supported_vertical_boundaries(
            x_boundaries,
            segments.vertical,
            y0=bbox[1],
            y1=bbox[3],
        )
        if len(preliminary_x) < self.policy.minimum_columns + 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_insufficient_supported_column_boundaries"
            )

        core_y0, core_y1 = self._stable_y_core(
            y_boundaries,
            preliminary_x,
            segments.vertical,
        )
        refined_x = self._supported_vertical_boundaries(
            x_boundaries,
            segments.vertical,
            y0=core_y0,
            y1=core_y1,
        )
        if len(refined_x) < self.policy.minimum_columns + 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_insufficient_refined_column_boundaries"
            )

        refined_y0, refined_y1 = self._stable_y_core(
            y_boundaries,
            refined_x,
            segments.vertical,
        )
        core_y0 = max(core_y0, refined_y0)
        core_y1 = min(core_y1, refined_y1)
        if core_y1 <= core_y0:
            raise PdfSegmentedGridNormalizationError(
                "segmented_empty_stable_grid_core"
            )

        logical_x = self._supported_vertical_boundaries(
            x_boundaries,
            segments.vertical,
            y0=core_y0,
            y1=core_y1,
        )
        if len(logical_x) < self.policy.minimum_columns + 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_logical_column_boundaries_unresolved"
            )
        x0, x1 = logical_x[0], logical_x[-1]

        logical_y = tuple(
            boundary
            for boundary in y_boundaries
            if core_y0 - self.policy.topology_tolerance_points
            <= boundary
            <= core_y1 + self.policy.topology_tolerance_points
            and self._horizontal_support(
                segments.horizontal,
                boundary,
                x0=x0,
                x1=x1,
            )
            >= self.boundary_support_ratio
        )
        logical_y = self._deduplicate_boundaries(logical_y)
        if len(logical_y) < self.policy.minimum_rows + 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_logical_row_boundaries_unresolved"
            )
        if not isclose(logical_y[0], core_y0, abs_tol=self.policy.topology_tolerance_points):
            raise PdfSegmentedGridNormalizationError(
                "segmented_grid_core_top_boundary_unsupported"
            )
        if not isclose(logical_y[-1], core_y1, abs_tol=self.policy.topology_tolerance_points):
            raise PdfSegmentedGridNormalizationError(
                "segmented_grid_core_bottom_boundary_unsupported"
            )

        normalized_rows = len(logical_y) - 1
        normalized_columns = len(logical_x) - 1
        if (
            normalized_rows < self.policy.minimum_rows
            or normalized_columns < self.policy.minimum_columns
            or normalized_rows * normalized_columns < self.policy.minimum_cells
        ):
            raise PdfSegmentedGridNormalizationError(
                "segmented_normalized_grid_too_small"
            )

        rows, has_merged_slots = self._build_rows(
            logical_x,
            logical_y,
            segments,
        )
        return PdfNormalizedTableCandidate(
            bbox=(logical_x[0], logical_y[0], logical_x[-1], logical_y[-1]),
            row_count=normalized_rows,
            col_count=normalized_columns,
            rows=rows,
            has_merged_slots=has_merged_slots,
        )

    def _stable_y_core(
        self,
        y_boundaries: tuple[float, ...],
        x_boundaries: tuple[float, ...],
        vertical_segments: tuple[tuple[float, float, float], ...],
    ) -> tuple[float, float]:
        required = max(
            self.minimum_active_vertical_boundaries,
            ceil(len(x_boundaries) * self.active_vertical_boundary_fraction),
        )
        required = min(required, len(x_boundaries))
        active: list[bool] = []
        for top, bottom in zip(y_boundaries, y_boundaries[1:]):
            if bottom <= top:
                active.append(False)
                continue
            count = sum(
                1
                for boundary in x_boundaries
                if self._vertical_support(
                    vertical_segments,
                    boundary,
                    y0=top,
                    y1=bottom,
                )
                >= self.boundary_support_ratio
            )
            active.append(count >= required)

        runs: list[tuple[int, int]] = []
        start: int | None = None
        for index, value in enumerate(active):
            if value and start is None:
                start = index
            elif not value and start is not None:
                runs.append((start, index))
                start = None
        if start is not None:
            runs.append((start, len(active)))
        if not runs:
            raise PdfSegmentedGridNormalizationError(
                "segmented_no_stable_vertical_grid_core"
            )
        if len(runs) > 1:
            raise PdfSegmentedGridNormalizationError(
                "segmented_multiple_stable_vertical_grid_cores",
                detail=";".join(f"{start}:{end}" for start, end in runs),
            )
        start, end = runs[0]
        return y_boundaries[start], y_boundaries[end]

    def _supported_vertical_boundaries(
        self,
        boundaries: tuple[float, ...],
        segments: tuple[tuple[float, float, float], ...],
        *,
        y0: float,
        y1: float,
    ) -> tuple[float, ...]:
        return self._deduplicate_boundaries(
            tuple(
                boundary
                for boundary in boundaries
                if self._vertical_support(
                    segments,
                    boundary,
                    y0=y0,
                    y1=y1,
                )
                >= self.boundary_support_ratio
            )
        )

    def _build_rows(
        self,
        x_boundaries: tuple[float, ...],
        y_boundaries: tuple[float, ...],
        segments: _VectorSegments,
    ) -> tuple[tuple[PdfNormalizedTableRow, ...], bool]:
        row_count = len(y_boundaries) - 1
        column_count = len(x_boundaries) - 1
        parent = list(range(row_count * column_count))

        def slot(row: int, column: int) -> int:
            return row * column_count + column

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for row in range(row_count):
            top, bottom = y_boundaries[row], y_boundaries[row + 1]
            for boundary_index in range(1, len(x_boundaries) - 1):
                boundary = x_boundaries[boundary_index]
                if self._vertical_support(
                    segments.vertical,
                    boundary,
                    y0=top,
                    y1=bottom,
                ) < self.boundary_support_ratio:
                    union(slot(row, boundary_index - 1), slot(row, boundary_index))

        for boundary_index in range(1, len(y_boundaries) - 1):
            boundary = y_boundaries[boundary_index]
            for column in range(column_count):
                left, right = x_boundaries[column], x_boundaries[column + 1]
                if self._horizontal_support(
                    segments.horizontal,
                    boundary,
                    x0=left,
                    x1=right,
                ) < self.boundary_support_ratio:
                    union(slot(boundary_index - 1, column), slot(boundary_index, column))

        components: dict[int, set[tuple[int, int]]] = {}
        for row in range(row_count):
            for column in range(column_count):
                root = find(slot(row, column))
                components.setdefault(root, set()).add((row, column))

        cell_matrix: list[list[PdfRect | None]] = [
            [None for _ in range(column_count)] for _ in range(row_count)
        ]
        has_merged_slots = False
        for members in components.values():
            rows = [row for row, _column in members]
            columns = [column for _row, column in members]
            row0, row1 = min(rows), max(rows)
            column0, column1 = min(columns), max(columns)
            expected = {
                (row, column)
                for row in range(row0, row1 + 1)
                for column in range(column0, column1 + 1)
            }
            if members != expected:
                raise PdfSegmentedGridNormalizationError(
                    "segmented_nonrectangular_merged_component"
                )
            bbox = (
                x_boundaries[column0],
                y_boundaries[row0],
                x_boundaries[column1 + 1],
                y_boundaries[row1 + 1],
            )
            cell_matrix[row0][column0] = bbox
            if len(members) > 1:
                has_merged_slots = True

        for row in range(row_count):
            for column in range(column_count):
                if cell_matrix[row][column] is not None:
                    continue
                if any(
                    row0 <= row <= row1 and column0 <= column <= column1
                    for members in components.values()
                    if len(members) > 1
                    for row0, row1, column0, column1 in [
                        (
                            min(item[0] for item in members),
                            max(item[0] for item in members),
                            min(item[1] for item in members),
                            max(item[1] for item in members),
                        )
                    ]
                ):
                    continue
                cell_matrix[row][column] = (
                    x_boundaries[column],
                    y_boundaries[row],
                    x_boundaries[column + 1],
                    y_boundaries[row + 1],
                )

        return (
            tuple(PdfNormalizedTableRow(cells=tuple(row)) for row in cell_matrix),
            has_merged_slots,
        )

    def _vector_segments(self, paths: tuple[object, ...]) -> _VectorSegments:
        horizontal: list[tuple[float, float, float]] = []
        vertical: list[tuple[float, float, float]] = []
        tolerance = self.vector_alignment_tolerance_points
        for path in paths:
            if not isinstance(path, dict):
                continue
            items = path.get("items")
            if not isinstance(items, (list, tuple)):
                continue
            for item in items:
                if not isinstance(item, (list, tuple)) or not item:
                    continue
                kind = item[0]
                if kind == "l" and len(item) >= 3:
                    start = self._point(item[1])
                    end = self._point(item[2])
                    if start is None or end is None:
                        continue
                    if abs(start[1] - end[1]) <= tolerance and abs(start[0] - end[0]) > tolerance:
                        left, right = sorted((start[0], end[0]))
                        horizontal.append(((start[1] + end[1]) / 2.0, left, right))
                    elif abs(start[0] - end[0]) <= tolerance and abs(start[1] - end[1]) > tolerance:
                        top, bottom = sorted((start[1], end[1]))
                        vertical.append(((start[0] + end[0]) / 2.0, top, bottom))
                elif kind == "re" and len(item) >= 2:
                    rect = self._rect(item[1])
                    if rect is None:
                        continue
                    x0, y0, x1, y1 = rect
                    if x1 - x0 > tolerance:
                        horizontal.extend(((y0, x0, x1), (y1, x0, x1)))
                    if y1 - y0 > tolerance:
                        vertical.extend(((x0, y0, y1), (x1, y0, y1)))
        return _VectorSegments(tuple(horizontal), tuple(vertical))

    def _vertical_support(
        self,
        segments: tuple[tuple[float, float, float], ...],
        boundary: float,
        *,
        y0: float,
        y1: float,
    ) -> float:
        return self._support(
            segments,
            boundary,
            lower=y0,
            upper=y1,
        )

    def _horizontal_support(
        self,
        segments: tuple[tuple[float, float, float], ...],
        boundary: float,
        *,
        x0: float,
        x1: float,
    ) -> float:
        return self._support(
            segments,
            boundary,
            lower=x0,
            upper=x1,
        )

    def _support(
        self,
        segments: tuple[tuple[float, float, float], ...],
        boundary: float,
        *,
        lower: float,
        upper: float,
    ) -> float:
        denominator = upper - lower
        if denominator <= 0:
            return 0.0
        intervals: list[tuple[float, float]] = []
        tolerance = self.vector_alignment_tolerance_points
        for coordinate, start, end in segments:
            if abs(coordinate - boundary) > tolerance:
                continue
            clipped_start = max(lower, start)
            clipped_end = min(upper, end)
            if clipped_end > clipped_start:
                intervals.append((clipped_start, clipped_end))
        return min(1.0, self._union_length(intervals) / denominator)

    def _cluster_boundaries(self, values: list[float]) -> tuple[float, ...]:
        tolerance = self.policy.topology_tolerance_points
        groups: list[list[float]] = []
        for value in sorted(values):
            if not groups or abs(value - groups[-1][-1]) > tolerance:
                groups.append([value])
            else:
                groups[-1].append(value)
        return tuple(sum(group) / len(group) for group in groups)

    def _deduplicate_boundaries(
        self,
        boundaries: tuple[float, ...],
    ) -> tuple[float, ...]:
        if not boundaries:
            return ()
        output = [boundaries[0]]
        tolerance = self.policy.topology_tolerance_points
        for boundary in boundaries[1:]:
            if abs(boundary - output[-1]) <= tolerance:
                output[-1] = (output[-1] + boundary) / 2.0
            else:
                output.append(boundary)
        return tuple(output)

    @staticmethod
    def _union_length(intervals: list[tuple[float, float]]) -> float:
        if not intervals:
            return 0.0
        ordered = sorted((left, right) for left, right in intervals if right > left)
        if not ordered:
            return 0.0
        total = 0.0
        current_left, current_right = ordered[0]
        for left, right in ordered[1:]:
            if left <= current_right:
                current_right = max(current_right, right)
                continue
            total += current_right - current_left
            current_left, current_right = left, right
        total += current_right - current_left
        return total

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _area(rect: PdfRect) -> float:
        return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])

    @staticmethod
    def _rect(value: Any) -> PdfRect | None:
        if value is None:
            return None
        if all(hasattr(value, name) for name in ("x0", "y0", "x1", "y1")):
            coords = (value.x0, value.y0, value.x1, value.y1)
        elif isinstance(value, (list, tuple)) and len(value) == 4:
            coords = tuple(value)
        else:
            return None
        if any(not isinstance(item, (int, float)) for item in coords):
            return None
        x0, y0, x1, y1 = (float(item) for item in coords)
        if x1 < x0 or y1 < y0:
            return None
        return (x0, y0, x1, y1)

    @staticmethod
    def _point(value: Any) -> tuple[float, float] | None:
        if all(hasattr(value, name) for name in ("x", "y")):
            coords = (value.x, value.y)
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            coords = tuple(value)
        else:
            return None
        if any(not isinstance(item, (int, float)) for item in coords):
            return None
        return float(coords[0]), float(coords[1])
