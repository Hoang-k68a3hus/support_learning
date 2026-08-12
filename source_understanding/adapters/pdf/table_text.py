from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from .models import PdfBlockObservation, PdfRect
from .tables import (
    PdfRejectedTableObservation,
    PdfTableCellObservation,
    PdfTableDetectionError,
    PdfTableDetectionResult,
    PdfTableObservation,
    PdfTableRowObservation,
    PdfTableSpanFragment,
)


PDF_TEXT_ALIGNED_TABLE_STRATEGY = "text_aligned"
_OPERATOR_CHARACTERS = frozenset("=:;+−-×÷*/|<>≤≥±→←↔")


@dataclass(frozen=True, slots=True)
class PdfTextAlignedTablePolicy:
    minimum_rows: int = 3
    minimum_columns: int = 3
    segment_join_gap_points: float = 8.0
    column_alignment_tolerance_points: float = 8.0
    minimum_column_gap_points: float = 12.0
    minimum_row_gap_ratio: float = 0.30
    maximum_row_gap_ratio: float = 3.0
    visual_row_overlap_ratio: float = 0.60
    operator_lane_ratio: float = 0.60


@dataclass(frozen=True, slots=True)
class _VisualSegment:
    bbox: PdfRect
    fragments: tuple[PdfTableSpanFragment, ...]

    @property
    def text(self) -> str:
        output = ""
        for fragment in self.fragments:
            part = fragment.span.text
            if not output:
                output = part
            elif not part:
                continue
            elif output[-1].isspace() or part[0].isspace():
                output += part
            else:
                output += " " + part
        return output


@dataclass(frozen=True, slots=True)
class _VisualRow:
    bbox: PdfRect
    segments: tuple[_VisualSegment, ...]


