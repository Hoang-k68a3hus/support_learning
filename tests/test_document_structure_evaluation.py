from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from benchmarks.docx_structure_v0_1.adjudicated_pilot import (
    GOLD_ADJUDICATION_VERSION,
    build_adjudicated_manifest,
    build_pilot_cases,
    materialize,
)
from benchmarks.docx_structure_v0_1.generate_pilot import GENERATOR_ID
from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.evaluation import (
    BenchmarkEvaluator,
    DocumentStructureEvaluator,
    EvaluationLoadError,
    load_materialized_benchmark,
)
from source_understanding.evaluation.metrics import prf_counts
from source_understanding.evaluation.report import EvaluationErrorType
from source_understanding.evaluation.schemas import (
    BenchmarkManifest,
    GoldDocumentStructure,
)


class GeneratedDocxGoldBenchmarkTests(unittest.TestCase):
    def test_generator_and_adjudication_are_byte_deterministic(self) -> None:
        first = build_pilot_cases()
        second = build_pilot_cases()
        self.assertEqual(len(first), 5)
        self.assertEqual([item.payload for item in first], [item.payload for item in second])
        self.assertEqual([item.gold for item in first], [item.gold for item in second])
        for item in first:
            expected = "sha256:" + hashlib.sha256(item.payload).hexdigest()
            self.assertEqual(item.gold.source.sha256, expected)
            self.assertEqual(item.gold.source.generator_id, GENERATOR_ID)
        reviewed = next(item for item in first if item.document_id == "docx-pilot-03")
        self.assertEqual(
            reviewed.gold.metadata["gold_adjudication_version"],
            GOLD_ADJUDICATION_VERSION,
        )

    def test_materialized_manifest_and_gold_are_round_trippable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = materialize(root)
            parsed = type(manifest).model_validate_json(
                (root / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(parsed, manifest)
            self.assertEqual(
                parsed.metadata["gold_adjudication_version"],
                GOLD_ADJUDICATION_VERSION,
            )
            for case in manifest.cases:
                payload = (root / case.source_file).read_bytes()
                self.assertEqual(
                    "sha256:" + hashlib.sha256(payload).hexdigest(),
                    case.sha256,
                )
                gold = GoldDocumentStructure.model_validate_json(
                    (root / case.annotation_file).read_text(encoding="utf-8")
                )
                self.assertEqual(gold.document_id, case.document_id)
                self.assertEqual(gold.source.sha256, case.sha256)

    def test_materialized_bundle_loader_verifies_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = materialize(root)
            loaded = load_materialized_benchmark(root)
            self.assertEqual(loaded.manifest, manifest)
            self.assertEqual(len(loaded.cases), 5)
            first = loaded.cases[0]
            first.source_path.write_bytes(first.source_path.read_bytes() + b"tamper")
            with self.assertRaises(EvaluationLoadError):
                load_materialized_benchmark(root)

    def test_gold_regions_are_exact_cover_not_partial_labels(self) -> None:
        case = build_pilot_cases()[0]
        raw = case.gold.model_dump(mode="json")
        raw["regions"][0]["element_ids"] = raw["regions"][0]["element_ids"][:-1]
        with self.assertRaises(ValidationError):
            GoldDocumentStructure.model_validate(raw)

    def test_manifest_rejects_path_traversal(self) -> None:
        manifest = build_adjudicated_manifest(build_pilot_cases())
        raw = manifest.model_dump(mode="json")
        raw["cases"][0]["source_file"] = "../escape.docx"
        with self.assertRaises(ValidationError):
            BenchmarkManifest.model_validate(raw)

    def test_gold_rejects_future_schema_version(self) -> None:
        case = build_pilot_cases()[0]
        raw = case.gold.model_dump(mode="json")
        raw["schema_version"] = "999"
        with self.assertRaises(ValidationError):
            GoldDocumentStructure.model_validate(raw)

    def test_complete_miss_is_zero_f1_not_undefined(self) -> None:
        score = prf_counts(tp=0, fp=0, fn=3)
        self.assertIsNone(score.precision)
        self.assertEqual(score.recall, 0.0)
        self.assertEqual(score.f1, 0.0)

    def test_all_adjudicated_cases_run_through_real_docx_pipeline_and_evaluator(self) -> None:
        runner = SourceAdapterRunner()
        evaluator = DocumentStructureEvaluator()
        reports = []
        cases = build_pilot_cases()
        for case in cases:
            result = runner.understand_bytes(
                case.payload,
                adapter=DocxAdapter(),
                document_id=case.document_id,
                source_name=case.file_name,
                processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            )
            report = evaluator.evaluate(
                case.gold,
                result.understanding.document,
                adapter_diagnostics=result.adapter_result.diagnostics,
                structural_ready=(
                    result.understanding.completion_report.structural_ready
                ),
            )
            self.assertEqual(report.document_id, case.document_id)
            self.assertFalse(
                any(
                    item.status.value == "AMBIGUOUS"
                    for item in report.alignment.matches
                ),
                case.document_id,
            )
            # Source fidelity is a hard pilot invariant even when the structure
            # benchmark intentionally exposes a parser-quality gap.
            self.assertEqual(report.metrics.source_text_preservation_ratio, 1.0)
            reports.append(report)

        by_id = {item.document_id: item for item in reports}
        nested = by_id["docx-pilot-02"]
        self.assertEqual(nested.metrics.structural_relations.f1, 1.0)
        self.assertFalse(
            any(
                error.type == EvaluationErrorType.RELATION_EXTRA
                for error in nested.errors
            ),
            "Element->LogicalUnit membership PART_OF edges are outside the nested "
            "LogicalUnit->LogicalUnit relation scope",
        )
        notes = by_id["docx-pilot-03"]
        self.assertEqual(notes.metrics.element_detection.f1, 1.0)
        self.assertFalse(
            any(
                error.type == EvaluationErrorType.ADAPTER_EXTRA_ELEMENT
                for error in notes.errors
            ),
            "adjudicated gold must include deliberate source-zone boundaries",
        )

        aggregate = BenchmarkEvaluator().aggregate(
            build_adjudicated_manifest(cases), reports
        )
        self.assertEqual(len(aggregate.document_reports), 5)


if __name__ == "__main__":
    unittest.main()
