from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from source_understanding.adapters.docx import DocxAdapter
from source_understanding.adapters.runner import SourceAdapterRunner
from source_understanding.evaluation import (
    BenchmarkEvaluator,
    DocumentStructureEvaluator,
    load_materialized_benchmark,
)

from benchmarks.docx_structure_v0_1.adjudicated_pilot import materialize


FIXED_EVALUATION_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)


def run_pilot() -> object:
    """Materialize, reload, and evaluate the deterministic pilot benchmark.

    Reloading the adjudicated materialized bundle is intentional: it exercises
    the same strict path/hash/identity validation that will be used for future
    real-world benchmark bundles instead of evaluating only in-memory objects.
    """

    with tempfile.TemporaryDirectory(prefix="docx-structure-v0-1-") as tmp:
        root = Path(tmp)
        materialize(root)
        loaded = load_materialized_benchmark(root)
        runner = SourceAdapterRunner()
        evaluator = DocumentStructureEvaluator()
        reports = []
        for loaded_case in loaded.cases:
            payload = loaded_case.source_path.read_bytes()
            result = runner.understand_bytes(
                payload,
                adapter=DocxAdapter(),
                document_id=loaded_case.case.document_id,
                source_name=loaded_case.source_path.name,
                processed_at=FIXED_EVALUATION_TIME,
            )
            reports.append(
                evaluator.evaluate(
                    loaded_case.gold,
                    result.understanding.document,
                    adapter_diagnostics=result.adapter_result.diagnostics,
                    structural_ready=(
                        result.understanding.completion_report.structural_ready
                    ),
                )
            )
        return BenchmarkEvaluator().aggregate(loaded.manifest, reports)


def _prf_summary(score: object) -> dict[str, object]:
    return {
        "precision": score.precision,
        "recall": score.recall,
        "f1": score.f1,
        "tp": score.true_positive,
        "fp": score.false_positive,
        "fn": score.false_negative,
    }


def _accuracy_summary(score: object) -> dict[str, object]:
    return {
        "accuracy": score.accuracy,
        "correct": score.correct,
        "total": score.total,
    }


def _error_summary(error: object) -> dict[str, object]:
    return {
        "type": error.type.value,
        "message": error.message,
        "gold_ids": list(error.gold_ids),
        "predicted_ids": list(error.predicted_ids),
        "metadata": dict(error.metadata),
    }


def summary_dict(report: object) -> dict[str, object]:
    aggregate = {
        item.name: {
            "mean": item.mean,
            "min": item.minimum,
            "max": item.maximum,
            "documents": item.document_count,
        }
        for item in report.aggregate
    }
    pooled = report.pooled
    return {
        "benchmark": report.benchmark_name,
        "version": report.benchmark_version,
        "documents": len(report.document_reports),
        "pooled": {
            "element_detection": _prf_summary(pooled.element_detection),
            "element_type_accuracy": _accuracy_summary(
                pooled.element_type_accuracy
            ),
            "heading_detection": _prf_summary(pooled.heading_detection),
            "heading_level_accuracy": _accuracy_summary(
                pooled.heading_level_accuracy
            ),
            "hierarchy_parent_edges": _prf_summary(
                pooled.hierarchy_parent_edges
            ),
            "logical_unit_pairwise": _prf_summary(
                pooled.logical_unit_pairwise
            ),
            "integrity_exact_match": _prf_summary(
                pooled.integrity_exact_match
            ),
            "region_boundary": _prf_summary(pooled.region_boundary),
            "region_category_accuracy": _accuracy_summary(
                pooled.region_category_accuracy
            ),
            "structural_relations": _prf_summary(
                pooled.structural_relations
            ),
            "source_text_exact": _accuracy_summary(pooled.source_text_exact),
            "source_text_preservation_ratio": (
                pooled.source_text_preservation_ratio
            ),
            "expected_diagnostic_recall": _accuracy_summary(
                pooled.expected_diagnostic_recall
            ),
            "unexpected_structural_diagnostic_count": (
                pooled.unexpected_structural_diagnostic_count
            ),
        },
        "macro_by_document": aggregate,
        "total_error_count": report.total_error_count,
        "error_type_counts": dict(report.error_type_counts),
        "documents_detail": [
            {
                "document_id": item.document_id,
                "element_detection_f1": item.metrics.element_detection.f1,
                "element_type_macro_f1": item.metrics.element_type_macro_f1,
                "heading_detection_f1": item.metrics.heading_detection.f1,
                "heading_level_accuracy": item.metrics.heading_level_accuracy.accuracy,
                "hierarchy_parent_f1": item.metrics.hierarchy_parent_edges.f1,
                "logical_unit_pairwise_f1": item.metrics.logical_unit_pairwise.f1,
                "integrity_exact_match_f1": item.metrics.integrity_exact_match.f1,
                "region_boundary_f1": item.metrics.region_boundary.f1,
                "region_category_accuracy": item.metrics.region_category_accuracy.accuracy,
                "structural_relation_f1": item.metrics.structural_relations.f1,
                "source_text_preservation_ratio": (
                    item.metrics.source_text_preservation_ratio
                ),
                "structure_mode_matches": item.metrics.structure_mode_matches,
                "structural_ready_matches": item.metrics.structural_ready_matches,
                "error_count": len(item.errors),
                "errors": [_error_summary(error) for error in item.errors],
            }
            for item in report.document_reports
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic DOCX Structure Gold Benchmark V0.1 pilot."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path for the full machine-readable benchmark report.",
    )
    args = parser.parse_args()
    aggregate = run_pilot()
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                aggregate.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary_dict(aggregate), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