class PdfTextAlignedTableDetector:
    """Precision-first borderless table detector grounded only in native text geometry.

    M2.3 does not call OCR and does not treat generic page text as a table. It
    requires a repeated rectangular alignment pattern, visible whitespace between
    columns and rows, and unambiguous ownership of every source span in the
    candidate. Geometry remains a derived structural projection.
    """

    def __init__(self, policy: PdfTextAlignedTablePolicy | None = None) -> None:
        self.policy = policy if policy is not None else PdfTextAlignedTablePolicy()

    def detect(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
    ) -> PdfTableDetectionResult:
        if not blocks:
            return PdfTableDetectionResult()

        rows = self._visual_rows(blocks)
        candidate_runs = self._candidate_runs(rows)
        if not candidate_runs:
            return PdfTableDetectionResult()

        accepted: list[PdfTableObservation] = []
        rejected: list[PdfRejectedTableObservation] = []
        consumed_orders: set[int] = set()
        for table_index, run in enumerate(candidate_runs):
            try:
                table = self._build_table(
                    table_index,
                    run,
                    blocks=blocks,
                    page=page,
                )
            except _RejectedTextCandidate as exc:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason=exc.reason,
                        bbox=exc.bbox,
                        row_count=exc.row_count,
                        column_count=exc.column_count,
                        detail=exc.detail,
                    )
                )
                continue
            except Exception as exc:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="text_aligned_candidate_inspection_failed",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            overlap = consumed_orders.intersection(table.source_native_orders)
            if overlap:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="text_aligned_overlapping_source_ownership",
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

    def _visual_rows(
        self,
        blocks: tuple[PdfBlockObservation, ...],
    ) -> tuple[_VisualRow, ...]:
        segments: list[_VisualSegment] = []
        for block in blocks:
            for line in block.lines:
                fragments = [
                    PdfTableSpanFragment(
                        block_number=block.native_block_number,
                        block_native_order=block.native_order,
                        line_native_order=line.native_order,
                        span=span,
                    )
                    for span in line.spans
                    if span.text.strip()
                ]
                if not fragments:
                    continue
                fragments.sort(key=lambda item: (item.span.bbox[0], item.span.native_order))
                current: list[PdfTableSpanFragment] = []
                for fragment in fragments:
                    if not current:
                        current = [fragment]
                        continue
                    current_bbox = self._union(
                        tuple(item.span.bbox for item in current)
                    )
                    gap = fragment.span.bbox[0] - current_bbox[2]
                    if (
                        gap <= self.policy.segment_join_gap_points
                        and self._vertical_overlap_ratio(
                            current_bbox,
                            fragment.span.bbox,
                        )
                        >= self.policy.visual_row_overlap_ratio
                    ):
                        current.append(fragment)
                    else:
                        segments.append(self._segment(tuple(current)))
                        current = [fragment]
                if current:
                    segments.append(self._segment(tuple(current)))

        visual_rows: list[list[_VisualSegment]] = []
        for segment in sorted(
            segments,
            key=lambda item: (item.bbox[1], item.bbox[0]),
        ):
            target: list[_VisualSegment] | None = None
            for row in reversed(visual_rows[-3:]):
                row_bbox = self._union(tuple(item.bbox for item in row))
                if (
                    self._vertical_overlap_ratio(segment.bbox, row_bbox)
                    >= self.policy.visual_row_overlap_ratio
                ):
                    target = row
                    break
            if target is None:
                visual_rows.append([segment])
            else:
                target.append(segment)

        output: list[_VisualRow] = []
        for row in visual_rows:
            row.sort(key=lambda item: item.bbox[0])
            bbox = self._union(tuple(item.bbox for item in row))
            output.append(_VisualRow(bbox=bbox, segments=tuple(row)))
        output.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
        return tuple(output)

    def _candidate_runs(
        self,
        rows: tuple[_VisualRow, ...],
    ) -> tuple[tuple[_VisualRow, ...], ...]:
        proposals: list[tuple[int, int, tuple[_VisualRow, ...]]] = []
        for start in range(len(rows)):
            column_count = len(rows[start].segments)
            if column_count < self.policy.minimum_columns:
                continue
            end = start
            while end + 1 < len(rows) and len(rows[end + 1].segments) == column_count:
                candidate = rows[start : end + 2]
                if not self._columns_align(candidate):
                    break
                end += 1
            if end - start + 1 >= self.policy.minimum_rows:
                proposals.append((start, end, rows[start : end + 1]))

        proposals.sort(key=lambda item: (-(item[1] - item[0] + 1), item[0]))
        selected: list[tuple[int, int, tuple[_VisualRow, ...]]] = []
        occupied: set[int] = set()
        for start, end, run in proposals:
            indexes = set(range(start, end + 1))
            if occupied.intersection(indexes):
                continue
            selected.append((start, end, run))
            occupied.update(indexes)
        selected.sort(key=lambda item: item[0])
        return tuple(item[2] for item in selected)

    def _columns_align(self, rows: tuple[_VisualRow, ...]) -> bool:
        if not rows:
            return False
        column_count = len(rows[0].segments)
        if any(len(row.segments) != column_count for row in rows):
            return False
        tolerance = self.policy.column_alignment_tolerance_points
        for column in range(column_count):
            x0_values = [row.segments[column].bbox[0] for row in rows]
            x1_values = [row.segments[column].bbox[2] for row in rows]
            left_aligned = max(x0_values) - min(x0_values) <= tolerance
            right_aligned = max(x1_values) - min(x1_values) <= tolerance
            if not (left_aligned or right_aligned):
                return False
        return True

    def _build_table(
        self,
        table_index: int,
        rows: tuple[_VisualRow, ...],
        *,
        blocks: tuple[PdfBlockObservation, ...],
        page: Any,
    ) -> PdfTableObservation:
        row_count = len(rows)
        column_count = len(rows[0].segments)
        text_bbox = self._union(tuple(row.bbox for row in rows))

        for row in rows:
            for index in range(column_count - 1):
                gap = row.segments[index + 1].bbox[0] - row.segments[index].bbox[2]
                if gap < self.policy.minimum_column_gap_points:
                    raise _RejectedTextCandidate(
                        "text_aligned_insufficient_column_gap",
                        bbox=text_bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )

        row_heights = [max(0.01, row.bbox[3] - row.bbox[1]) for row in rows]
        row_gap_ratios = [
            max(0.0, rows[index + 1].bbox[1] - rows[index].bbox[3])
            / min(row_heights[index], row_heights[index + 1])
            for index in range(row_count - 1)
        ]
        if row_gap_ratios:
            typical_gap = median(row_gap_ratios)
            if typical_gap < self.policy.minimum_row_gap_ratio:
                raise _RejectedTextCandidate(
                    "text_aligned_dense_row_spacing",
                    bbox=text_bbox,
                    row_count=row_count,
                    column_count=column_count,
                    detail=f"median_row_gap_ratio={typical_gap:.4f}",
                )
            if typical_gap > self.policy.maximum_row_gap_ratio:
                raise _RejectedTextCandidate(
                    "text_aligned_rows_too_far_apart",
                    bbox=text_bbox,
                    row_count=row_count,
                    column_count=column_count,
                    detail=f"median_row_gap_ratio={typical_gap:.4f}",
                )

        operator_column = self._operator_lane(rows)
        if operator_column is not None:
            raise _RejectedTextCandidate(
                "text_aligned_operator_lane",
                bbox=text_bbox,
                row_count=row_count,
                column_count=column_count,
                detail=f"operator_column={operator_column}",
            )

        owned_span_orders = {
            fragment.span.native_order
            for row in rows
            for segment in row.segments
            for fragment in segment.fragments
        }
        consumed_block_orders: set[int] = set()
        consumed_block_numbers: set[int] = set()
        for block in blocks:
            nonblank_span_orders = {
                span.native_order
                for line in block.lines
                for span in line.spans
                if span.text.strip()
            }
            owned_in_block = nonblank_span_orders.intersection(owned_span_orders)
            if not owned_in_block:
                continue
            if owned_in_block != nonblank_span_orders:
                raise _RejectedTextCandidate(
                    "text_aligned_source_block_crosses_boundary",
                    bbox=text_bbox,
                    row_count=row_count,
                    column_count=column_count,
                )
            consumed_block_orders.add(block.native_order)
            consumed_block_numbers.add(block.native_block_number)

        if not consumed_block_orders:
            raise _RejectedTextCandidate(
                "text_aligned_no_source_text_ownership",
                bbox=text_bbox,
                row_count=row_count,
                column_count=column_count,
            )
        block_positions = {block.native_order: index for index, block in enumerate(blocks)}
        positions = sorted(block_positions[item] for item in consumed_block_orders)
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise _RejectedTextCandidate(
                "text_aligned_source_blocks_noncontiguous",
                bbox=text_bbox,
                row_count=row_count,
                column_count=column_count,
            )

        x_boundaries = self._column_boundaries(rows)
        y_boundaries = self._row_boundaries(rows)
        table_rows: list[PdfTableRowObservation] = []
        for row_index, row in enumerate(rows):
            cells: list[PdfTableCellObservation] = []
            for column_index, segment in enumerate(row.segments):
                bbox = (
                    x_boundaries[column_index],
                    y_boundaries[row_index],
                    x_boundaries[column_index + 1],
                    y_boundaries[row_index + 1],
                )
                cells.append(
                    PdfTableCellObservation(
                        row_index=row_index,
                        cell_index=column_index,
                        bbox=bbox,
                        displayed_bbox=self._displayed_rect(page, bbox),
                        text=segment.text,
                        fragments=segment.fragments,
                    )
                )
            row_bbox = self._union(tuple(cell.bbox for cell in cells))
            table_rows.append(
                PdfTableRowObservation(
                    row_index=row_index,
                    bbox=row_bbox,
                    displayed_bbox=self._displayed_rect(page, row_bbox),
                    cells=tuple(cells),
                )
            )

        table_bbox = self._union(tuple(row.bbox for row in table_rows))
        return PdfTableObservation(
            table_index=table_index,
            bbox=table_bbox,
            displayed_bbox=self._displayed_rect(page, table_bbox),
            rows=tuple(table_rows),
            source_block_numbers=tuple(sorted(consumed_block_numbers)),
            source_native_orders=tuple(sorted(consumed_block_orders)),
            detection_strategy=PDF_TEXT_ALIGNED_TABLE_STRATEGY,
        )

    def _operator_lane(self, rows: tuple[_VisualRow, ...]) -> int | None:
        for column in range(len(rows[0].segments)):
            operator_cells = sum(
                self._operator_only(row.segments[column].text) for row in rows
            )
            if operator_cells / len(rows) >= self.policy.operator_lane_ratio:
                return column
        return None

    @staticmethod
    def _operator_only(text: str) -> bool:
        compact = "".join(text.split())
        return bool(compact) and all(character in _OPERATOR_CHARACTERS for character in compact)

    def _column_boundaries(
        self,
        rows: tuple[_VisualRow, ...],
    ) -> tuple[float, ...]:
        column_count = len(rows[0].segments)
        left_edges = [min(row.segments[index].bbox[0] for row in rows) for index in range(column_count)]
        right_edges = [max(row.segments[index].bbox[2] for row in rows) for index in range(column_count)]
        boundaries = [left_edges[0]]
        for index in range(column_count - 1):
            boundaries.append((right_edges[index] + left_edges[index + 1]) / 2.0)
        boundaries.append(right_edges[-1])
        if any(boundaries[index + 1] <= boundaries[index] for index in range(len(boundaries) - 1)):
            raise _RejectedTextCandidate("text_aligned_invalid_column_boundaries")
        return tuple(boundaries)

    def _row_boundaries(
        self,
        rows: tuple[_VisualRow, ...],
    ) -> tuple[float, ...]:
        boundaries = [rows[0].bbox[1]]
        for index in range(len(rows) - 1):
            boundaries.append((rows[index].bbox[3] + rows[index + 1].bbox[1]) / 2.0)
        boundaries.append(rows[-1].bbox[3])
        if any(boundaries[index + 1] <= boundaries[index] for index in range(len(boundaries) - 1)):
            raise _RejectedTextCandidate("text_aligned_invalid_row_boundaries")
        return tuple(boundaries)

    @staticmethod
    def has_rectilinear_vector_evidence(paths: Any) -> bool:
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
                    rect = PdfTextAlignedTableDetector._rect(item[1])
                    if rect is not None and PdfTextAlignedTableDetector._area(rect) > 0:
                        horizontal += 2
                        vertical += 2
                elif kind == "l" and len(item) >= 3:
                    start = PdfTextAlignedTableDetector._point(item[1])
                    end = PdfTextAlignedTableDetector._point(item[2])
                    if start is None or end is None:
                        continue
                    if abs(start[1] - end[1]) <= tolerance and abs(start[0] - end[0]) > tolerance:
                        horizontal += 1
                    elif abs(start[0] - end[0]) <= tolerance and abs(start[1] - end[1]) > tolerance:
                        vertical += 1
        return horizontal >= 3 and vertical >= 3

    def _segment(
        self,
        fragments: tuple[PdfTableSpanFragment, ...],
    ) -> _VisualSegment:
        return _VisualSegment(
            bbox=self._union(tuple(item.span.bbox for item in fragments)),
            fragments=fragments,
        )

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
                f"text-aligned table bbox rotation failed: {type(exc).__name__}: {exc}"
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
    def _area(rect: PdfRect) -> float:
        return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])

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


class _RejectedTextCandidate(Exception):
    def __init__(
        self,
        reason: str,
        *,
        bbox: PdfRect | None = None,
        row_count: int | None = None,
        column_count: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.bbox = bbox
        self.row_count = row_count
        self.column_count = column_count
        self.detail = detail
