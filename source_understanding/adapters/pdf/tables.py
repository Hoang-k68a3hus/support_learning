from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any

from .models import PdfBlockObservation, PdfRect, PdfSpanObservation


PDF_TABLE_STRUCTURE_VERSION = "pymupdf-lines-strict-v1"
PDF_TABLE_TEXT_RECONSTRUCTION_VERSION = "source-spans-v1"


class PdfTableDetectionError(ValueError):
    """PDF table detection could not run safely on one page."""


@dataclass(frozen=True, slots=True)
class PdfTablePolicy:
    minimum_rows: int = 2
    minimum_columns: int = 2
    minimum_cells: int = 6
    minimum_populated_rows: int = 2
    minimum_populated_columns: int = 2
    minimum_populated_cells: int = 4
    minimum_span_cell_overlap_ratio: float = 0.50
    visual_line_overlap_ratio: float = 0.60
    topology_tolerance_points: float = 3.0


@dataclass(frozen=True, slots=True)
class PdfTableSpanFragment:
    block_number: int
    block_native_order: int
    line_native_order: int
    span: PdfSpanObservation


@dataclass(frozen=True, slots=True)
class PdfTableCellObservation:
    row_index: int
    cell_index: int
    bbox: PdfRect
    displayed_bbox: PdfRect
    text: str
    fragments: tuple[PdfTableSpanFragment, ...]


@dataclass(frozen=True, slots=True)
class PdfTableRowObservation:
    row_index: int
    bbox: PdfRect
    displayed_bbox: PdfRect
    cells: tuple[PdfTableCellObservation, ...]


@dataclass(frozen=True, slots=True)
class PdfTableObservation:
    table_index: int
    bbox: PdfRect
    displayed_bbox: PdfRect
    rows: tuple[PdfTableRowObservation, ...]
    source_block_numbers: tuple[int, ...]
    source_native_orders: tuple[int, ...]
    detection_strategy: str = "lines_strict"

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.rows[0].cells) if self.rows else 0


@dataclass(frozen=True, slots=True)
class PdfRejectedTableObservation:
    table_index: int
    reason: str
    bbox: PdfRect | None = None
    row_count: int | None = None
    column_count: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PdfTableDetectionResult:
    tables: tuple[PdfTableObservation, ...] = ()
    rejected: tuple[PdfRejectedTableObservation, ...] = ()


