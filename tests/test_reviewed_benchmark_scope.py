from __future__ import annotations

import unittest
from types import SimpleNamespace

from benchmarks.docx_structure_real_v0_1.adjudication import ReviewCoverageStatus
from benchmarks.docx_structure_real_v0_1.run_reviewed_benchmark import (
    _scope_report_to_review_coverage,
    _source_text_escape_audit,
)
from source_understanding.evaluation.metrics import accuracy_score
from source_understanding.evaluation.report import (
    DocumentEvaluationMetrics,
    DocumentEvaluationReport,
    EvaluationError,
    EvaluationErrorType,
)


def _decision(status: ReviewCoverageStatus):
    return SimpleNamespace(
        coverage=SimpleNamespace(
            L0_source_fidelity=SimpleNamespace(coverage=status),
        )
    )


def _report(*errors: EvaluationError) -> DocumentEvaluationReport:
    metrics = DocumentEvaluationMetrics.model_construct(
        source_text_exact=accuracy_score(1, 2),
        source_text_gold_char_count=10,
        source_text_preserved_char_count=9,
        source_text_preservation_ratio=0.9,
    )
    return DocumentEvaluationReport.model_construct(
        document_id="reviewed-doc",
        metrics=metrics,
        alignment=None,
        errors=tuple(errors),
        diagnostics={},
    )


class ReviewedBenchmarkScopeTests(unittest.TestCase):
    def test_not_reviewed_l0_is_excluded_without_weakening_raw_evaluator(self) -> None:
        source_error = EvaluationError(
            type=EvaluationErrorType.SOURCE_TEXT_LOSS,
            message="source mismatch",
            metadata={
                "gold_text": "line 1\\nline 2",
                "predicted_raw_text": "line 1\nline 2",
            },
        )
        structural_error = EvaluationError(
            type=EvaluationErrorType.REGION_BOUNDARY_EXTRA,
            message="structural mismatch",
        )
        raw_report = _report(source_error, structural_error)

        scoped, exclusions = _scope_report_to_review_coverage(
            _decision(ReviewCoverageStatus.NOT_REVIEWED), raw_report
        )

        self.assertEqual(raw_report.errors, (source_error, structural_error))
        self.assertEqual(scoped.errors, (structural_error,))
        self.assertEqual(scoped.metrics.source_text_exact.total, 0)
        self.assertIsNone(scoped.metrics.source_text_exact.accuracy)
        self.assertEqual(scoped.metrics.source_text_gold_char_count, 0)
        self.assertEqual(scoped.metrics.source_text_preserved_char_count, 0)
        self.assertIsNone(scoped.metrics.source_text_preservation_ratio)
        self.assertEqual(exclusions["excluded_layers"], ["L0_source_fidelity"])
        self.assertEqual(
            exclusions["excluded_error_type_counts"],
            {EvaluationErrorType.SOURCE_TEXT_LOSS.value: 1},
        )

    def test_reviewed_l0_keeps_exact_source_measurement(self) -> None:
        source_error = EvaluationError(
            type=EvaluationErrorType.SOURCE_TEXT_LOSS,
            message="source mismatch",
        )
        raw_report = _report(source_error)

        scoped, exclusions = _scope_report_to_review_coverage(
            _decision(ReviewCoverageStatus.PARTIAL), raw_report
        )

        self.assertIs(scoped, raw_report)
        self.assertEqual(scoped.metrics.source_text_exact.total, 2)
        self.assertEqual(scoped.errors, (source_error,))
        self.assertEqual(exclusions["excluded_layers"], [])
        self.assertEqual(exclusions["excluded_error_type_counts"], {})

    def test_escape_audit_identifies_only_literal_backslash_n_equivalence(self) -> None:
        escaped = EvaluationError(
            type=EvaluationErrorType.SOURCE_TEXT_LOSS,
            message="escaped newline",
            metadata={
                "gold_text": "A\\nB",
                "predicted_raw_text": "A\nB",
            },
        )
        genuine = EvaluationError(
            type=EvaluationErrorType.SOURCE_TEXT_LOSS,
            message="real mismatch",
            metadata={
                "gold_text": "A\\nB",
                "predicted_raw_text": "A B",
            },
        )
        report = _report(escaped, genuine)

        self.assertEqual(
            _source_text_escape_audit(report),
            {
                "raw_source_text_mismatch_count": 2,
                "literal_backslash_n_equivalent_count": 1,
                "non_escape_mismatch_count": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
