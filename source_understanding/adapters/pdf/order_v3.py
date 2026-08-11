from __future__ import annotations

from dataclasses import dataclass

from .models import PdfBlockObservation
from .order import PdfReadingOrderPolicy, PdfReadingOrderResolver


@dataclass(frozen=True, slots=True)
class PdfReadingOrderPolicyV3(PdfReadingOrderPolicy):
    """Additional evidence required before treating geometry as prose columns."""

    minimum_column_width_balance_ratio: float = 0.35
    minimum_column_block_count: int = 2


class PdfReadingOrderResolverV3(PdfReadingOrderResolver):
    """V3 reading order with conservative math/textbook guards.

    Narrow equation-number lanes and asymmetric mathematical fragments are not
    sufficient column evidence. Wide separators are only active when the blocks
    remaining after removing them independently establish a defensible column
    cohort. Otherwise the auditable native source sequence wins.
    """

    policy: PdfReadingOrderPolicyV3

    def __init__(self, policy: PdfReadingOrderPolicyV3 | None = None) -> None:
        super().__init__(policy if policy is not None else PdfReadingOrderPolicyV3())

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
        if spanning:
            remaining = tuple(block for block in blocks if block not in spanning)
            cohort = self._select_column_cohort(
                self._cluster_columns(remaining),
                page_width=page_width,
            )
            if cohort is None:
                spanning = ()

        if not spanning:
            return self._order_band(blocks, page_width=page_width)

        spanning = tuple(sorted(spanning, key=self._top_left_key))
        remaining_blocks = list(blocks)
        output: list[PdfBlockObservation] = []
        for separator in spanning:
            if separator not in remaining_blocks:
                continue
            before = [
                block
                for block in remaining_blocks
                if block is not separator
                and self._vertical_center(block) < separator.displayed_bbox[1]
            ]
            output.extend(self._order_band(tuple(before), page_width=page_width))
            consumed = {id(block) for block in before}
            remaining_blocks = [
                block
                for block in remaining_blocks
                if id(block) not in consumed and block is not separator
            ]
            output.append(separator)
        output.extend(
            self._order_band(tuple(remaining_blocks), page_width=page_width)
        )
        return tuple(output)

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
                if (
                    len(left) < self.policy.minimum_column_block_count
                    or len(right) < self.policy.minimum_column_block_count
                ):
                    continue
                if self._column_gap(left, right) < min_gap:
                    continue
                overlap = self._column_vertical_overlap_ratio(left, right)
                if overlap < self.policy.minimum_vertical_overlap_ratio:
                    continue
                if (
                    self._column_width_balance(left, right)
                    < self.policy.minimum_column_width_balance_ratio
                ):
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

        minimum_reference_width = min(
            self._column_width(columns[left_index]),
            self._column_width(columns[right_index]),
        )
        maximum_reference_width = max(
            self._column_width(columns[left_index]),
            self._column_width(columns[right_index]),
        )

        for index, column in enumerate(columns):
            if index in selected:
                continue
            if len(column) < self.policy.minimum_column_block_count:
                continue
            if not all(
                self._separated_columns(
                    column,
                    columns[other],
                    min_gap=min_gap,
                )
                for other in selected
            ):
                continue

            width = self._column_width(column)
            width_balance = (
                min(width, minimum_reference_width)
                / max(width, maximum_reference_width)
                if max(width, maximum_reference_width) > 0
                else 0.0
            )
            if width_balance < self.policy.minimum_column_width_balance_ratio:
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
                minimum_reference_width = min(minimum_reference_width, width)
                maximum_reference_width = max(maximum_reference_width, width)

        return tuple(sorted(selected))

    @staticmethod
    def _column_width(column: list[PdfBlockObservation]) -> float:
        return max(block.displayed_bbox[2] for block in column) - min(
            block.displayed_bbox[0] for block in column
        )

    @classmethod
    def _column_width_balance(
        cls,
        left: list[PdfBlockObservation],
        right: list[PdfBlockObservation],
    ) -> float:
        left_width = cls._column_width(left)
        right_width = cls._column_width(right)
        denominator = max(left_width, right_width)
        return min(left_width, right_width) / denominator if denominator > 0 else 0.0
