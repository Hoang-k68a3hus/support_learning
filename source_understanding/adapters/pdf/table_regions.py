from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from .models import PdfBlockObservation, PdfRect
from .table_grid_normalize import (
    PdfNormalizedTableCandidate,
    PdfSegmentedGridNormalizationError,
    PdfSegmentedGridNormalizer,
)
from .table_merged import PdfMergedTableDetector
from .tables import (
    PdfRejectedTableObservation,
    PdfTableDetectionError,
    PdfTableDetectionResult,
    PdfTableDetector,
    PdfTableObservation,
    PdfTablePolicy,
)


PDF_SEGMENTED_STRICT_TABLE_STRATEGY = "lines_strict_segmented"
PDF_SEGMENTED_LINES_TABLE_STRATEGY = "lines_segmented"
PDF_SEGMENTED_STRICT_MERGED_TABLE_STRATEGY = "lines_strict_segmented_merged"
PDF_SEGMENTED_LINES_MERGED_TABLE_STRATEGY = "lines_segmented_merged"

_COMPLEX_REASONS = frozenset({"complex_or_merged_cells", "complex_or_irregular_topology"})


class _RegionPageProxy:
    """Narrow ``Page.find_tables`` to one source-vector cluster."""

    def __init__(
        self,
        page: Any,
        *,
        clip: PdfRect,
        paths: tuple[object, ...],
        strategy: str,
    ) -> None:
        self._page = page
        self._clip = clip
        self._paths = paths
        self._strategy = strategy
        self.last_candidates: tuple[Any, ...] = ()

    @property
    def rect(self) -> Any:
        return self._page.rect

    @property
    def rotation(self) -> int:
        return int(getattr(self._page, "rotation", 0))

    @property
    def rotation_matrix(self) -> Any:
        return self._page.rotation_matrix

    def get_drawings(self) -> list[object]:
        return list(self._paths)

    def find_tables(self, **kwargs: Any) -> Any:
        kwargs["strategy"] = self._strategy
        kwargs["clip"] = self._clip
        kwargs["paths"] = list(self._paths)
        finder = self._page.find_tables(**kwargs)
        self.last_candidates = tuple(getattr(finder, "tables", ()) or ())
        return finder


class _CandidateFinder:
    def __init__(self, candidate: PdfNormalizedTableCandidate) -> None:
        self.tables = (candidate,)


class _CandidatePageProxy:
    """Expose one normalized grid to the existing M2/M2.4 verifier."""

    def __init__(
        self,
        page: _RegionPageProxy,
        *,
        candidate: PdfNormalizedTableCandidate,
        paths: tuple[object, ...],
    ) -> None:
        self._page = page
        self._candidate = candidate
        self._paths = paths

    @property
    def rect(self) -> Any:
        return self._page.rect

    @property
    def rotation(self) -> int:
        return self._page.rotation

    @property
    def rotation_matrix(self) -> Any:
        return self._page.rotation_matrix

    def get_drawings(self) -> list[object]:
        return list(self._paths)

    def find_tables(self, **_kwargs: Any) -> _CandidateFinder:
        return _CandidateFinder(self._candidate)


