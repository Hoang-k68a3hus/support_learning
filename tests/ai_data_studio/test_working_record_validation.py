from __future__ import annotations

import unittest

from ai_data_studio.schemas import WorkingRecordStatus, WorkingTarget
from ai_data_studio.validation import (
    ValidationIssueCode,
    ValidationSeverity,
    WorkingRecordValidator,
    build_target_text_snapshot,
)
from source_understanding.schemas.document import SemanticTextView
from source_understanding.semantics.provider import SemanticTargetKind

from tests.ai_data_studio._validation_fixtures import (
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
    working_target,
)


class WorkingRecordValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = canonical_document()
        self.batch = working_batch()
        self.validator = WorkingRecordValidator()

    def report(self, record, *, document=None, batch=None):
        return self.validator.validate(
            record=record,
            document=document or self.document,
            batch=batch or self.batch,
        )

    def codes(self, record, *, document=None, batch=None):
        return tuple(
            issue.code
            for issue in self.report(record, document=document, batch=batch).issues
        )

    def with_source(self, record, **updates: object):
        return record.model_copy(
            update={"source": record.source.model_copy(update=updates)}
        )

    def test_matching_source_snapshot_and_logical_target_pass(self) -> None:
        report = self.report(working_record(self.document))
        self.assertTrue(report.is_valid)
        self.assertEqual(report.issues, ())

    def test_matching_pass_record_is_cross_object_valid_without_review(self) -> None:
        record = working_record(
            self.document,
            decisions=(positive_definition(),),
            status=WorkingRecordStatus.PASS,
        )

        report = self.report(record)

        self.assertTrue(report.is_valid)
        self.assertEqual(report.issues, ())

    def test_document_id_mismatch_is_error(self) -> None:
        record = self.with_source(
            working_record(self.document),
            document_id="stale-doc",
        )
        self.assertIn(
            ValidationIssueCode.SOURCE_DOCUMENT_ID_MISMATCH,
            self.codes(record),
        )

    def test_content_hash_mismatch_is_error(self) -> None:
        record = self.with_source(
            working_record(self.document),
            content_hash="sha256:" + "f" * 64,
        )
        self.assertIn(
            ValidationIssueCode.SOURCE_CONTENT_HASH_MISMATCH,
            self.codes(record),
        )

    def test_element_snapshot_hash_mismatch_is_error(self) -> None:
        record = self.with_source(
            working_record(self.document),
            element_snapshot_hash="sha256:" + "f" * 64,
        )
        self.assertIn(
            ValidationIssueCode.SOURCE_ELEMENT_SNAPSHOT_HASH_MISMATCH,
            self.codes(record),
        )

    def test_canonical_element_text_change_invalidates_stale_record(self) -> None:
        record = working_record(self.document)
        changed_element = self.document.elements[0].model_copy(
            update={"normalized_text": "Changed canonical text"}
        )
        changed_document = self.document.model_copy(
            update={
                "elements": (changed_element, *self.document.elements[1:])
            }
        )

        codes = self.codes(record, document=changed_document)

        self.assertIn(
            ValidationIssueCode.SOURCE_ELEMENT_SNAPSHOT_HASH_MISMATCH,
            codes,
        )
        self.assertIn(ValidationIssueCode.TARGET_NORMALIZED_TEXT_MISMATCH, codes)

    def test_language_mismatch_is_error(self) -> None:
        record = self.with_source(working_record(self.document), language="vi")
        self.assertIn(
            ValidationIssueCode.SOURCE_LANGUAGE_MISMATCH,
            self.codes(record),
        )

    def test_missing_canonical_language_is_warning(self) -> None:
        document = canonical_document(language=None)
        record = working_record(document)

        report = self.report(record, document=document)

        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.warnings), 1)
        self.assertEqual(
            report.warnings[0].code,
            ValidationIssueCode.SOURCE_LANGUAGE_UNAVAILABLE,
        )
        self.assertEqual(report.warnings[0].severity, ValidationSeverity.WARNING)

    def test_element_target_matches_canonical_element(self) -> None:
        target = working_target(
            self.document,
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
        )
        record = working_record(self.document, target=target)
        self.assertTrue(self.report(record).is_valid)

    def test_element_target_unknown_id_stops_dependent_target_checks(self) -> None:
        target = WorkingTarget(
            target_id="missing",
            target_kind=SemanticTargetKind.ELEMENT,
            element_ids=("missing",),
            element_orders=(0,),
            raw_text="missing",
            normalized_text="missing",
        )
        record = working_record(self.document, target=target)
        target_codes = tuple(
            code for code in self.codes(record) if code.value.startswith("TARGET_")
        )
        self.assertEqual(target_codes, (ValidationIssueCode.TARGET_NOT_FOUND,))

    def test_target_kind_mismatch_is_error(self) -> None:
        element_target = working_target(
            self.document,
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
        )
        target = WorkingTarget(
            target_id="e-1",
            target_kind=SemanticTargetKind.LOGICAL_UNIT,
            element_ids=element_target.element_ids,
            element_orders=element_target.element_orders,
            raw_text=element_target.raw_text,
            normalized_text=element_target.normalized_text,
            logical_unit_type="TEXT_BLOCK",
        )
        record = working_record(self.document, target=target)
        self.assertIn(ValidationIssueCode.TARGET_KIND_MISMATCH, self.codes(record))

    def test_element_target_id_must_match_element_id(self) -> None:
        target = working_target(
            self.document,
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
        ).model_copy(update={"element_ids": ("e-2",)})
        record = working_record(self.document, target=target)
        self.assertIn(
            ValidationIssueCode.TARGET_ELEMENT_IDS_MISMATCH,
            self.codes(record),
        )

    def test_element_order_mismatch_is_error(self) -> None:
        target = working_target(
            self.document,
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
        ).model_copy(update={"element_orders": (1,)})
        record = working_record(self.document, target=target)
        self.assertIn(
            ValidationIssueCode.TARGET_ELEMENT_ORDERS_MISMATCH,
            self.codes(record),
        )

    def test_element_raw_and_normalized_snapshot_mismatches_are_separate(self) -> None:
        base = working_target(
            self.document,
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
        )
        target = base.model_copy(
            update={
                "raw_text": "stale raw",
                "normalized_text": "stale normalized",
            }
        )
        record = working_record(self.document, target=target)
        codes = self.codes(record)
        self.assertIn(ValidationIssueCode.TARGET_RAW_TEXT_MISMATCH, codes)
        self.assertIn(ValidationIssueCode.TARGET_NORMALIZED_TEXT_MISMATCH, codes)

    def logical_target_for(self, element_ids: tuple[str, ...]) -> WorkingTarget:
        by_id = {element.id: element for element in self.document.elements}
        selected = tuple(by_id[element_id] for element_id in element_ids)
        return WorkingTarget(
            target_id="lu-1",
            target_kind=SemanticTargetKind.LOGICAL_UNIT,
            element_ids=element_ids,
            element_orders=tuple(element.order for element in selected),
            raw_text=build_target_text_snapshot(
                selected,
                view=SemanticTextView.RAW_TEXT,
            ),
            normalized_text=build_target_text_snapshot(
                selected,
                view=SemanticTextView.NORMALIZED_TEXT,
            ),
            logical_unit_type="TEXT_BLOCK",
        )

    def test_logical_unit_missing_or_extra_element_is_rejected(self) -> None:
        missing = working_record(
            self.document,
            target=self.logical_target_for(("e-1",)),
        )
        extra = working_record(
            self.document,
            target=self.logical_target_for(("e-1", "e-2", "e-context")),
        )

        self.assertIn(
            ValidationIssueCode.TARGET_ELEMENT_IDS_MISMATCH,
            self.codes(missing),
        )
        self.assertIn(
            ValidationIssueCode.TARGET_ELEMENT_IDS_MISMATCH,
            self.codes(extra),
        )

    def test_logical_unit_reversed_membership_is_rejected(self) -> None:
        target = working_target(self.document).model_copy(
            update={"element_ids": ("e-2", "e-1")}
        )
        record = working_record(self.document, target=target)
        self.assertIn(
            ValidationIssueCode.TARGET_ELEMENT_IDS_MISMATCH,
            self.codes(record),
        )

    def test_logical_unit_order_mismatch_is_rejected(self) -> None:
        target = working_target(self.document).model_copy(
            update={"element_orders": (0, 2)}
        )
        record = working_record(self.document, target=target)
        self.assertIn(
            ValidationIssueCode.TARGET_ELEMENT_ORDERS_MISMATCH,
            self.codes(record),
        )

    def test_logical_unit_type_and_text_snapshot_mismatch_are_rejected(self) -> None:
        target = working_target(self.document).model_copy(
            update={
                "logical_unit_type": "QA_PAIR",
                "raw_text": "stale target",
            }
        )
        record = working_record(self.document, target=target)
        codes = self.codes(record)
        self.assertIn(
            ValidationIssueCode.TARGET_LOGICAL_UNIT_TYPE_MISMATCH,
            codes,
        )
        self.assertIn(ValidationIssueCode.TARGET_RAW_TEXT_MISMATCH, codes)

    def test_validator_does_not_mutate_inputs(self) -> None:
        record = working_record(self.document)
        before_record = record.model_dump(mode="json")
        before_document = self.document.model_dump(mode="json")
        before_batch = self.batch.model_dump(mode="json")

        self.report(record)

        self.assertEqual(record.model_dump(mode="json"), before_record)
        self.assertEqual(self.document.model_dump(mode="json"), before_document)
        self.assertEqual(self.batch.model_dump(mode="json"), before_batch)

    def test_validator_accumulates_independent_errors_in_one_report(self) -> None:
        target = WorkingTarget(
            target_id="missing",
            target_kind=SemanticTargetKind.ELEMENT,
            element_ids=("missing",),
            element_orders=(0,),
            raw_text="missing",
            normalized_text="missing",
        )
        record = working_record(self.document, target=target).model_copy(
            update={"batch_id": "wrong-batch"}
        )
        record = self.with_source(record, language="vi")

        report = self.report(record)
        codes = {issue.code for issue in report.issues}

        self.assertFalse(report.is_valid)
        self.assertTrue(
            {
                ValidationIssueCode.SOURCE_LANGUAGE_MISMATCH,
                ValidationIssueCode.BATCH_ID_MISMATCH,
                ValidationIssueCode.TARGET_NOT_FOUND,
            }.issubset(codes)
        )


if __name__ == "__main__":
    unittest.main()
