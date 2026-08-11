from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.evaluation import BenchmarkEvaluator, DocumentStructureEvaluator
from source_understanding.evaluation.metrics import accuracy_score, prf_counts, prf_from_sets
from source_understanding.evaluation.report import EvaluationErrorType
from source_understanding.evaluation.structure_scoring import StructureScorer

from ._corpus import FIXED_EVALUATION_TIME, SOURCES, _download
from .adjudication import ReviewCoverageStatus
from .reviewed_gold import (
    REVIEWED_GOLD_ADJUDICATION_VERSION,
    build_reviewed_benchmark_manifest,
    load_review_decisions,
)


_L0_ERROR_TYPES = frozenset({EvaluationErrorType.SOURCE_TEXT_LOSS})


def _verify_source_revision(source: dict[str, object], payload: bytes) -> None:
    expected_hash = source.get("sha256")
    expected_bytes = source.get("bytes")
    actual_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    if not isinstance(expected_bytes, int) or len(payload) != expected_bytes:
        raise RuntimeError(
            f"pinned source byte-length mismatch for {source.get('id')!r}: "
            f"expected={expected_bytes!r}, actual={len(payload)}"
        )
    if not isinstance(expected_hash, str) or actual_hash != expected_hash:
        raise RuntimeError(
            f"pinned source hash mismatch for {source.get('id')!r}: "
            f"expected={expected_hash!r}, actual={actual_hash!r}"
        )


def _per_logical_unit_type(gold, predicted, alignment) -> dict[str, object]:
    scorer = StructureScorer()
    output: dict[str, object] = {}
    for unit_type in gold.evaluated_logical_unit_types:
        scoped = gold.model_copy(update={"evaluated_logical_unit_types": (unit_type,)})
        pairwise, exact = scorer.logical_units(scoped, predicted, alignment, [])
        output[unit_type.value] = {
            "pairwise": pairwise.model_dump(mode="json"),
            "exact_match": exact.model_dump(mode="json"),
        }
    return output


def _context_anchor_metrics(gold, predicted, alignment) -> dict[str, object]:
    gold_by_anchor = {node.anchor_element_id: node for node in gold.context_nodes}
    predicted_by_token: dict[str, object] = {}
    predicted_tokens: set[str] = set()
    for node in predicted.context_nodes:
        anchor_id = node.attributes.get("anchor_element_id")
        if not isinstance(anchor_id, str):
            token = f"__pred_ctx__:{node.id}"
        else:
            gold_anchor = alignment.predicted_to_gold.get(anchor_id)
            token = gold_anchor if isinstance(gold_anchor, str) else f"__pred_ctx__:{node.id}"
        predicted_tokens.add(token)
        predicted_by_token[token] = node

    gold_tokens = set(gold_by_anchor)
    detection = prf_from_sets(gold_tokens, predicted_tokens)
    level_correct = 0
    level_total = 0
    level_mismatches: list[dict[str, object]] = []
    for anchor_id in sorted(gold_tokens & predicted_tokens):
        gold_node = gold_by_anchor[anchor_id]
        predicted_node = predicted_by_token[anchor_id]
        if gold_node.level is None:
            continue
        level_total += 1
        if predicted_node.level == gold_node.level:
            level_correct += 1
        else:
            level_mismatches.append(
                {
                    "gold_anchor_element_id": anchor_id,
                    "expected_level": gold_node.level,
                    "predicted_level": predicted_node.level,
                }
            )
    return {
        "anchor_detection": detection.model_dump(mode="json"),
        "level_accuracy": accuracy_score(level_correct, level_total).model_dump(mode="json"),
        "level_mismatches": level_mismatches,
    }


def _sum_prf(records: list[dict[str, object]]) -> dict[str, object]:
    return prf_counts(
        sum(int(item["true_positive"]) for item in records),
        sum(int(item["false_positive"]) for item in records),
        sum(int(item["false_negative"]) for item in records),
    ).model_dump(mode="json")


def _sum_accuracy(records: list[dict[str, object]]) -> dict[str, object]:
    correct = sum(int(item["correct"]) for item in records)
    total = sum(int(item["total"]) for item in records)
    return accuracy_score(correct, total).model_dump(mode="json")


def _source_text_escape_audit(report) -> dict[str, int]:
    """Diagnose review-artifact escaping without weakening exact source scoring."""

    source_errors = [
        error for error in report.errors if error.type == EvaluationErrorType.SOURCE_TEXT_LOSS
    ]
    escaped_newline_equivalent = 0
    for error in source_errors:
        gold_text = error.metadata.get("gold_text")
        predicted_text = error.metadata.get("predicted_raw_text")
        if (
            isinstance(gold_text, str)
            and isinstance(predicted_text, str)
            and "\\n" in gold_text
            and gold_text.replace("\\n", "\n") == predicted_text
        ):
            escaped_newline_equivalent += 1
    return {
        "raw_source_text_mismatch_count": len(source_errors),
        "literal_backslash_n_equivalent_count": escaped_newline_equivalent,
        "non_escape_mismatch_count": len(source_errors) - escaped_newline_equivalent,
    }


