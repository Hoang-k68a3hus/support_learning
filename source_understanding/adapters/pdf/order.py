from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .models import PdfBlockObservation


@dataclass(frozen=True, slots=True)
class PdfReadingOrderPolicy:
    full_width_ratio: float = 0.68
    minimum_column_gap_ratio: float = 0.025
    minimum_vertical_overlap_ratio: float = 0.20
    column_join_overlap_ratio: float = 0.35
    maximum_separator_vertical_overlap_ratio: float = 0.10
    aligned_row_overlap_ratio: float = 0.50
    aligned_row_gap_ratio: float = 0.01
    aligned_layout_many_rows: int = 6
    aligned_layout_multi_cell_rows: int = 3


class PdfReadingOrderResolver:
    """Deterministic geometry-first reading order for native text blocks.

    M1 deliberately avoids semantic labels. Wide blocks are treated as vertical
    separators only when they do not materially overlap neighboring blocks. In
    each remaining band the resolver searches for a defensible set of coexisting
    visual columns. Isolated blocks above/below that cohort (for example a short
    centered title) remain in geometric order.

    A band without defensible column evidence keeps the backend's native order.
    This is intentionally conservative: mathematical displays, BNF productions,
    diagrams, and other aligned fragments can have slightly different top
    coordinates even though their source order is already the only auditable
    sequence. Reordering such ambiguous fragments by top-left geometry would turn
    a weak layout guess into a false source fact.

    Repeated row-aligned geometry is also treated conservatively. It often comes
    from tables, forms, equation arrays, or diagrams rather than newspaper-style
    prose columns. M1 does not infer those structures, so the page keeps native
    block order and lets the adapter surface an explicit structural-loss
    diagnostic instead of flattening a grid column-by-column.
    """

    def __init__(self, policy: PdfReadingOrderPolicy | None = None) -> None:
        self.policy = policy if policy is not None else PdfReadingOrderPolicy()

    def resolve(
        self,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page_width: float,
    ) -> tuple[PdfBlockObservation, ...]:
        if len(blocks) <= 1:
            return blocks
        if page_width <= 0:
            raise ValueError("page_width must be positive for PDF reading order")
        if self.looks_aligned_layout(blocks, page_width=page_width):
            return blocks

        spanning = tuple(
            block
            for block in blocks
            if self._is_vertical_separator(block, blocks, page_width=page_width)
        )
        if not spanning:
            return self._order_band(blocks, page_width=page_width)

        spanning = tuple(sorted(spanning, key=self._top_left_key))
        remaining = list(blocks)
        output: list[PdfBlockObservation] = []
        for separator in spanning:
            if separator not in remaining:
                continue
            before = [
                block
                for block in remaining
                if block is not separator
                and self._vertical_center(block) < separator.displayed_bbox[1]
            ]
            output.extend(self._order_band(tuple(before), page_width=page_width))
            consumed = {id(block) for block in before}
            remaining = [
                block
                for block in remaining
                if id(block) not in consumed and block is not separator
            ]
            output.append(separator)
        output.extend(self._order_band(tuple(remaining), page_width=page_width))
        return tuple(output)

    def looks_aligned_layout(
        self,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page_width: float,
    ) -> bool:
        """Return True only for strong repeated row/grid geometry.

        This is not a TABLE classifier. It is a fail-closed signal that native
        block geometry is more consistent with a grid/form/equation array than
        with independent prose columns, so M1 should not reorder the page.
        """

        if len(blocks) < 4:
            return False
        if page_width <= 0:
            raise ValueError("page_width must be positive for PDF aligned-layout checks")

        two_cell_rows = self._aligned_rows(
            blocks,
            page_width=page_width,
            minimum_cells=2,
        )
        three_cell_rows = self._aligned_rows(
            blocks,
            page_width=page_width,
            minimum_cells=3,
        )
        maximum_cells = max((item[1] for item in two_cell_rows), default=0)
        return (
            maximum_cells >= 4
            or len(three_cell_rows) >= self.policy.aligned_layout_multi_cell_rows
            or len(two_cell_rows) >= self.policy.aligned_layout_many_rows
        )

    def _aligned_rows(
        self,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page_width: float,
        minimum_cells: int,
    ) -> tuple[tuple[float, int], ...]:
        minimum_gap = page_width * self.policy.aligned_row_gap_ratio
        heights = [
            max(0.0, block.displayed_bbox[3] - block.displayed_bbox[1])
            for block in blocks
        ]
        positive_heights = [item for item in heights if item > 0]
        merge_tolerance = max(
            1.0,
            median(positive_heights) * 0.35 if positive_heights else 1.0,
        )

        candidates: list[tuple[float, int]] = []
        for seed in blocks:
            row_candidates = [
                block
                for block in blocks
                if self._block_vertical_overlap_ratio(seed, block)
                >= self.policy.aligned_row_overlap_ratio
            ]
            selected: list[PdfBlockObservation] = []
            for block in sorted(row_candidates, key=self._left_top_key):
                if not selected:
                    selected.append(block)
                    continue
                if block.displayed_bbox[0] - selected[-1].displayed_bbox[2] >= minimum_gap:
                    selected.append(block)
            if len(selected) < minimum_cells:
                continue
            row_center = sum(self._vertical_center(block) for block in selected) / len(
                selected
            )
            candidates.append((row_center, len(selected)))

        rows: list[tuple[float, int]] = []
        for row_center, cell_count in sorted(candidates):
            if not rows or row_center - rows[-1][0] > merge_tolerance:
                rows.append((row_center, cell_count))
                continue
            previous_center, previous_count = rows[-1]
            if cell_count > previous_count:
                rows[-1] = (previous_center, cell_count)
        return tuple(rows)

    def _is_vertical_separator(
        self,
        block: PdfBlockObservation,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page_width: float,
    ) -> bool:
        if self._width(block) / page_width < self.policy.full_width_ratio:
            return False
        maximum_overlap = max(
            (
                self._block_vertical_overlap_ratio(block, other)
                for other in blocks
                if other is not block
            ),
            default=0.0,
        )
        return maximum_overlap <= self.policy.maximum_separator_vertical_overlap_ratio

    def _order_band(
        self,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        page_width: float,
    ) -> tuple[PdfBlockObservation, ...]:
        if len(blocks) <= 1:
            return blocks

        columns = self._cluster_columns(blocks)
        cohort = self._select_column_cohort(columns, page_width=page_width)
        if cohort is None:
            return blocks

        selected_blocks = [block for index in cohort for block in columns[index]]
        selected_ids = {id(block) for block in selected_blocks}
        outliers = [block for block in blocks if id(block) not in selected_ids]
        cohort_y0 = min(block.displayed_bbox[1] for block in selected_blocks)
        cohort_y1 = max(block.displayed_bbox[3] for block in selected_blocks)

        before: list[PdfBlockObservation] = []
        after: list[PdfBlockObservation] = []
        for block in outliers:
            center = self._vertical_center(block)
            if center < cohort_y0:
                before.append(block)
            elif center > cohort_y1:
                after.append(block)
            else:
                return blocks

        output: list[PdfBlockObservation] = []
        output.extend(sorted(before, key=self._top_left_key))
        for index in sorted(
            cohort,
            key=lambda item: min(block.displayed_bbox[0] for block in columns[item]),
        ):
            output.extend(sorted(columns[index], key=self._top_left_key))
        output.extend(sorted(after, key=self._top_left_key))
        return tuple(output)

    def _cluster_columns(
        self,
        blocks: tuple[PdfBlockObservation, ...],
    ) -> list[list[PdfBlockObservation]]:
        columns: list[list[PdfBlockObservation]] = []
        for block in sorted(blocks, key=self._left_top_key):
            best_index: int | None = None
            best_overlap = 0.0
            for index, column in enumerate(columns):
                overlap = self._horizontal_overlap_ratio(block, column)
                if overlap >= self.policy.column_join_overlap_ratio and overlap > best_overlap:
                    best_index = index
                    best_overlap = overlap
            if best_index is None:
                columns.append([block])
            else:
                columns[best_index].append(block)
        columns.sort(key=lambda column: min(item.displayed_bbox[0] for item in column))
        return columns

    def _select_column_cohort(
        self,
        columns: list[list[PdfBlockObservation]],
        *,
        page_width: float,
    ) -> tuple[int, ...] | None:
        if len(columns) < 2:
            return None
        min_gap = page_width * self.policy.minimum_column_gap_ratio
        candidates: list[tuple[tuple[int, float], int, int]] = []
        for left_index in range(len(columns)):
            for right_index in range(left_index + 1, len(columns)):
                left = columns[left_index]
                right = columns[right_index]
                if self._column_gap(left, right) < min_gap:
                    continue
                overlap = self._column_vertical_overlap_ratio(left, right)
                if overlap < self.policy.minimum_vertical_overlap_ratio:
                    continue
                score = (len(left) + len(right), overlap)
                candidates.append((score, left_index, right_index))
        if not candidates:
            return None

        _score, left_index, right_index = max(candidates, key=lambda item: item[0])
        selected = {left_index, right_index}
        common_y0, common_y1 = self._common_vertical_interval(
            [columns[left_index], columns[right_index]]
        )
        if common_y1 <= common_y0:
            return tuple(sorted(selected))

        for index, column in enumerate(columns):
            if index in selected:
                continue
            if not all(
                self._separated_columns(column, columns[other], min_gap=min_gap)
                for other in selected
            ):
                continue
            cy0, cy1 = self._column_vertical_range(column)
            intersection = max(0.0, min(cy1, common_y1) - max(cy0, common_y0))
            denominator = min(max(0.0, cy1 - cy0), common_y1 - common_y0)
            if (
                denominator > 0
                and intersection / denominator
                >= self.policy.minimum_vertical_overlap_ratio
            ):
                selected.add(index)
                common_y0 = max(common_y0, cy0)
                common_y1 = min(common_y1, cy1)

        return tuple(sorted(selected))

    @staticmethod
    def _common_vertical_interval(
        columns: list[list[PdfBlockObservation]],
    ) -> tuple[float, float]:
        ranges = [PdfReadingOrderResolver._column_vertical_range(column) for column in columns]
        return max(item[0] for item in ranges), min(item[1] for item in ranges)

    @staticmethod
    def _column_vertical_range(
        column: list[PdfBlockObservation],
    ) -> tuple[float, float]:
        return (
            min(block.displayed_bbox[1] for block in column),
            max(block.displayed_bbox[3] for block in column),
        )

    @classmethod
    def _column_vertical_overlap_ratio(
        cls,
        left: list[PdfBlockObservation],
        right: list[PdfBlockObservation],
    ) -> float:
        left_y0, left_y1 = cls._column_vertical_range(left)
        right_y0, right_y1 = cls._column_vertical_range(right)
        intersection = max(0.0, min(left_y1, right_y1) - max(left_y0, right_y0))
        denominator = min(max(0.0, left_y1 - left_y0), max(0.0, right_y1 - right_y0))
        return intersection / denominator if denominator > 0 else 0.0

    @staticmethod
    def _block_vertical_overlap_ratio(
        left: PdfBlockObservation,
        right: PdfBlockObservation,
    ) -> float:
        left_y0, left_y1 = left.displayed_bbox[1], left.displayed_bbox[3]
        right_y0, right_y1 = right.displayed_bbox[1], right.displayed_bbox[3]
        intersection = max(0.0, min(left_y1, right_y1) - max(left_y0, right_y0))
        denominator = min(max(0.0, left_y1 - left_y0), max(0.0, right_y1 - right_y0))
        return intersection / denominator if denominator > 0 else 0.0

    @staticmethod
    def _column_gap(
        left: list[PdfBlockObservation],
        right: list[PdfBlockObservation],
    ) -> float:
        left_x1 = max(block.displayed_bbox[2] for block in left)
        right_x0 = min(block.displayed_bbox[0] for block in right)
        if right_x0 >= left_x1:
            return right_x0 - left_x1
        right_x1 = max(block.displayed_bbox[2] for block in right)
        left_x0 = min(block.displayed_bbox[0] for block in left)
        if left_x0 >= right_x1:
            return left_x0 - right_x1
        return -1.0

    @classmethod
    def _separated_columns(
        cls,
        left: list[PdfBlockObservation],
        right: list[PdfBlockObservation],
        *,
        min_gap: float,
    ) -> bool:
        return cls._column_gap(left, right) >= min_gap

    @staticmethod
    def _horizontal_overlap_ratio(
        block: PdfBlockObservation,
        column: list[PdfBlockObservation],
    ) -> float:
        bx0, _, bx1, _ = block.displayed_bbox
        cx0 = min(item.displayed_bbox[0] for item in column)
        cx1 = max(item.displayed_bbox[2] for item in column)
        intersection = max(0.0, min(bx1, cx1) - max(bx0, cx0))
        denominator = min(max(0.0, bx1 - bx0), max(0.0, cx1 - cx0))
        return intersection / denominator if denominator > 0 else 0.0

    @staticmethod
    def _width(block: PdfBlockObservation) -> float:
        return max(0.0, block.displayed_bbox[2] - block.displayed_bbox[0])

    @staticmethod
    def _vertical_center(block: PdfBlockObservation) -> float:
        return (block.displayed_bbox[1] + block.displayed_bbox[3]) / 2.0

    @staticmethod
    def _top_left_key(block: PdfBlockObservation) -> tuple[float, float, int]:
        return (block.displayed_bbox[1], block.displayed_bbox[0], block.native_order)

    @staticmethod
    def _left_top_key(block: PdfBlockObservation) -> tuple[float, float, int]:
        return (block.displayed_bbox[0], block.displayed_bbox[1], block.native_order)