class PdfTableDetector:
    """Conservative v1 detector for line-bordered rectangular PDF tables.

    Detection is deliberately precision-first. PyMuPDF proposes vector-line table
    candidates, then this class verifies a simple rectangular topology and binds
    every in-table source span back to exactly one cell. Any ambiguous source
    ownership rejects the candidate so the adapter can preserve its M1 blocks.
    """

    def __init__(self, policy: PdfTablePolicy | None = None) -> None:
        self.policy = policy if policy is not None else PdfTablePolicy()

    def detect(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
    ) -> PdfTableDetectionResult:
        if not blocks:
            return PdfTableDetectionResult()

        try:
            paths = page.get_drawings()
        except Exception as exc:
            raise PdfTableDetectionError(
                f"vector path inspection failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not self._has_rectilinear_table_evidence(paths):
            return PdfTableDetectionResult()

        try:
            finder = page.find_tables(strategy="lines_strict", paths=paths)
            candidates = tuple(getattr(finder, "tables", ()) or ())
        except Exception as exc:
            raise PdfTableDetectionError(
                f"PyMuPDF find_tables failed: {type(exc).__name__}: {exc}"
            ) from exc

        accepted: list[PdfTableObservation] = []
        rejected: list[PdfRejectedTableObservation] = []
        consumed_orders: set[int] = set()
        for table_index, candidate in enumerate(candidates):
            try:
                table = self._inspect_candidate(
                    table_index,
                    candidate,
                    blocks,
                    page=page,
                )
            except _RejectedCandidate as exc:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason=exc.reason,
                        bbox=exc.bbox,
                        row_count=exc.row_count,
                        column_count=exc.column_count,
                    )
                )
                continue
            except Exception as exc:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="candidate_inspection_failed",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            overlap = consumed_orders.intersection(table.source_native_orders)
            if overlap:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="overlapping_source_ownership",
                        bbox=table.bbox,
                        row_count=table.row_count,
                        column_count=table.column_count,
                    )
                )
                continue
            accepted.append(table)
            consumed_orders.update(table.source_native_orders)

        accepted.sort(key=lambda item: item.source_native_orders[0])
        return PdfTableDetectionResult(tuple(accepted), tuple(rejected))

    def _inspect_candidate(
        self,
        table_index: int,
        candidate: Any,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page: Any,
    ) -> PdfTableObservation:
        bbox = self._rect(getattr(candidate, "bbox", None))
        row_count = self._positive_int(getattr(candidate, "row_count", None))
        column_count = self._positive_int(getattr(candidate, "col_count", None))
        if bbox is None or row_count is None or column_count is None:
            raise _RejectedCandidate("invalid_candidate_geometry", bbox=bbox)
        if (
            row_count < self.policy.minimum_rows
            or column_count < self.policy.minimum_columns
            or row_count * column_count < self.policy.minimum_cells
        ):
            raise _RejectedCandidate(
                "candidate_too_small",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        raw_rows = tuple(getattr(candidate, "rows", ()) or ())
        if len(raw_rows) != row_count:
            raise _RejectedCandidate(
                "row_topology_mismatch",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        cell_grid: list[list[PdfRect]] = []
        for row in raw_rows:
            raw_cells = tuple(getattr(row, "cells", ()) or ())
            if len(raw_cells) != column_count:
                raise _RejectedCandidate(
                    "column_topology_mismatch",
                    bbox=bbox,
                    row_count=row_count,
                    column_count=column_count,
                )
            cells: list[PdfRect] = []
            for raw_cell in raw_cells:
                cell = self._rect(raw_cell)
                if cell is None or self._area(cell) <= 0:
                    raise _RejectedCandidate(
                        "complex_or_merged_cells",
                        bbox=bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                cells.append(cell)
            cell_grid.append(cells)

        if not self._simple_rectangular_topology(cell_grid, table_bbox=bbox):
            raise _RejectedCandidate(
                "complex_or_irregular_topology",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        fragments_by_cell: list[list[list[PdfTableSpanFragment]]] = [
            [[] for _ in range(column_count)] for _ in range(row_count)
        ]
        consumed_block_orders: set[int] = set()
        consumed_block_numbers: set[int] = set()
        for block in blocks:
            has_inside = False
            has_nonblank_outside = False
            for line in block.lines:
                for span in line.spans:
                    if not span.text:
                        continue
                    relevant = self._span_relevant_to_table(span.bbox, bbox)
                    if not relevant:
                        if span.text.strip():
                            has_nonblank_outside = True
                        continue
                    assignment = self._cell_for_span(span.bbox, cell_grid)
                    if assignment is None:
                        raise _RejectedCandidate(
                            "ambiguous_source_span_assignment",
                            bbox=bbox,
                            row_count=row_count,
                            column_count=column_count,
                        )
                    row_index, cell_index = assignment
                    fragments_by_cell[row_index][cell_index].append(
                        PdfTableSpanFragment(
                            block_number=block.native_block_number,
                            block_native_order=block.native_order,
                            line_native_order=line.native_order,
                            span=span,
                        )
                    )
                    has_inside = True
            if has_inside:
                if has_nonblank_outside:
                    raise _RejectedCandidate(
                        "source_block_crosses_table_boundary",
                        bbox=bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                consumed_block_orders.add(block.native_order)
                consumed_block_numbers.add(block.native_block_number)

        if not consumed_block_orders:
            raise _RejectedCandidate(
                "no_source_text_ownership",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        block_positions = {
            block.native_order: index for index, block in enumerate(blocks)
        }
        consumed_positions = sorted(block_positions[item] for item in consumed_block_orders)
        if consumed_positions != list(
            range(consumed_positions[0], consumed_positions[-1] + 1)
        ):
            raise _RejectedCandidate(
                "source_blocks_noncontiguous",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        populated_cells = sum(
            bool(fragments_by_cell[row][column])
            for row in range(row_count)
            for column in range(column_count)
        )
        populated_rows = sum(
            any(fragments_by_cell[row][column] for column in range(column_count))
            for row in range(row_count)
        )
        populated_columns = sum(
            any(fragments_by_cell[row][column] for row in range(row_count))
            for column in range(column_count)
        )
        if (
            populated_cells < self.policy.minimum_populated_cells
            or populated_rows < self.policy.minimum_populated_rows
            or populated_columns < self.policy.minimum_populated_columns
        ):
            raise _RejectedCandidate(
                "insufficient_populated_cells",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        rows: list[PdfTableRowObservation] = []
        for row_index, row_cells in enumerate(cell_grid):
            cells: list[PdfTableCellObservation] = []
            for cell_index, cell_bbox in enumerate(row_cells):
                fragments = tuple(
                    sorted(
                        fragments_by_cell[row_index][cell_index],
                        key=lambda item: (
                            item.line_native_order,
                            item.span.native_order,
                        ),
                    )
                )
                cells.append(
                    PdfTableCellObservation(
                        row_index=row_index,
                        cell_index=cell_index,
                        bbox=cell_bbox,
                        displayed_bbox=self._displayed_rect(page, cell_bbox),
                        text=self._reconstruct_cell_text(fragments),
                        fragments=fragments,
                    )
                )
            row_bbox = self._union(tuple(cell.bbox for cell in cells))
            rows.append(
                PdfTableRowObservation(
                    row_index=row_index,
                    bbox=row_bbox,
                    displayed_bbox=self._displayed_rect(page, row_bbox),
                    cells=tuple(cells),
                )
            )

        return PdfTableObservation(
            table_index=table_index,
            bbox=bbox,
            displayed_bbox=self._displayed_rect(page, bbox),
            rows=tuple(rows),
            source_block_numbers=tuple(sorted(consumed_block_numbers)),
            source_native_orders=tuple(sorted(consumed_block_orders)),
        )

    def _simple_rectangular_topology(
        self,
        rows: list[list[PdfRect]],
        *,
        table_bbox: PdfRect,
    ) -> bool:
        if not rows or not rows[0]:
            return False
        tolerance = self.policy.topology_tolerance_points
        reference = rows[0]
        reference_x = tuple((cell[0], cell[2]) for cell in reference)
        previous_bottom: float | None = None
        for row in rows:
            row_union = self._union(tuple(row))
            if previous_bottom is not None and row_union[1] < previous_bottom - tolerance:
                return False
            previous_bottom = row_union[3]
            for index, cell in enumerate(row):
                if cell[0] < table_bbox[0] - tolerance or cell[2] > table_bbox[2] + tolerance:
                    return False
                if cell[1] < table_bbox[1] - tolerance or cell[3] > table_bbox[3] + tolerance:
                    return False
                if not isclose(cell[1], row_union[1], abs_tol=tolerance):
                    return False
                if not isclose(cell[3], row_union[3], abs_tol=tolerance):
                    return False
                ref_x0, ref_x1 = reference_x[index]
                if not isclose(cell[0], ref_x0, abs_tol=tolerance):
                    return False
                if not isclose(cell[2], ref_x1, abs_tol=tolerance):
                    return False
                if index and cell[0] < row[index - 1][2] - tolerance:
                    return False
        union = self._union(tuple(cell for row in rows for cell in row))
        return all(
            isclose(union[index], table_bbox[index], abs_tol=tolerance)
            for index in range(4)
        )

    def _span_relevant_to_table(self, span: PdfRect, table: PdfRect) -> bool:
        return (
            self._coverage(span, table) >= self.policy.minimum_span_cell_overlap_ratio
            or self._contains_point(table, self._center(span))
        )

    def _cell_for_span(
        self,
        span: PdfRect,
        cells: list[list[PdfRect]],
    ) -> tuple[int, int] | None:
        center = self._center(span)
        center_matches = [
            (row_index, cell_index)
            for row_index, row in enumerate(cells)
            for cell_index, cell in enumerate(row)
            if self._contains_point(cell, center)
        ]
        if len(center_matches) == 1:
            return center_matches[0]

        scored = [
            (self._coverage(span, cell), row_index, cell_index)
            for row_index, row in enumerate(cells)
            for cell_index, cell in enumerate(row)
        ]
        scored.sort(reverse=True)
        if not scored or scored[0][0] < self.policy.minimum_span_cell_overlap_ratio:
            return None
        if len(scored) > 1 and isclose(scored[0][0], scored[1][0], abs_tol=1e-9):
            return None
        return scored[0][1], scored[0][2]

    def _reconstruct_cell_text(
        self,
        fragments: tuple[PdfTableSpanFragment, ...],
    ) -> str:
        if not fragments:
            return ""

        by_source_line: dict[int, list[PdfTableSpanFragment]] = {}
        for fragment in fragments:
            by_source_line.setdefault(fragment.line_native_order, []).append(fragment)

        line_segments: list[tuple[PdfRect, str, int]] = []
        for line_order, items in sorted(by_source_line.items()):
            items.sort(key=lambda item: item.span.native_order)
            text = "".join(item.span.text for item in items)
            bbox = self._union(tuple(item.span.bbox for item in items))
            line_segments.append((bbox, text, line_order))

        visual_rows: list[list[tuple[PdfRect, str, int]]] = []
        for segment in sorted(line_segments, key=lambda item: (item[0][1], item[0][0], item[2])):
            target: list[tuple[PdfRect, str, int]] | None = None
            for row in visual_rows:
                row_bbox = self._union(tuple(item[0] for item in row))
                if self._vertical_overlap_ratio(segment[0], row_bbox) >= self.policy.visual_line_overlap_ratio:
                    target = row
                    break
            if target is None:
                visual_rows.append([segment])
            else:
                target.append(segment)

        output: list[str] = []
        for row in visual_rows:
            row.sort(key=lambda item: (item[0][0], item[2]))
            output.append(self._join_segments(tuple(item[1] for item in row)))
        return "\n".join(output)

    @staticmethod
    def _join_segments(parts: tuple[str, ...]) -> str:
        output = ""
        for part in parts:
            if not output:
                output = part
            elif not part:
                continue
            elif output[-1].isspace() or part[0].isspace():
                output += part
            else:
                output += " " + part
        return output

    @staticmethod
    def _has_rectilinear_table_evidence(paths: Any) -> bool:
        if not isinstance(paths, (list, tuple)):
            return False
        horizontal = 0
        vertical = 0
        tolerance = 0.5
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
                if kind == "re" and len(item) >= 2:
                    rect = PdfTableDetector._rect(item[1])
                    if rect is not None and PdfTableDetector._area(rect) > 0:
                        horizontal += 2
                        vertical += 2
                elif kind == "l" and len(item) >= 3:
                    start = PdfTableDetector._point(item[1])
                    end = PdfTableDetector._point(item[2])
                    if start is None or end is None:
                        continue
                    if abs(start[1] - end[1]) <= tolerance and abs(start[0] - end[0]) > tolerance:
                        horizontal += 1
                    elif abs(start[0] - end[0]) <= tolerance and abs(start[1] - end[1]) > tolerance:
                        vertical += 1
        return horizontal >= 3 and vertical >= 3

    @staticmethod
    def _displayed_rect(page: Any, bbox: PdfRect) -> PdfRect:
        try:
            rect_type = type(page.rect)
            rect = rect_type(bbox)
            if int(getattr(page, "rotation", 0)) % 360:
                rect = rect * page.rotation_matrix
            return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
        except Exception as exc:
            raise PdfTableDetectionError(
                f"table bbox rotation failed: {type(exc).__name__}: {exc}"
            ) from exc

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

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _center(rect: PdfRect) -> tuple[float, float]:
        return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)

    @staticmethod
    def _contains_point(rect: PdfRect, point: tuple[float, float]) -> bool:
        return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]

    @staticmethod
    def _area(rect: PdfRect) -> float:
        return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])

    @classmethod
    def _coverage(cls, subject: PdfRect, container: PdfRect) -> float:
        area = cls._area(subject)
        if area <= 0:
            return 0.0
        x0 = max(subject[0], container[0])
        y0 = max(subject[1], container[1])
        x1 = min(subject[2], container[2])
        y1 = min(subject[3], container[3])
        intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        return intersection / area

    @classmethod
    def _vertical_overlap_ratio(cls, left: PdfRect, right: PdfRect) -> float:
        overlap = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
        denominator = min(left[3] - left[1], right[3] - right[1])
        return overlap / denominator if denominator > 0 else 0.0

    @staticmethod
    def _union(rects: tuple[PdfRect, ...]) -> PdfRect:
        if not rects:
            raise ValueError("cannot union empty PDF rectangle collection")
        return (
            min(item[0] for item in rects),
            min(item[1] for item in rects),
            max(item[2] for item in rects),
            max(item[3] for item in rects),
        )


class _RejectedCandidate(Exception):
    def __init__(
        self,
        reason: str,
        *,
        bbox: PdfRect | None = None,
        row_count: int | None = None,
        column_count: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.bbox = bbox
        self.row_count = row_count
        self.column_count = column_count