def _scope_report_to_review_coverage(decision, report):
    """Exclude measurements for review layers explicitly marked NOT_REVIEWED.

    The generic evaluator intentionally scores every available gold field. The
    reviewed real-DOCX benchmark has an additional human-review coverage contract,
    so its aggregate must not turn fields from an unreviewed layer into accuracy
    claims or disagreement events.
    """

    l0_status = decision.coverage.L0_source_fidelity.coverage
    if l0_status != ReviewCoverageStatus.NOT_REVIEWED:
        return report, {
            "excluded_layers": [],
            "excluded_error_type_counts": {},
        }

    excluded = Counter(
        error.type.value for error in report.errors if error.type in _L0_ERROR_TYPES
    )
    retained_errors = tuple(
        error for error in report.errors if error.type not in _L0_ERROR_TYPES
    )
    metrics = report.metrics.model_copy(
        update={
            "source_text_exact": accuracy_score(0, 0),
            "source_text_gold_char_count": 0,
            "source_text_preserved_char_count": 0,
            "source_text_preservation_ratio": None,
        }
    )
    scoped = report.model_copy(update={"metrics": metrics, "errors": retained_errors})
    return scoped, {
        "excluded_layers": ["L0_source_fidelity"],
        "excluded_error_type_counts": dict(sorted(excluded.items())),
    }


def evaluate_reviewed_corpus() -> dict[str, object]:
    decisions = load_review_decisions()
    decision_by_id = {decision.source_id: decision for decision in decisions}
    manifest = build_reviewed_benchmark_manifest(decisions)
    evaluator = DocumentStructureEvaluator()
    reports = []
    documents: list[dict[str, object]] = []
    context_detection_records: list[dict[str, object]] = []
    context_level_records: list[dict[str, object]] = []
    escape_audit_totals = Counter()
    per_type_records: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(
        lambda: {"pairwise": [], "exact_match": []}
    )

    for source in SOURCES:
        document_id = str(source["id"])
        decision = decision_by_id[document_id]
        gold = decision.gold
        if gold is None:  # pragma: no cover - guarded by reviewed-gold loader.
            raise RuntimeError(f"reviewed gold missing for {document_id!r}")

        payload = _download(str(source["url"]))
        _verify_source_revision(source, payload)
        adapter = DocxAdapter()
        production = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=adapter,
            document_id=document_id,
            source_name=str(source["file_name"]),
            processed_at=FIXED_EVALUATION_TIME,
        )
        understanding = production.understanding
        raw_report = evaluator.evaluate(
            gold,
            understanding.document,
            adapter_diagnostics=production.adapter_result.diagnostics,
            structural_ready=understanding.completion_report.structural_ready,
        )
        escape_audit = _source_text_escape_audit(raw_report)
        escape_audit_totals.update(escape_audit)
        report, scope_exclusions = _scope_report_to_review_coverage(
            decision, raw_report
        )
        reports.append(report)

        per_type = _per_logical_unit_type(
            gold, understanding.document, report.alignment
        )
        for unit_type, metrics in per_type.items():
            per_type_records[unit_type]["pairwise"].append(metrics["pairwise"])
            per_type_records[unit_type]["exact_match"].append(metrics["exact_match"])

        context_metrics = _context_anchor_metrics(
            gold, understanding.document, report.alignment
        )
        context_detection_records.append(context_metrics["anchor_detection"])
        context_level_records.append(context_metrics["level_accuracy"])

        documents.append(
            {
                "id": document_id,
                "review_status": decision.status.value,
                "review_coverage": decision.coverage.model_dump(mode="json"),
                "measurement_scope_exclusions": scope_exclusions,
                "source_text_escape_audit": escape_audit,
                "metrics": report.metrics.model_dump(mode="json"),
                "context_anchor_metrics": context_metrics,
                "logical_unit_metrics_by_type": per_type,
                "error_count": len(report.errors),
                "error_type_counts": dict(
                    sorted(Counter(error.type.value for error in report.errors).items())
                ),
                "errors": [error.model_dump(mode="json") for error in report.errors],
                "prediction": {
                    "element_count": len(understanding.document.elements),
                    "logical_unit_count": len(understanding.document.logical_units),
                    "context_node_count": len(understanding.document.context_nodes),
                    "region_count": len(understanding.document.regions),
                    "relation_count": len(understanding.document.relations),
                    "structure_mode": understanding.document.structure.mode.value,
                    "structural_ready": understanding.completion_report.structural_ready,
                },
            }
        )

    aggregate = BenchmarkEvaluator().aggregate(manifest, reports)
    per_type_pooled: dict[str, object] = {}
    for unit_type, families in sorted(per_type_records.items()):
        per_type_pooled[unit_type] = {
            "pairwise": _sum_prf(families["pairwise"]),
            "exact_match": _sum_prf(families["exact_match"]),
        }

    return {
        "benchmark": manifest.name,
        "benchmark_version": manifest.benchmark_version,
        "adjudication_version": REVIEWED_GOLD_ADJUDICATION_VERSION,
        "measurement_scope": (
            "structural agreement on five pinned assistant-adjudicated public DOCX documents"
        ),
        "measurement_scope_policy": (
            "metrics and disagreement events from NOT_REVIEWED layers are excluded from "
            "the reviewed benchmark aggregate; raw mismatches may remain as diagnostics"
        ),
        "population_accuracy_claim": False,
        "gold_oracle_policy": (
            "source-document inspection + independent OOXML audit; production output is not gold"
        ),
        "document_count": len(documents),
        "documents": documents,
        "aggregate": aggregate.model_dump(mode="json"),
        "reviewed_extensions": {
            "context_anchor_detection": _sum_prf(context_detection_records),
            "context_level_accuracy": _sum_accuracy(context_level_records),
            "logical_unit_metrics_by_type": per_type_pooled,
            "source_text_escape_audit": dict(sorted(escape_audit_totals.items())),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate production source understanding against SU4.1 reviewed real-DOCX gold."
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero when any reviewed-gold disagreement is reported.",
    )
    args = parser.parse_args()

    result = evaluate_reviewed_corpus()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    total_errors = int(result["aggregate"]["total_error_count"])
    if args.fail_on_error and total_errors:
        raise SystemExit(
            f"reviewed real-DOCX benchmark found {total_errors} structural disagreement(s)"
        )


if __name__ == "__main__":
    main()
