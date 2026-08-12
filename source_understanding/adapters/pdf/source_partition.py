from __future__ import annotations

from dataclasses import dataclass

from .models import (
    PdfBlockLinePartition,
    PdfBlockObservation,
    PdfLineObservation,
    PdfRect,
)


PDF_SOURCE_LINE_PARTITION_VERSION = "native-line-prefix-v1"


@dataclass(frozen=True, slots=True)
class PdfSourcePartitionPolicy:
    geometry_tolerance_points: float = 0.75
    maximum_partitioned_blocks_per_table: int = 2


class PdfSourcePartitionError(ValueError):
    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PdfSourcePartitionResult:
    detection_blocks: tuple[PdfBlockObservation, ...]
    partitions: tuple[PdfBlockLinePartition, ...]


class PdfSourceBlockLinePartitioner:
    """Build a table-only detection view without splitting source lines/spans.

    The supported M2.6 shape is intentionally narrow: one or more source blocks
    may contain a contiguous table prefix followed by a residual suffix. Every
    nonblank span must be wholly inside or wholly outside the candidate table.
    Mixed/partial geometry, outside-before-table content, and table-in-the-middle
    layouts fail closed.
    """

    def __init__(self, policy: PdfSourcePartitionPolicy | None = None) -> None:
        self.policy = policy if policy is not None else PdfSourcePartitionPolicy()
        if self.policy.geometry_tolerance_points < 0:
            raise ValueError("geometry_tolerance_points must be non-negative")
        if self.policy.maximum_partitioned_blocks_per_table < 1:
            raise ValueError("maximum_partitioned_blocks_per_table must be positive")

    def partition_for_table(
        self,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        table_bbox: PdfRect,
    ) -> PdfSourcePartitionResult:
        detection_blocks: list[PdfBlockObservation] = []
        partitions: list[PdfBlockLinePartition] = []
        for block in blocks:
            relation = self._block_relation(block, table_bbox=table_bbox)
            if relation == "inside" or relation == "outside":
                detection_blocks.append(block)
                continue
            if relation != "crossing":
                raise PdfSourcePartitionError(
                    "boundary_partition_ambiguous_block_geometry",
                    detail=f"block_native_order={block.native_order}",
                )
            partition, table_fragment = self._partition_crossing_block(
                block,
                table_bbox=table_bbox,
            )
            partitions.append(partition)
            if len(partitions) > self.policy.maximum_partitioned_blocks_per_table:
                raise PdfSourcePartitionError(
                    "boundary_partition_too_many_blocks",
                    detail=(
                        "partitioned_blocks="
                        f"{len(partitions)};limit="
                        f"{self.policy.maximum_partitioned_blocks_per_table}"
                    ),
                )
            detection_blocks.append(table_fragment)

        if not partitions:
            raise PdfSourcePartitionError("boundary_partition_not_applicable")
        return PdfSourcePartitionResult(
            detection_blocks=tuple(detection_blocks),
            partitions=tuple(partitions),
        )

    def residual_fragment(
        self,
        block: PdfBlockObservation,
        partition: PdfBlockLinePartition,
    ) -> PdfBlockObservation:
        self._validate_partition_identity(block, partition)
        self._validate_exact_line_cover(block, partition)
        line_by_order = {line.native_order: line for line in block.lines}
        if len(line_by_order) != len(block.lines):
            raise PdfSourcePartitionError("boundary_partition_duplicate_line_order")
        try:
            residual_lines = tuple(
                line_by_order[order] for order in partition.residual_line_native_orders
            )
        except KeyError as exc:
            raise PdfSourcePartitionError(
                "boundary_partition_residual_line_missing",
                detail=f"line_native_order={exc.args[0]}",
            ) from exc
        if not residual_lines:
            raise PdfSourcePartitionError("boundary_partition_empty_residual")
        return PdfBlockObservation(
            page_number=block.page_number,
            native_block_number=block.native_block_number,
            native_order=block.native_order,
            bbox=self._union(tuple(line.bbox for line in residual_lines)),
            displayed_bbox=self._union(
                tuple(line.displayed_bbox for line in residual_lines)
            ),
            lines=residual_lines,
        )

    def _partition_crossing_block(
        self,
        block: PdfBlockObservation,
        *,
        table_bbox: PdfRect,
    ) -> tuple[PdfBlockLinePartition, PdfBlockObservation]:
        if not block.lines:
            raise PdfSourcePartitionError("boundary_partition_empty_block")

        line_relations = tuple(
            self._line_relation(line, table_bbox=table_bbox) for line in block.lines
        )
        if line_relations[0] != "inside":
            raise PdfSourcePartitionError(
                "boundary_partition_requires_table_prefix",
                detail=f"block_native_order={block.native_order}",
            )

        last_inside = -1
        for index, relation in enumerate(line_relations):
            if relation == "inside":
                if last_inside != index - 1:
                    raise PdfSourcePartitionError(
                        "boundary_partition_noncontiguous_table_prefix",
                        detail=f"block_native_order={block.native_order}",
                    )
                last_inside = index
                continue
            break
        if last_inside < 0 or last_inside == len(block.lines) - 1:
            raise PdfSourcePartitionError("boundary_partition_missing_residual_suffix")

        residual_relations = line_relations[last_inside + 1 :]
        if any(relation == "inside" for relation in residual_relations):
            raise PdfSourcePartitionError(
                "boundary_partition_table_reappears_after_residual",
                detail=f"block_native_order={block.native_order}",
            )
        if any(relation == "ambiguous" for relation in residual_relations):
            raise PdfSourcePartitionError(
                "boundary_partition_ambiguous_residual_geometry",
                detail=f"block_native_order={block.native_order}",
            )
        if not any(relation == "outside" for relation in residual_relations):
            raise PdfSourcePartitionError("boundary_partition_residual_has_no_nonblank_text")

        table_lines = block.lines[: last_inside + 1]
        residual_lines = block.lines[last_inside + 1 :]
        if any(
            self._line_relation(line, table_bbox=table_bbox) != "inside"
            for line in table_lines
        ):
            raise PdfSourcePartitionError(
                "boundary_partition_table_prefix_contains_blank_line"
            )

        table_bottom = max(line.bbox[3] for line in table_lines)
        residual_nonblank_tops = [
            line.bbox[1]
            for line, relation in zip(residual_lines, residual_relations, strict=True)
            if relation == "outside"
        ]
        if not residual_nonblank_tops:
            raise PdfSourcePartitionError("boundary_partition_residual_has_no_nonblank_text")
        first_residual_top = min(residual_nonblank_tops)
        tolerance = self.policy.geometry_tolerance_points
        if first_residual_top < table_bottom - tolerance:
            raise PdfSourcePartitionError(
                "boundary_partition_visual_order_overlap",
                detail=(
                    f"table_bottom={table_bottom};"
                    f"residual_top={first_residual_top};tolerance={tolerance}"
                ),
            )

        partition = PdfBlockLinePartition(
            page_number=block.page_number,
            native_block_number=block.native_block_number,
            native_order=block.native_order,
            original_bbox=block.bbox,
            original_displayed_bbox=block.displayed_bbox,
            table_line_native_orders=tuple(line.native_order for line in table_lines),
            residual_line_native_orders=tuple(line.native_order for line in residual_lines),
        )
        table_fragment = PdfBlockObservation(
            page_number=block.page_number,
            native_block_number=block.native_block_number,
            native_order=block.native_order,
            bbox=self._union(tuple(line.bbox for line in table_lines)),
            displayed_bbox=self._union(
                tuple(line.displayed_bbox for line in table_lines)
            ),
            lines=table_lines,
        )
        self._validate_exact_line_cover(block, partition)
        return partition, table_fragment

    def _block_relation(
        self,
        block: PdfBlockObservation,
        *,
        table_bbox: PdfRect,
    ) -> str:
        relations = {
            relation
            for line in block.lines
            if (relation := self._line_relation(line, table_bbox=table_bbox)) != "blank"
        }
        if not relations:
            return "outside"
        if "ambiguous" in relations:
            return "ambiguous"
        if relations == {"inside"}:
            return "inside"
        if relations == {"outside"}:
            return "outside"
        if relations == {"inside", "outside"}:
            return "crossing"
        return "ambiguous"

    def _line_relation(
        self,
        line: PdfLineObservation,
        *,
        table_bbox: PdfRect,
    ) -> str:
        nonblank = tuple(span for span in line.spans if span.text.strip())
        if not nonblank:
            return "blank"
        relations = {self._span_relation(span.bbox, table_bbox) for span in nonblank}
        if "ambiguous" in relations or len(relations) != 1:
            return "ambiguous"
        return next(iter(relations))

    def _span_relation(self, span: PdfRect, table: PdfRect) -> str:
        tolerance = self.policy.geometry_tolerance_points
        if self._contains_rect(
            table,
            span,
            tolerance=tolerance,
        ) and self._contains_point(table, self._center(span)):
            return "inside"
        intersection = self._intersection(span, table)
        if self._area(intersection) <= 0.0:
            return "outside"
        return "ambiguous"

    @staticmethod
    def _contains_rect(outer: PdfRect, inner: PdfRect, *, tolerance: float) -> bool:
        return (
            inner[0] >= outer[0] - tolerance
            and inner[1] >= outer[1] - tolerance
            and inner[2] <= outer[2] + tolerance
            and inner[3] <= outer[3] + tolerance
        )

    @staticmethod
    def _center(rect: PdfRect) -> tuple[float, float]:
        return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)

    @staticmethod
    def _contains_point(rect: PdfRect, point: tuple[float, float]) -> bool:
        return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]

    @staticmethod
    def _intersection(left: PdfRect, right: PdfRect) -> PdfRect:
        x0 = max(left[0], right[0])
        y0 = max(left[1], right[1])
        x1 = min(left[2], right[2])
        y1 = min(left[3], right[3])
        return (x0, y0, max(x0, x1), max(y0, y1))

    @staticmethod
    def _area(rect: PdfRect) -> float:
        return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])

    @staticmethod
    def _union(rects: tuple[PdfRect, ...]) -> PdfRect:
        if not rects:
            raise PdfSourcePartitionError("boundary_partition_empty_geometry")
        return (
            min(rect[0] for rect in rects),
            min(rect[1] for rect in rects),
            max(rect[2] for rect in rects),
            max(rect[3] for rect in rects),
        )

    @staticmethod
    def _validate_partition_identity(
        block: PdfBlockObservation,
        partition: PdfBlockLinePartition,
    ) -> None:
        if (
            partition.page_number != block.page_number
            or partition.native_block_number != block.native_block_number
            or partition.native_order != block.native_order
            or partition.original_bbox != block.bbox
            or partition.original_displayed_bbox != block.displayed_bbox
        ):
            raise PdfSourcePartitionError("boundary_partition_block_identity_drift")

    @staticmethod
    def _validate_exact_line_cover(
        block: PdfBlockObservation,
        partition: PdfBlockLinePartition,
    ) -> None:
        source = tuple(line.native_order for line in block.lines)
        table = partition.table_line_native_orders
        residual = partition.residual_line_native_orders
        if set(table).intersection(residual):
            raise PdfSourcePartitionError("boundary_partition_line_overlap")
        if table + residual != source:
            raise PdfSourcePartitionError("boundary_partition_line_cover_drift")
        if len(source) != len(set(source)):
            raise PdfSourcePartitionError("boundary_partition_duplicate_line_order")
        if not table or not residual:
            raise PdfSourcePartitionError("boundary_partition_empty_side")
