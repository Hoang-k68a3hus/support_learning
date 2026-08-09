from __future__ import annotations

import unittest

from ai_data_studio.validation import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationReport,
    ValidationSeverity,
)


class ValidationIssueTests(unittest.TestCase):
    def test_warning_does_not_make_report_invalid(self) -> None:
        warning = ValidationIssue(
            code=ValidationIssueCode.SOURCE_LANGUAGE_UNAVAILABLE,
            severity=ValidationSeverity.WARNING,
            message="Canonical language is unavailable.",
            record_id="record-1",
            path="source.language",
        )
        report = ValidationReport(issues=(warning,))

        self.assertTrue(report.is_valid)
        self.assertEqual(report.errors, ())
        self.assertEqual(report.warnings, (warning,))

    def test_error_filters_are_structured_and_stable(self) -> None:
        error = ValidationIssue(
            code=ValidationIssueCode.TARGET_NOT_FOUND,
            severity=ValidationSeverity.ERROR,
            message="Target is missing.",
            record_id="record-1",
            path="target.target_id",
            related_ids=("missing-target",),
        )
        report = ValidationReport(issues=(error,))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.errors, (error,))
        self.assertEqual(report.warnings, ())
        self.assertEqual(error.code.value, "TARGET_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
