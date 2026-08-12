from __future__ import annotations

from pathlib import Path
import unittest

from benchmarks.pdf_tables_real_v0_1._corpus import git_blob_sha, load_sources
from benchmarks.pdf_tables_real_v0_1.audit import audit_missed_table_failures
from benchmarks.pdf_tables_real_v0_1.evaluate import (
    CellSpanPrediction,
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


def span_table_prediction(
    row_count: int,
    column_count: int,
    span_kind: str,
) -> TablePrediction:
    if span_kind == "ROW_SPAN":
        span = CellSpanPrediction(row=0, column=0, row_span=2, column_span=1)
    elif span_kind == "COLUMN_SPAN":
        span = CellSpanPrediction(row=0, column=0, row_span=1, column_span=2)
    else:
        raise ValueError(f"unsupported test span kind: {span_kind}")
    return TablePrediction(
        row_count=row_count,
        column_count=column_count,
        cells=tuple(tuple("" for _ in range(column_count)) for _ in range(row_count)),
        spans=(span,),
    )


def two_table_predictions() -> tuple[TablePrediction, TablePrediction]:
    def table(kerala_value: str, pooled_value: str) -> TablePrediction:
        cells = [["" for _ in range(8)] for _ in range(13)]
        cells[1][0] = "State"
        cells[2][0] = "Kerala"
        cells[2][2] = kerala_value
        cells[12][0] = "Pooled"
        cells[12][7] = pooled_value
        return TablePrediction(
            row_count=13,
            column_count=8,
            cells=tuple(tuple(row) for row in cells),
        )

    return table("7.2", "6.4"), table("8.8", "3.3")


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

    def test_gold_keeps_source_truth_capability_and_span_oracle_separate(self) -> None:
        cases = load_gold_cases()
        strict = next(item for item in cases if item.source_id == "pymupdf-strict-yes-no")
        self.assertIsNone(strict.source_truth_table_count)
        self.assertEqual(strict.capability_expectation, "SUPPORTED_REQUIRED")
        self.assertEqual((strict.tables[0].row_count, strict.tables[0].column_count), (5, 3))
        self.assertEqual(len(strict.tables[0].anchors), 15)

        two_tables = next(item for item in cases if item.source_id == "camelot-two-tables")
        self.assertEqual(two_tables.source_truth_table_count, 2)
        self.assertEqual(two_tables.capability_expectation, "SUPPORTED_REQUIRED")
        self.assertEqual(len(two_tables.tables), 2)
        self.assertEqual(
            {(table.row_count, table.column_count) for table in two_tables.tables},
            {(13, 8)},
        )
        self.assertEqual(
            {
                next(anchor.text for anchor in table.anchors if (anchor.row, anchor.column) == (2, 2))
                for table in two_tables.tables
            },
            {"7.2", "8.8"},
        )

        row_span = next(item for item in cases if item.source_id == "camelot-row-span")
        column_span = next(item for item in cases if item.source_id == "camelot-column-span")
        image = next(item for item in cases if item.source_id == "camelot-image-only")
        self.assertEqual(row_span.source_truth_table_count, 1)
        self.assertEqual(row_span.capability_expectation, "SUPPORTED_REQUIRED")
        self.assertEqual((row_span.tables[0].row_count, row_span.tables[0].column_count), (40, 4))
        self.assertEqual(row_span.tables[0].required_span_kinds, ("ROW_SPAN",))
        self.assertEqual(column_span.capability_expectation, "SUPPORTED_REQUIRED")
        self.assertEqual(
            (column_span.tables[0].row_count, column_span.tables[0].column_count),
            (11, 7),
        )
        self.assertEqual(column_span.tables[0].required_span_kinds, ("COLUMN_SPAN",))
        self.assertEqual(image.capability_expectation, "MUST_PRESERVE_UNSTRUCTURED")
        self.assertFalse(any(item.capability_expectation == "OBSERVE" for item in cases))

    def test_evaluator_reports_count_truth_and_capability_independently(self) -> None:
        cases = load_gold_cases()
        predictions = []
        for case in cases:
            if case.source_id == "pymupdf-strict-yes-no":
                tables = (strict_table_prediction(),)
            elif case.source_id == "camelot-two-tables":
                tables = two_table_predictions()
            elif case.source_id == "camelot-row-span":
                tables = (span_table_prediction(40, 4, "ROW_SPAN"),)
            elif case.source_id == "camelot-column-span":
                tables = (span_table_prediction(11, 7, "COLUMN_SPAN"),)
            else:
                tables = ()
            predictions.append(PagePrediction(case.source_id, case.page, tables))
        result = evaluate(cases, predictions)
        self.assertTrue(result.quality_gate_passed)
        self.assertEqual(result.capability_checked_cases, 6)
        self.assertEqual(result.capability_passed_cases, 6)
        self.assertEqual(result.known_count_expected_tables, 5)
        self.assertEqual(result.known_count_predicted_tables, 4)
        self.assertEqual(result.known_count_missed_source_truth_tables, 1)
        self.assertEqual(result.known_count_source_truth_precision, 1.0)
        self.assertEqual(result.known_count_source_truth_recall, 0.8)
        self.assertEqual(result.structural_contracts, 6)
        self.assertEqual(result.structural_matches, 5)

    def test_two_table_contract_requires_both_independent_structures(self) -> None:
        case = next(
            item for item in load_gold_cases() if item.source_id == "camelot-two-tables"
        )
        only_one = two_table_predictions()[0]
        result = evaluate(
            (case,),
            (PagePrediction(case.source_id, case.page, (only_one,)),),
        )
        self.assertFalse(result.quality_gate_passed)
        self.assertEqual(result.structural_matches, 1)
        self.assertEqual(result.known_count_missed_source_truth_tables, 1)

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

    def test_supported_span_contract_requires_topology_not_only_shape(self) -> None:
        row_span = next(
            item for item in load_gold_cases() if item.source_id == "camelot-row-span"
        )
        same_shape_without_span = TablePrediction(
            row_count=40,
            column_count=4,
            cells=tuple(tuple("" for _ in range(4)) for _ in range(40)),
        )
        result = evaluate(
            (row_span,),
            (PagePrediction(row_span.source_id, row_span.page, (same_shape_without_span,)),),
        )
        self.assertFalse(result.quality_gate_passed)
        self.assertEqual(result.structural_matches, 0)
        self.assertEqual(result.known_count_predicted_tables, 1)

    def test_invalid_span_geometry_cannot_satisfy_topology_contract(self) -> None:
        column_span = next(
            item for item in load_gold_cases() if item.source_id == "camelot-column-span"
        )
        malformed = TablePrediction(
            row_count=11,
            column_count=7,
            cells=tuple(tuple("" for _ in range(7)) for _ in range(11)),
            spans=(CellSpanPrediction(row=0, column=6, row_span=1, column_span=2),),
        )
        result = evaluate(
            (column_span,),
            (PagePrediction(column_span.source_id, column_span.page, (malformed,)),),
        )
        self.assertFalse(result.quality_gate_passed)
        self.assertEqual(result.structural_matches, 0)

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

    def test_m2_3_failure_audit_counts_cases_separately_from_candidate_reasons(self) -> None:
        reports = (
            {
                "source_id": "alpha",
                "table_diagnostics": [
                    {
                        "metadata": {
                            "page": 1,
                            "reason_counts": {
                                "complex_or_merged_cells": 2,
                                "source_block_crosses_table_boundary": 1,
                            },
                        }
                    }
                ],
            },
            {
                "source_id": "beta",
                "table_diagnostics": [
                    {
                        "metadata": {
                            "page": 2,
                            "reason_counts": {"complex_or_merged_cells": 1},
                        }
                    }
                ],
            },
        )
        audit = audit_missed_table_failures(
            (("alpha", 1), ("beta", 2), ("gamma", 1)),
            reports,
        )
        self.assertEqual(audit["missed_case_count"], 3)
        self.assertEqual(audit["classified_missed_case_count"], 2)
        self.assertEqual(audit["unclassified_missed_cases"], ["gamma#page:1"])
        self.assertEqual(
            audit["failure_class_case_counts"],
            {
                "complex_or_merged_cells": 2,
                "source_block_crosses_table_boundary": 1,
            },
        )
        self.assertEqual(
            audit["candidate_reason_occurrences"],
            {
                "complex_or_merged_cells": 3,
                "source_block_crosses_table_boundary": 1,
            },
        )

    def test_m2_3_failure_audit_is_page_scoped_and_ignores_invalid_counts(self) -> None:
        audit = audit_missed_table_failures(
            (("alpha", 1),),
            (
                {
                    "source_id": "alpha",
                    "table_diagnostics": [
                        {"metadata": {"page": 2, "reason_counts": {"wrong_page": 1}}},
                        {
                            "metadata": {
                                "page": 1,
                                "reason_counts": {
                                    "valid": 1,
                                    "zero": 0,
                                    "boolean": True,
                                    "text": "1",
                                },
                            }
                        },
                    ],
                },
            ),
        )
        self.assertEqual(audit["unclassified_missed_cases"], [])
        self.assertEqual(audit["failure_class_case_counts"], {"valid": 1})
        self.assertEqual(audit["candidate_reason_occurrences"], {"valid": 1})

    def test_independent_evaluator_has_no_production_detector_dependency(self) -> None:
        benchmark_root = Path(__file__).resolve().parents[1] / "benchmarks" / "pdf_tables_real_v0_1"
        source = (benchmark_root / "evaluate.py").read_text(encoding="utf-8")
        self.assertNotIn("source_understanding", source)
        self.assertNotIn("PdfTableDetector", source)
        self.assertNotIn("PdfAdapter", source)


if __name__ == "__main__":
    unittest.main()
