from __future__ import annotations

from pathlib import Path
import unittest

from benchmarks.pdf_tables_real_v0_1._corpus import git_blob_sha, load_sources
from benchmarks.pdf_tables_real_v0_1.evaluate import (
    PagePrediction,
    TablePrediction,
    evaluate,
    load_gold_cases,
)


def strict_table_prediction() -> TablePrediction:
    return TablePrediction(
        row_count=5,
        column_count=3,
        cells=(
            ("Header1", "Header2", "Header3"),
            ("Col11\nCol12", "Col21\nCol22", "Col31\nCol32\nCol33"),
            ("Col13", "Col23", "Col34\nCol35"),
            ("Col14", "Col24", "Col36"),
            ("Col15", "Col25\nCol26", ""),
        ),
    )


class RealPdfTableBenchmarkContractTests(unittest.TestCase):
    def test_source_manifest_and_gold_cover_the_same_pinned_sources(self) -> None:
        sources = load_sources()
        gold = load_gold_cases()
        self.assertEqual({item.id for item in sources}, {item.source_id for item in gold})
        self.assertGreaterEqual(len(sources), 6)
        for source in sources:
            self.assertIn(source.upstream_commit, source.url)
            self.assertIn(source.upstream_path, source.url)
            self.assertEqual(len(source.git_blob_sha), 40)
            self.assertTrue(source.rights_note)

    def test_git_blob_identity_is_content_sensitive(self) -> None:
        self.assertEqual(
            git_blob_sha(b"hello\n"),
            "ce013625030ba8dba906f756967f9e9ca394464a",
        )
        self.assertNotEqual(git_blob_sha(b"hello\n"), git_blob_sha(b"hello"))

    def test_gold_keeps_source_truth_separate_from_capability(self) -> None:
        cases = load_gold_cases()
        strict = next(item for item in cases if item.source_id == "pymupdf-strict-yes-no")
        self.assertIsNone(strict.source_truth_table_count)
        self.assertEqual(strict.capability_expectation, "SUPPORTED_REQUIRED")
        self.assertEqual((strict.tables[0].row_count, strict.tables[0].column_count), (5, 3))
        self.assertEqual(len(strict.tables[0].anchors), 15)

        row_span = next(item for item in cases if item.source_id == "camelot-row-span")
        column_span = next(item for item in cases if item.source_id == "camelot-column-span")
        image = next(item for item in cases if item.source_id == "camelot-image-only")
        self.assertEqual(row_span.source_truth_table_count, 1)
        self.assertEqual(row_span.capability_expectation, "MUST_PRESERVE_UNSTRUCTURED")
        self.assertEqual(column_span.capability_expectation, "MUST_PRESERVE_UNSTRUCTURED")
        self.assertEqual(image.capability_expectation, "MUST_PRESERVE_UNSTRUCTURED")
        self.assertTrue(any(item.capability_expectation == "OBSERVE" for item in cases))

    def test_evaluator_reports_count_truth_and_capability_independently(self) -> None:
        cases = load_gold_cases()
        predictions = []
        for case in cases:
            if case.source_id == "pymupdf-strict-yes-no":
                predictions.append(
                    PagePrediction(case.source_id, case.page, (strict_table_prediction(),))
                )
            else:
                predictions.append(PagePrediction(case.source_id, case.page, ()))
        result = evaluate(cases, predictions)
        self.assertTrue(result.quality_gate_passed)
        self.assertEqual(result.capability_checked_cases, 5)
        self.assertEqual(result.capability_passed_cases, 5)
        self.assertEqual(result.known_count_expected_tables, 5)
        self.assertEqual(result.known_count_predicted_tables, 0)
        self.assertEqual(result.known_count_missed_source_truth_tables, 5)
        self.assertEqual(result.known_count_source_truth_recall, 0.0)
        self.assertEqual(result.structural_contracts, 2)
        self.assertEqual(result.structural_matches, 1)

    def test_supported_structural_contract_fails_on_wrong_cell_content(self) -> None:
        strict = next(
            item for item in load_gold_cases() if item.source_id == "pymupdf-strict-yes-no"
        )
        wrong = strict_table_prediction()
        wrong_cells = list(wrong.cells)
        wrong_cells[4] = ("Col15", "WRONG", "")
        result = evaluate(
            (strict,),
            (
                PagePrediction(
                    strict.source_id,
                    strict.page,
                    (TablePrediction(5, 3, tuple(wrong_cells)),),
                ),
            ),
        )
        self.assertFalse(result.quality_gate_passed)
        self.assertEqual(result.structural_matches, 0)
        self.assertEqual(result.known_count_cases, 0)

    def test_evaluator_rejects_false_structure_for_fail_closed_case(self) -> None:
        image = next(
            item for item in load_gold_cases() if item.source_id == "camelot-image-only"
        )
        result = evaluate(
            (image,),
            (
                PagePrediction(
                    image.source_id,
                    image.page,
                    (TablePrediction(2, 3, (("a", "b", "c"), ("d", "e", "f"))),),
                ),
            ),
        )
        self.assertFalse(result.quality_gate_passed)
        self.assertEqual(result.known_count_false_positive_tables, 1)

    def test_independent_evaluator_has_no_production_detector_dependency(self) -> None:
        benchmark_root = Path(__file__).resolve().parents[1] / "benchmarks" / "pdf_tables_real_v0_1"
        source = (benchmark_root / "evaluate.py").read_text(encoding="utf-8")
        self.assertNotIn("source_understanding", source)
        self.assertNotIn("PdfTableDetector", source)
        self.assertNotIn("PdfAdapter", source)


if __name__ == "__main__":
    unittest.main()
