from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any

from .models import PdfBlockObservation, PdfRect
from .tables import (
    PdfRejectedTableObservation,
    PdfTableCellObservation,
    PdfTableDetectionError,
    PdfTableDetectionResult,
    PdfTableDetector,
    PdfTableObservation,
    PdfTableRowObservation,
    PdfTableSpanFragment,
)


PDF_MERGED_TABLE_STRATEGY = "lines_strict_merged"


@dataclass(frozen=True, slots=True)
class PdfMergedTableObservation(PdfTableObservation):
    """Verified rectangular merged-cell table with a logical column count."""

    logical_column_count: int = 0

    @property
    def column_count(self) -> int:
        return self.logical_column_count


@dataclass(frozen=True, slots=True)
class _MergedCell:
    row_index: int
    cell_index: int
    row_span: int
    column_span: int
    bbox: PdfRect


@dataclass(frozen=True, slots=True)
class _MergedGrid:
    row_boundaries: tuple[float, ...]
    column_boundaries: tuple[float, ...]
    cells: tuple[_MergedCell, ...]


class _RejectedMergedCandidate(ValueError):
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


class PdfMergedTableDetector(PdfTableDetector):
    """M2.4 detector for rectangular row/column spans in ruled native PDFs.

    It only inspects line-table candidates that the simple M2 path rejected. A
    missing PyMuPDF grid slot is accepted only when a single rectangular anchor
    cell covers it. Holes, overlaps, unresolvable grid boundaries, or ambiguous
    source-span ownership reject the candidate and preserve M1 text.
    """

    def detect(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        candidate_indexes: frozenset[int] | None = None,
        reserved_source_orders: frozenset[int] = frozenset(),
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
        consumed_orders = set(reserved_source_orders)
        requested = candidate_indexes
        for table_index, candidate in enumerate(candidates):
            if requested is not None and table_index not in requested:
                continue
            try:
                table = self._inspect_merged_candidate(
                    table_index,
                    candidate,
                    blocks,
                    page=page,
                )
            except _RejectedMergedCandidate as exc:
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
                        reason="merged_candidate_inspection_failed",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            overlap = consumed_orders.intersection(table.source_native_orders)
            if overlap:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="merged_overlapping_source_ownership",
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

    def _inspect_merged_candidate(
        self,
        table_index: int,
        candidate: Any,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page: Any,
    ) -> PdfMergedTableObservation:
        bbox = self._rect(getattr(candidate, "bbox", None))
        row_count = self._positive_int(getattr(candidate, "row_count", None))
        column_count = self._positive_int(getattr(candidate, "col_count", None))
        if bbox is None or row_count is None or column_count is None:
            raise _RejectedMergedCandidate("invalid_merged_candidate_geometry", bbox=bbox)
        if (
            row_count < self.policy.minimum_rows
            or column_count < self.policy.minimum_columns
            or row_count * column_count < self.policy.minimum_cells
        ):
            raise _RejectedMergedCandidate(
                "merged_candidate_too_small",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        raw_rows = tuple(getattr(candidate, "rows", ()) or ())
        if len(raw_rows) != row_count:
            raise _RejectedMergedCandidate(
                "merged_row_topology_mismatch",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )
        row_cells: list[tuple[PdfRect | None, ...]] = []
        has_missing_slot = False
        for row in raw_rows:
            raw_cells = tuple(getattr(row, "cells", ()) or ())
            if len(raw_cells) != column_count:
                raise _RejectedMergedCandidate(
                    "merged_column_topology_mismatch",
                    bbox=bbox,
                    row_count=row_count,
                    column_count=column_count,
                )
            parsed: list[PdfRect | None] = []
            for raw_cell in raw_cells:
                cell = self._rect(raw_cell)
                if cell is None:
                    parsed.append(None)
                    has_missing_slot = True
                elif self._area(cell) <= 0:
                    raise _RejectedMergedCandidate(
                        "merged_invalid_cell_geometry",
                        bbox=bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                else:
                    parsed.append(cell)
            row_cells.append(tuple(parsed))
        if not has_missing_slot:
            raise _RejectedMergedCandidate(
                "candidate_has_no_merged_slots",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        grid = self._infer_merged_grid(
            tuple(row_cells),
            table_bbox=bbox,
            row_count=row_count,
            column_count=column_count,
        )
        fragments_by_anchor: list[list[PdfTableSpanFragment]] = [
            [] for _ in grid.cells
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
                    if not self._span_relevant_to_table(span.bbox, bbox):
                        if span.text.strip():
                            has_nonblank_outside = True
                        continue
                    anchor_index = self._anchor_for_span(span.bbox, grid.cells)
                    if anchor_index is None:
                        raise _RejectedMergedCandidate(
                            "merged_ambiguous_source_span_assignment",
                            bbox=bbox,
                            row_count=row_count,
                            column_count=column_count,
                        )
                    fragments_by_anchor[anchor_index].append(
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
                    raise _RejectedMergedCandidate(
                        "merged_source_block_crosses_table_boundary",
                        bbox=bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                consumed_block_orders.add(block.native_order)
                consumed_block_numbers.add(block.native_block_number)

        if not consumed_block_orders:
            raise _RejectedMergedCandidate(
                "merged_no_source_text_ownership",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        block_positions = {block.native_order: index for index, block in enumerate(blocks)}
        consumed_positions = sorted(block_positions[item] for item in consumed_block_orders)
        if consumed_positions != list(range(consumed_positions[0], consumed_positions[-1] + 1)):
            raise _RejectedMergedCandidate(
                "merged_source_blocks_noncontiguous",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        populated_anchor_indexes = {
            index for index, fragments in enumerate(fragments_by_anchor) if fragments
        }
        populated_rows = {
            grid.cells[index].row_index for index in populated_anchor_indexes
        }
        populated_columns: set[int] = set()
        for index in populated_anchor_indexes:
            cell = grid.cells[index]
            populated_columns.update(
                range(cell.cell_index, cell.cell_index + cell.column_span)
            )
        if (
            len(populated_anchor_indexes) < self.policy.minimum_populated_cells
            or len(populated_rows) < self.policy.minimum_populated_rows
            or len(populated_columns) < self.policy.minimum_populated_columns
        ):
            raise _RejectedMergedCandidate(
                "merged_insufficient_populated_cells",
                bbox=bbox,
                row_count=row_count,
                column_count=column_count,
            )

        observations_by_row: dict[int, list[PdfTableCellObservation]] = {
            index: [] for index in range(row_count)
        }
        for anchor_index, anchor in enumerate(grid.cells):
            fragments = tuple(
                sorted(
                    fragments_by_anchor[anchor_index],
                    key=lambda item: (item.line_native_order, item.span.native_order),
                )
            )
            observations_by_row[anchor.row_index].append(
                PdfTableCellObservation(
                    row_index=anchor.row_index,
                    cell_index=anchor.cell_index,
                    bbox=anchor.bbox,
                    displayed_bbox=self._displayed_rect(page, anchor.bbox),
                    text=self._reconstruct_cell_text(fragments),
                    fragments=fragments,
                )
            )

        rows: list[PdfTableRowObservation] = []
        for row_index in range(row_count):
            cells = tuple(
                sorted(
                    observations_by_row[row_index],
                    key=lambda item: item.cell_index,
                )
            )
            row_bbox = (
                bbox[0],
                grid.row_boundaries[row_index],
                bbox[2],
                grid.row_boundaries[row_index + 1],
            )
            rows.append(
                PdfTableRowObservation(
                    row_index=row_index,
                    bbox=row_bbox,
                    displayed_bbox=self._displayed_rect(page, row_bbox),
                    cells=cells,
                )
            )

        return PdfMergedTableObservation(
            table_index=table_index,
            bbox=bbox,
            displayed_bbox=self._displayed_rect(page, bbox),
            rows=tuple(rows),
            source_block_numbers=tuple(sorted(consumed_block_numbers)),
            source_native_orders=tuple(sorted(consumed_block_orders)),
            detection_strategy=PDF_MERGED_TABLE_STRATEGY,
            logical_column_count=column_count,
        )

    def _infer_merged_grid(
        self,
        rows: tuple[tuple[PdfRect | None, ...], ...],
        *,
        table_bbox: PdfRect,
        row_count: int,
        column_count: int,
    ) -> _MergedGrid:
        tolerance = self.policy.topology_tolerance_points
        rects = tuple(cell for row in rows for cell in row if cell is not None)
        if not rects:
            raise _RejectedMergedCandidate(
                "merged_no_cell_geometry",
                bbox=table_bbox,
                row_count=row_count,
                column_count=column_count,
            )
        x_values = [table_bbox[0], table_bbox[2]]
        y_values = [table_bbox[1], table_bbox[3]]
        for cell in rects:
            x_values.extend((cell[0], cell[2]))
            y_values.extend((cell[1], cell[3]))
        x_boundaries = self._cluster_boundaries(x_values, tolerance)
        y_boundaries = self._cluster_boundaries(y_values, tolerance)
        if len(x_boundaries) != column_count + 1 or len(y_boundaries) != row_count + 1:
            raise _RejectedMergedCandidate(
                "merged_grid_boundaries_unresolved",
                bbox=table_bbox,
                row_count=row_count,
                column_count=column_count,
                detail=(
                    f"x_boundaries={len(x_boundaries)};"
                    f"y_boundaries={len(y_boundaries)}"
                ),
            )
        if not (
            isclose(x_boundaries[0], table_bbox[0], abs_tol=tolerance)
            and isclose(x_boundaries[-1], table_bbox[2], abs_tol=tolerance)
            and isclose(y_boundaries[0], table_bbox[1], abs_tol=tolerance)
            and isclose(y_boundaries[-1], table_bbox[3], abs_tol=tolerance)
        ):
            raise _RejectedMergedCandidate(
                "merged_grid_does_not_cover_table_bbox",
                bbox=table_bbox,
                row_count=row_count,
                column_count=column_count,
            )

        coverage: list[list[int | None]] = [
            [None for _ in range(column_count)] for _ in range(row_count)
        ]
        anchors: list[_MergedCell] = []
        for row_index, row in enumerate(rows):
            for cell_index, cell in enumerate(row):
                if cell is None:
                    continue
                x0 = self._boundary_index(x_boundaries, cell[0], tolerance)
                x1 = self._boundary_index(x_boundaries, cell[2], tolerance)
                y0 = self._boundary_index(y_boundaries, cell[1], tolerance)
                y1 = self._boundary_index(y_boundaries, cell[3], tolerance)
                if None in {x0, x1, y0, y1}:
                    raise _RejectedMergedCandidate(
                        "merged_cell_boundary_unresolved",
                        bbox=table_bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                assert x0 is not None and x1 is not None and y0 is not None and y1 is not None
                if x0 != cell_index or y0 != row_index or x1 <= x0 or y1 <= y0:
                    raise _RejectedMergedCandidate(
                        "merged_anchor_slot_mismatch",
                        bbox=table_bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                anchor = _MergedCell(
                    row_index=row_index,
                    cell_index=cell_index,
                    row_span=y1 - y0,
                    column_span=x1 - x0,
                    bbox=cell,
                )
                anchor_index = len(anchors)
                anchors.append(anchor)
                for logical_row in range(y0, y1):
                    for logical_column in range(x0, x1):
                        if coverage[logical_row][logical_column] is not None:
                            raise _RejectedMergedCandidate(
                                "merged_grid_overlap",
                                bbox=table_bbox,
                                row_count=row_count,
                                column_count=column_count,
                            )
                        coverage[logical_row][logical_column] = anchor_index

        has_real_span = any(
            anchor.row_span > 1 or anchor.column_span > 1 for anchor in anchors
        )
        if not has_real_span:
            raise _RejectedMergedCandidate(
                "missing_slots_not_explained_by_span",
                bbox=table_bbox,
                row_count=row_count,
                column_count=column_count,
            )

        for row_index, row in enumerate(rows):
            for cell_index, raw_cell in enumerate(row):
                owner = coverage[row_index][cell_index]
                if owner is None:
                    raise _RejectedMergedCandidate(
                        "merged_grid_hole",
                        bbox=table_bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                anchor = anchors[owner]
                is_anchor = (row_index, cell_index) == (
                    anchor.row_index,
                    anchor.cell_index,
                )
                if raw_cell is None and is_anchor:
                    raise _RejectedMergedCandidate(
                        "merged_anchor_missing_geometry",
                        bbox=table_bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )
                if raw_cell is not None and not is_anchor:
                    raise _RejectedMergedCandidate(
                        "merged_covered_slot_has_geometry",
                        bbox=table_bbox,
                        row_count=row_count,
                        column_count=column_count,
                    )

        return _MergedGrid(
            row_boundaries=y_boundaries,
            column_boundaries=x_boundaries,
            cells=tuple(anchors),
        )

    def _anchor_for_span(
        self,
        span: PdfRect,
        cells: tuple[_MergedCell, ...],
    ) -> int | None:
        center = self._center(span)
        center_matches = [
            index
            for index, cell in enumerate(cells)
            if self._contains_point(cell.bbox, center)
        ]
        if len(center_matches) == 1:
            return center_matches[0]
        scored = [
            (self._coverage(span, cell.bbox), index)
            for index, cell in enumerate(cells)
        ]
        scored.sort(reverse=True)
        if not scored or scored[0][0] < self.policy.minimum_span_cell_overlap_ratio:
            return None
        if len(scored) > 1 and isclose(scored[0][0], scored[1][0], abs_tol=1e-9):
            return None
        return scored[0][1]

    @staticmethod
    def _cluster_boundaries(
        values: list[float],
        tolerance: float,
    ) -> tuple[float, ...]:
        clusters: list[list[float]] = []
        for value in sorted(values):
            if not clusters or value - clusters[-1][-1] > tolerance:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        return tuple(sum(cluster) / len(cluster) for cluster in clusters)

    @staticmethod
    def _boundary_index(
        boundaries: tuple[float, ...],
        value: float,
        tolerance: float,
    ) -> int | None:
        if not boundaries:
            return None
        index = min(range(len(boundaries)), key=lambda item: abs(boundaries[item] - value))
        if abs(boundaries[index] - value) > tolerance:
            return None
        return index
