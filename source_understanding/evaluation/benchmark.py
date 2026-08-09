from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from .metrics import AccuracyScore, PRFScore, accuracy_score, prf_counts
from .report import (
    AggregateMetric,
    BenchmarkEvaluationReport,
    BenchmarkPooledMetrics,
    DocumentEvaluationReport,
)
from .schemas import BenchmarkManifest


class BenchmarkEvaluator:
    """Aggregate document reports without hiding document-level variation."""

    def aggregate(
        self,
        manifest: BenchmarkManifest,
        reports: Sequence[DocumentEvaluationReport],
    ) -> BenchmarkEvaluationReport:
        by_id = {item.document_id: item for item in reports}
        if len(by_id) != len(reports):
            raise ValueError("benchmark reports must have unique document ids")
        expected_ids = [item.document_id for item in manifest.cases]
        missing = [item for item in expected_ids if item not in by_id]
        extra = sorted(set(by_id) - set(expected_ids))
        if missing or extra:
            raise ValueError(
                f"benchmark report identity mismatch: missing={missing}, extra={extra}"
            )

        ordered = tuple(by_id[item] for item in expected_ids)
        aggregate_specs = {
            "element_detection_f1": [
                item.metrics.element_detection.f1 for item in ordered
            ],
            "element_type_macro_f1": [
                item.metrics.element_type_macro_f1 for item in ordered
            ],
            "heading_detection_f1": [
                item.metrics.heading_detection.f1 for item in ordered
            ],
            "heading_level_accuracy": [
                item.metrics.heading_level_accuracy.accuracy for item in ordered
            ],
            "hierarchy_parent_f1": [
                item.metrics.hierarchy_parent_edges.f1 for item in ordered
            ],
            "logical_unit_pairwise_f1": [
                item.metrics.logical_unit_pairwise.f1 for item in ordered
            ],
            "integrity_exact_match_f1": [
                item.metrics.integrity_exact_match.f1 for item in ordered
            ],
            "region_boundary_f1": [
                item.metrics.region_boundary.f1 for item in ordered
            ],
            "region_category_accuracy": [
                item.metrics.region_category_accuracy.accuracy for item in ordered
            ],
            "structural_relation_f1": [
                item.metrics.structural_relations.f1 for item in ordered
            ],
            "source_text_preservation_ratio": [
                item.metrics.source_text_preservation_ratio for item in ordered
            ],
        }
        aggregates: list[AggregateMetric] = []
        for name, raw_values in aggregate_specs.items():
            values = [value for value in raw_values if value is not None]
            aggregates.append(
                AggregateMetric(
                    name=name,
                    mean=sum(values) / len(values) if values else None,
                    minimum=min(values) if values else None,
                    maximum=max(values) if values else None,
                    document_count=len(values),
                )
            )

        total_gold_chars = sum(
            item.metrics.source_text_gold_char_count for item in ordered
        )
        total_preserved_chars = sum(
            item.metrics.source_text_preserved_char_count for item in ordered
        )
        pooled = BenchmarkPooledMetrics(
            element_detection=self._sum_prf(
                item.metrics.element_detection for item in ordered
            ),
            element_type_accuracy=self._sum_accuracy(
                item.metrics.element_type_accuracy for item in ordered
            ),
            heading_detection=self._sum_prf(
                item.metrics.heading_detection for item in ordered
            ),
            heading_level_accuracy=self._sum_accuracy(
                item.metrics.heading_level_accuracy for item in ordered
            ),
            hierarchy_parent_edges=self._sum_prf(
                item.metrics.hierarchy_parent_edges for item in ordered
            ),
            logical_unit_pairwise=self._sum_prf(
                item.metrics.logical_unit_pairwise for item in ordered
            ),
            integrity_exact_match=self._sum_prf(
                item.metrics.integrity_exact_match for item in ordered
            ),
            region_boundary=self._sum_prf(
                item.metrics.region_boundary for item in ordered
            ),
            region_category_accuracy=self._sum_accuracy(
                item.metrics.region_category_accuracy for item in ordered
            ),
            structural_relations=self._sum_prf(
                item.metrics.structural_relations for item in ordered
            ),
            source_text_exact=self._sum_accuracy(
                item.metrics.source_text_exact for item in ordered
            ),
            source_text_preservation_ratio=(
                total_preserved_chars / total_gold_chars if total_gold_chars else None
            ),
            expected_diagnostic_recall=self._sum_accuracy(
                item.metrics.expected_diagnostic_recall for item in ordered
            ),
            unexpected_structural_diagnostic_count=sum(
                item.metrics.unexpected_structural_diagnostic_count for item in ordered
            ),
        )

        error_counts = Counter(
            error.type.value for report in ordered for error in report.errors
        )
        return BenchmarkEvaluationReport(
            benchmark_name=manifest.name,
            benchmark_version=manifest.benchmark_version,
            document_reports=ordered,
            pooled=pooled,
            aggregate=tuple(aggregates),
            total_error_count=sum(error_counts.values()),
            error_type_counts=dict(sorted(error_counts.items())),
        )

    @staticmethod
    def _sum_prf(scores: Iterable[PRFScore]) -> PRFScore:
        snapshot = tuple(scores)
        return prf_counts(
            sum(item.true_positive for item in snapshot),
            sum(item.false_positive for item in snapshot),
            sum(item.false_negative for item in snapshot),
        )

    @staticmethod
    def _sum_accuracy(scores: Iterable[AccuracyScore]) -> AccuracyScore:
        snapshot = tuple(scores)
        return accuracy_score(
            sum(item.correct for item in snapshot),
            sum(item.total for item in snapshot),
        )
