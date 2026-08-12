from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import PdfBlockLinePartition, PdfBlockObservation, PdfRect
from .source_partition import (
    PdfSourceBlockLinePartitioner,
    PdfSourcePartitionError,
    PdfSourcePartitionPolicy,
)
from .table_merged import (
    PDF_MERGED_TABLE_STRATEGY,
    PdfMergedTableDetector,
    PdfMergedTableObservation,
)
from .tables import (
    PdfRejectedTableObservation,
    PdfTableDetectionError,
    PdfTableDetectionResult,
    PdfTablePolicy,
)


@dataclass(frozen=True, slots=True)
class PdfBoundaryPartitionedTableObservation(PdfMergedTableObservation):
    source_block_line_partitions: tuple[PdfBlockLinePartition, ...] = ()


class PdfBoundaryPartitionedTableDetector:
    """Retry merged-table candidates using an exact native-line detection view.

    The original source observations are never mutated. A crossing block is
    replaced only in the detector's private view by its table-owned native-line
    prefix. Accepted cell fragments still point to the original span objects and
    the returned partition plan lets the adapter emit the untouched residual
    suffix after the table.
    """

    def __init__(
        self,
        table_policy: PdfTablePolicy,
        *,
        geometry_tolerance_points: float = 0.75,
        maximum_partitioned_blocks_per_table: int = 2,
    ) -> None:
        self._merged_detector = PdfMergedTableDetector(table_policy)
        self._partitioner = PdfSourceBlockLinePartitioner(
            PdfSourcePartitionPolicy(
                geometry_tolerance_points=geometry_tolerance_points,
                maximum_partitioned_blocks_per_table=(
                    maximum_partitioned_blocks_per_table
                ),
            )
        )

    @property
    def partitioner(self) -> PdfSourceBlockLinePartitioner:
        return self._partitioner

    def detect(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        candidate_indexes: frozenset[int],
        reserved_source_orders: frozenset[int] = frozenset(),
    ) -> PdfTableDetectionResult:
        if not blocks or not candidate_indexes:
            return PdfTableDetectionResult()
        candidates = self._candidates(page)
        accepted: list[PdfBoundaryPartitionedTableObservation] = []
        rejected: list[PdfRejectedTableObservation] = []
        consumed_orders = set(reserved_source_orders)

        for table_index in sorted(candidate_indexes):
            if table_index < 0 or table_index >= len(candidates):
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="boundary_partition_candidate_missing",
                    )
                )
                continue
            candidate = candidates[table_index]
            bbox = self._candidate_bbox(candidate)
            if bbox is None:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="boundary_partition_invalid_candidate_geometry",
                    )
                )
                continue
            try:
                partitioned = self._partitioner.partition_for_table(
                    blocks,
                    table_bbox=bbox,
                )
            except PdfSourcePartitionError as exc:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason=exc.reason,
                        bbox=bbox,
                        detail=exc.detail,
                    )
                )
                continue

            retry = self._merged_detector.detect(
                page,
                partitioned.detection_blocks,
                candidate_indexes=frozenset({table_index}),
                reserved_source_orders=frozenset(consumed_orders),
            )
            if not retry.tables:
                if retry.rejected:
                    rejected.extend(retry.rejected)
                else:
                    rejected.append(
                        PdfRejectedTableObservation(
                            table_index=table_index,
                            reason="boundary_partition_retry_produced_no_table",
                            bbox=bbox,
                        )
                    )
                continue
            if len(retry.tables) != 1:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="boundary_partition_retry_count_drift",
                        bbox=bbox,
                        detail=f"accepted_count={len(retry.tables)}",
                    )
                )
                continue
            table = retry.tables[0]
            if table.table_index != table_index or not isinstance(
                table, PdfMergedTableObservation
            ):
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="boundary_partition_retry_identity_drift",
                        bbox=bbox,
                    )
                )
                continue
            if not self._partition_span_cover_is_exact(
                table,
                partitioned.detection_blocks,
                partitioned.partitions,
            ):
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="boundary_partition_table_span_cover_drift",
                        bbox=bbox,
                        row_count=table.row_count,
                        column_count=table.column_count,
                    )
                )
                continue
            overlap = consumed_orders.intersection(table.source_native_orders)
            if overlap:
                rejected.append(
                    PdfRejectedTableObservation(
                        table_index=table_index,
                        reason="boundary_partition_overlapping_source_ownership",
                        bbox=bbox,
                        row_count=table.row_count,
                        column_count=table.column_count,
                        detail=f"native_orders={sorted(overlap)}",
                    )
                )
                continue

            upgraded = PdfBoundaryPartitionedTableObservation(
                table_index=table.table_index,
                bbox=table.bbox,
                displayed_bbox=table.displayed_bbox,
                rows=table.rows,
                source_block_numbers=table.source_block_numbers,
                source_native_orders=table.source_native_orders,
                detection_strategy=PDF_MERGED_TABLE_STRATEGY,
                logical_column_count=table.logical_column_count,
                source_block_line_partitions=partitioned.partitions,
            )
            accepted.append(upgraded)
            consumed_orders.update(upgraded.source_native_orders)

        accepted.sort(key=lambda item: item.source_native_orders[0])
        return PdfTableDetectionResult(
            tables=tuple(accepted),
            rejected=tuple(rejected),
        )

    def _candidates(self, page: Any) -> tuple[Any, ...]:
        try:
            paths = page.get_drawings()
        except Exception as exc:
            raise PdfTableDetectionError(
                f"vector path inspection failed: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            finder = page.find_tables(strategy="lines_strict", paths=paths)
            return tuple(getattr(finder, "tables", ()) or ())
        except Exception as exc:
            raise PdfTableDetectionError(
                f"PyMuPDF find_tables failed: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _candidate_bbox(candidate: Any) -> PdfRect | None:
        raw = getattr(candidate, "bbox", None)
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        if any(not isinstance(value, (int, float)) for value in raw):
            return None
        bbox = tuple(float(value) for value in raw)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            return None
        return bbox[0], bbox[1], bbox[2], bbox[3]

    @staticmethod
    def _partition_span_cover_is_exact(
        table: PdfMergedTableObservation,
        detection_blocks: tuple[PdfBlockObservation, ...],
        partitions: tuple[PdfBlockLinePartition, ...],
    ) -> bool:
        block_by_order = {block.native_order: block for block in detection_blocks}
        owned_span_order_list = [
            fragment.span.native_order
            for row in table.rows
            for cell in row.cells
            for fragment in cell.fragments
        ]
        if len(owned_span_order_list) != len(set(owned_span_order_list)):
            return False
        owned_span_orders = set(owned_span_order_list)

        for partition in partitions:
            block = block_by_order.get(partition.native_order)
            if block is None:
                return False
            expected_list = [
                span.native_order
                for line in block.lines
                if line.native_order in partition.table_line_native_orders
                for span in line.spans
                if span.text
            ]
            actual_list = [
                fragment.span.native_order
                for row in table.rows
                for cell in row.cells
                for fragment in cell.fragments
                if fragment.block_native_order == partition.native_order
            ]
            if len(expected_list) != len(set(expected_list)):
                return False
            if len(actual_list) != len(set(actual_list)):
                return False
            expected = set(expected_list)
            actual = set(actual_list)
            if actual != expected:
                return False
            if not actual.issubset(owned_span_orders):
                return False
        return True
