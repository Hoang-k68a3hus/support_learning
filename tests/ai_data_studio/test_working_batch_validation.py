from __future__ import annotations

import unittest

from ai_data_studio.validation import (
    ValidationIssueCode,
    WorkingBatchValidator,
    WorkingRecordValidator,
)
from source_understanding.schemas.document import SemanticAnnotationType

from tests.ai_data_studio._validation_fixtures import (
    canonical_document,
    working_batch,
    working_record,
)


class WorkingBatchValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = canonical_document()
        self.record = working_record(self.document)
        self.batch = working_batch()

    def record_codes(self, record=None, batch=None):
        report = WorkingRecordValidator().validate(
            record=record or self.record,
            document=self.document,
            batch=batch or self.batch,
        )
        return tuple(issue.code for issue in report.issues)

    def batch_codes(self, records, batch=None):
        report = WorkingBatchValidator().validate(
            batch=batch or self.batch,
            records=records,
        )
        return tuple(issue.code for issue in report.issues)

    def test_record_matches_batch(self) -> None:
        self.assertEqual(self.record_codes(), ())
        self.assertTrue(
            WorkingBatchValidator().validate(
                batch=self.batch,
                records=(self.record,),
            ).is_valid
        )

    def test_record_batch_id_mismatch(self) -> None:
        record = self.record.model_copy(update={"batch_id": "other-batch"})
        self.assertIn(
            ValidationIssueCode.BATCH_ID_MISMATCH,
            self.record_codes(record=record),
        )

    def test_record_not_declared_in_batch(self) -> None:
        batch = working_batch(record_ids=("other-record",))
        self.assertIn(
            ValidationIssueCode.BATCH_RECORD_NOT_DECLARED,
            self.record_codes(batch=batch),
        )

    def test_evaluated_types_mismatch(self) -> None:
        batch = working_batch(
            evaluated_types=(
                SemanticAnnotationType.DEFINITION,
                SemanticAnnotationType.EXAMPLE,
            )
        )
        self.assertIn(
            ValidationIssueCode.BATCH_EVALUATED_TYPES_MISMATCH,
            self.record_codes(batch=batch),
        )

    def test_batch_missing_declared_record(self) -> None:
        self.assertIn(
            ValidationIssueCode.BATCH_RECORD_MISSING,
            self.batch_codes(()),
        )

    def test_batch_rejects_unexpected_record(self) -> None:
        unexpected = self.record.model_copy(update={"record_id": "record-2"})
        codes = self.batch_codes((self.record, unexpected))
        self.assertIn(ValidationIssueCode.BATCH_UNEXPECTED_RECORD, codes)
        self.assertIn(ValidationIssueCode.BATCH_RECORD_NOT_DECLARED, codes)

    def test_batch_rejects_duplicate_actual_record_ids(self) -> None:
        self.assertIn(
            ValidationIssueCode.BATCH_DUPLICATE_RECORD,
            self.batch_codes((self.record, self.record)),
        )


if __name__ == "__main__":
    unittest.main()