class PdfSegmentedTableDetector(PdfTableDetector):
    """Precision-first multi-table fallback for disconnected ruled regions.

    Whole-page ``lines_strict`` remains authoritative when it produces a defensible
    table. This fallback only handles pages where that path exposes rectilinear
    evidence but no candidate. Each disconnected drawing cluster is inspected
    independently. Permissive ``lines`` candidates are never trusted directly:
    their logical grid is rebuilt from source vector strokes and then passed back
    through the existing source-span / topology verifier.
    """

    def __init__(
        self,
        policy: PdfTablePolicy | None = None,
        *,
        cluster_tolerance_points: float = 3.0,
        minimum_regions: int = 2,
        maximum_regions: int = 16,
        boundary_support_ratio: float = 0.75,
        vector_alignment_tolerance_points: float = 0.75,
        active_vertical_boundary_fraction: float = 0.40,
        minimum_active_vertical_boundaries: int = 3,
    ) -> None:
        super().__init__(policy)
        if cluster_tolerance_points < 0:
            raise ValueError("cluster_tolerance_points must be nonnegative")
        if minimum_regions < 2:
            raise ValueError("minimum_regions must be at least 2")
        if maximum_regions < minimum_regions:
            raise ValueError("maximum_regions must be >= minimum_regions")
        self.cluster_tolerance_points = float(cluster_tolerance_points)
        self.minimum_regions = minimum_regions
        self.maximum_regions = maximum_regions
        self._merged_detector = PdfMergedTableDetector(self.policy)
        self._grid_normalizer = PdfSegmentedGridNormalizer(
            self.policy,
            boundary_support_ratio=boundary_support_ratio,
            vector_alignment_tolerance_points=vector_alignment_tolerance_points,
            active_vertical_boundary_fraction=active_vertical_boundary_fraction,
            minimum_active_vertical_boundaries=minimum_active_vertical_boundaries,
        )

    def detect(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
        *,
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

        regions = self._cluster_regions(page, paths)
        if len(regions) < self.minimum_regions:
            return self._single_rejection(
                "segmented_insufficient_vector_regions",
                detail=f"regions={len(regions)};minimum={self.minimum_regions}",
            )
        if len(regions) > self.maximum_regions:
            return self._single_rejection(
                "segmented_too_many_vector_regions",
                detail=f"regions={len(regions)};maximum={self.maximum_regions}",
            )
        if self._regions_overlap(regions):
            return self._single_rejection("segmented_vector_regions_overlap")

        accepted: list[PdfTableObservation] = []
        rejected: list[PdfRejectedTableObservation] = []
        consumed_orders = set(reserved_source_orders)
        next_table_index = 0
        for region_index, region in enumerate(regions):
            region_paths = self._paths_for_region(paths, region)
            if not self._has_rectilinear_table_evidence(region_paths):
                continue
            result, strategy = self._detect_region(
                page,
                blocks,
                region=region,
                paths=region_paths,
            )
            if not result.tables:
                rejected.extend(
                    replace(
                        item,
                        table_index=next_table_index + offset,
                        detail=self._detail_with_region(item.detail, region_index),
                    )
                    for offset, item in enumerate(result.rejected)
                )
                next_table_index += max(1, len(result.rejected))
                continue

            for table in result.tables:
                overlap = consumed_orders.intersection(table.source_native_orders)
                if overlap:
                    rejected.append(
                        PdfRejectedTableObservation(
                            table_index=next_table_index,
                            reason="segmented_overlapping_source_ownership",
                            bbox=table.bbox,
                            row_count=table.row_count,
                            column_count=table.column_count,
                            detail=f"region_index={region_index}",
                        )
                    )
                    next_table_index += 1
                    continue
                accepted.append(
                    replace(
                        table,
                        table_index=next_table_index,
                        detection_strategy=strategy,
                    )
                )
                consumed_orders.update(table.source_native_orders)
                next_table_index += 1

            rejected.extend(
                replace(
                    item,
                    table_index=next_table_index + offset,
                    detail=self._detail_with_region(item.detail, region_index),
                )
                for offset, item in enumerate(result.rejected)
            )
            next_table_index += len(result.rejected)

        if len(accepted) < self.minimum_regions:
            return PdfTableDetectionResult(
                rejected=tuple(rejected)
                + (
                    PdfRejectedTableObservation(
                        table_index=next_table_index,
                        reason="segmented_minimum_tables_not_met",
                        detail=json.dumps(
                            {
                                "accepted": len(accepted),
                                "minimum": self.minimum_regions,
                                "regions": len(regions),
                                "accepted_shapes": [
                                    [table.row_count, table.column_count]
                                    for table in accepted
                                ],
                            },
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    ),
                )
            )

        accepted.sort(key=lambda item: item.source_native_orders[0])
        return PdfTableDetectionResult(tuple(accepted), tuple(rejected))

    def _detect_region(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        region: PdfRect,
        paths: tuple[object, ...],
    ) -> tuple[PdfTableDetectionResult, str]:
        strict_proxy = _RegionPageProxy(
            page,
            clip=region,
            paths=paths,
            strategy="lines_strict",
        )
        strict = super().detect(strict_proxy, blocks)
        strict_verified = self._retry_merged_region(strict_proxy, blocks, strict)
        if strict_verified.tables or strict_verified.rejected:
            strategy = (
                PDF_SEGMENTED_STRICT_MERGED_TABLE_STRATEGY
                if strict_verified.tables and not strict.tables
                else PDF_SEGMENTED_STRICT_TABLE_STRATEGY
            )
            return strict_verified, strategy

        lines_proxy = _RegionPageProxy(
            page,
            clip=region,
            paths=paths,
            strategy="lines",
        )
        lines_result = super().detect(lines_proxy, blocks)
        candidates = lines_proxy.last_candidates
        if not candidates:
            return lines_result, PDF_SEGMENTED_LINES_TABLE_STRATEGY
        if len(candidates) != 1:
            return (
                self._single_rejection(
                    "segmented_region_candidate_count_ambiguous",
                    detail=f"candidate_count={len(candidates)}",
                ),
                PDF_SEGMENTED_LINES_TABLE_STRATEGY,
            )

        raw_candidate = candidates[0]
        try:
            normalized = self._grid_normalizer.normalize(raw_candidate, paths)
        except PdfSegmentedGridNormalizationError as exc:
            return (
                self._single_rejection(
                    exc.reason,
                    bbox=self._rect(getattr(raw_candidate, "bbox", None)),
                    row_count=self._positive_int(getattr(raw_candidate, "row_count", None)),
                    column_count=self._positive_int(getattr(raw_candidate, "col_count", None)),
                    detail=exc.detail,
                ),
                PDF_SEGMENTED_LINES_TABLE_STRATEGY,
            )

        return self._verify_normalized_candidate(
            lines_proxy,
            blocks,
            paths=paths,
            candidate=normalized,
        )

    def _verify_normalized_candidate(
        self,
        page: _RegionPageProxy,
        blocks: tuple[PdfBlockObservation, ...],
        *,
        paths: tuple[object, ...],
        candidate: PdfNormalizedTableCandidate,
    ) -> tuple[PdfTableDetectionResult, str]:
        proxy = _CandidatePageProxy(page, candidate=candidate, paths=paths)
        if candidate.has_merged_slots:
            result = self._merged_detector.detect(
                proxy,
                blocks,
                candidate_indexes=frozenset({0}),
            )
            strategy = PDF_SEGMENTED_LINES_MERGED_TABLE_STRATEGY
        else:
            result = PdfTableDetector(self.policy).detect(proxy, blocks)
            strategy = PDF_SEGMENTED_LINES_TABLE_STRATEGY
        if not result.tables:
            return result, strategy
        return (
            PdfTableDetectionResult(
                tables=tuple(
                    replace(table, detection_strategy=strategy)
                    for table in result.tables
                ),
                rejected=result.rejected,
            ),
            strategy,
        )

    def _retry_merged_region(
        self,
        proxy: _RegionPageProxy,
        blocks: tuple[PdfBlockObservation, ...],
        base_result: PdfTableDetectionResult,
    ) -> PdfTableDetectionResult:
        if base_result.tables:
            return base_result
        candidate_indexes = frozenset(
            item.table_index
            for item in base_result.rejected
            if item.reason in _COMPLEX_REASONS
        )
        if not candidate_indexes:
            return base_result
        merged = self._merged_detector.detect(
            proxy,
            blocks,
            candidate_indexes=candidate_indexes,
        )
        if not merged.tables:
            return merged if merged.rejected else base_result
        accepted_indexes = {item.table_index for item in merged.tables}
        rejected = tuple(
            item
            for item in base_result.rejected
            if item.table_index not in accepted_indexes
        ) + tuple(
            item
            for item in merged.rejected
            if item.table_index not in accepted_indexes
        )
        return PdfTableDetectionResult(tables=merged.tables, rejected=rejected)

    def _cluster_regions(self, page: Any, paths: Any) -> tuple[PdfRect, ...]:
        try:
            clustered = page.cluster_drawings(
                drawings=paths,
                x_tolerance=self.cluster_tolerance_points,
                y_tolerance=self.cluster_tolerance_points,
                final_filter=True,
            )
        except Exception as exc:
            raise PdfTableDetectionError(
                f"vector cluster inspection failed: {type(exc).__name__}: {exc}"
            ) from exc
        regions = {
            rect
            for item in tuple(clustered or ())
            if (rect := self._rect(item)) is not None and self._area(rect) > 0
        }
        return tuple(
            sorted(regions, key=lambda item: (item[1], item[0], item[3], item[2]))
        )

    def _paths_for_region(self, paths: Any, region: PdfRect) -> tuple[object, ...]:
        if not isinstance(paths, (list, tuple)):
            return ()
        expanded = self._expand(region, self.cluster_tolerance_points)
        output: list[object] = []
        for path in paths:
            if not isinstance(path, dict):
                continue
            path_rect = self._rect(path.get("rect"))
            if path_rect is None or self._intersects(path_rect, expanded):
                output.append(path)
        return tuple(output)

    def _regions_overlap(self, regions: tuple[PdfRect, ...]) -> bool:
        tolerance = self.cluster_tolerance_points
        for index, left in enumerate(regions):
            for right in regions[index + 1 :]:
                intersection = self._intersection(left, right)
                if intersection is None:
                    continue
                if (intersection[2] - intersection[0]) > tolerance and (
                    intersection[3] - intersection[1]
                ) > tolerance:
                    return True
        return False

    @staticmethod
    def _single_rejection(
        reason: str,
        *,
        bbox: PdfRect | None = None,
        row_count: int | None = None,
        column_count: int | None = None,
        detail: str | None = None,
    ) -> PdfTableDetectionResult:
        return PdfTableDetectionResult(
            rejected=(
                PdfRejectedTableObservation(
                    table_index=0,
                    reason=reason,
                    bbox=bbox,
                    row_count=row_count,
                    column_count=column_count,
                    detail=detail,
                ),
            )
        )

    @staticmethod
    def _detail_with_region(detail: str | None, region_index: int) -> str:
        region_detail = f"region_index={region_index}"
        return region_detail if not detail else f"{region_detail};{detail}"

    @staticmethod
    def _expand(rect: PdfRect, amount: float) -> PdfRect:
        return (
            rect[0] - amount,
            rect[1] - amount,
            rect[2] + amount,
            rect[3] + amount,
        )

    @classmethod
    def _intersects(cls, left: PdfRect, right: PdfRect) -> bool:
        return cls._intersection(left, right) is not None

    @staticmethod
    def _intersection(left: PdfRect, right: PdfRect) -> PdfRect | None:
        x0 = max(left[0], right[0])
        y0 = max(left[1], right[1])
        x1 = min(left[2], right[2])
        y1 = min(left[3], right[3])
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1)
