from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ai_data_studio.datasets import (
    DatasetSplit,
    DatasetSplitManifest,
    SplitAssignment,
)
from ai_data_studio.schemas import (
    SemanticWorkingRecord,
    WorkingSourceSnapshot,
    WorkingTarget,
)
from ai_data_studio.validation import (
    DatasetSplitValidator,
    InvalidDatasetSplitError,
    ValidationIssueCode,
    resolve_record_splits,
)
from source_understanding.schemas.document import SemanticAnnotationType
from source_understanding.semantics.provider import SemanticTargetKind


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
SNAPSHOT_HASH = "sha256:" + "f" * 64


def split_record(
    *,
    record_id: str,
    document_id: str,
    content_token: str,
    source_family_id: str,
    split_group_id: str,
    target_order: int,
    target_id: str | None = None,
) -> SemanticWorkingRecord:
    return SemanticWorkingRecord(
        record_id=record_id,
        batch_id="batch-1",
        source=WorkingSourceSnapshot(
            document_id=document_id,
            content_hash="sha256:" + content_token * 64,
            element_snapshot_hash=SNAPSHOT_HASH,
            language="en",
            source_family_id=source_family_id,
            split_group_id=split_group_id,
        ),
        target=WorkingTarget(
            target_id=target_id or f"element-{target_order}-{record_id}",
            target_kind=SemanticTargetKind.ELEMENT,
            element_ids=(f"element-{target_order}",),
            element_orders=(target_order,),
            raw_text=f"Text {target_order}",
            normalized_text=f"Text {target_order}",
        ),
        evaluated_types=(SemanticAnnotationType.DEFINITION,),
    )


def split_manifest(*assignments: tuple[str, DatasetSplit]) -> DatasetSplitManifest:
    ordered = tuple(
        SplitAssignment(split_group_id=group_id, split=split)
        for group_id, split in sorted(assignments)
    )
    return DatasetSplitManifest(
        name="semantic-role-splits",
        dataset_version="splits-v1",
        assignments=ordered,
        created_by="operator-1",
        created_at=NOW,
    )


def codes(records, manifest) -> tuple[ValidationIssueCode, ...]:
    report = DatasetSplitValidator().validate(records=records, manifest=manifest)
    return tuple(issue.code for issue in report.issues)


class DatasetSplitLeakageValidationTests(unittest.TestCase):
    def test_all_record_groups_assigned_passes_and_resolves_deterministically(self) -> None:
        first = split_record(
            record_id="record-b",
            document_id="doc-b",
            content_token="b",
            source_family_id="family-b",
            split_group_id="group-b",
            target_order=1,
        )
        second = split_record(
            record_id="record-a",
            document_id="doc-a",
            content_token="a",
            source_family_id="family-a",
            split_group_id="group-a",
            target_order=0,
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.TRAIN),
            ("group-b", DatasetSplit.TEST),
        )

        report = DatasetSplitValidator().validate(
            records=(first, second),
            manifest=manifest,
        )
        resolution = resolve_record_splits(
            records=(first, second),
            manifest=manifest,
        )

        self.assertTrue(report.is_valid)
        self.assertEqual(report.issues, ())
        self.assertEqual(
            resolution,
            {
                "record-a": DatasetSplit.TRAIN,
                "record-b": DatasetSplit.TEST,
            },
        )

    def test_record_group_missing_from_manifest_is_error(self) -> None:
        record = split_record(
            record_id="record-1",
            document_id="doc-1",
            content_token="a",
            source_family_id="family-1",
            split_group_id="missing-group",
            target_order=0,
        )
        manifest = split_manifest(("other-group", DatasetSplit.TRAIN))

        report = DatasetSplitValidator().validate(
            records=(record,),
            manifest=manifest,
        )

        self.assertFalse(report.is_valid)
        self.assertIn(
            ValidationIssueCode.SPLIT_GROUP_UNASSIGNED,
            codes((record,), manifest),
        )
        self.assertIn(ValidationIssueCode.SPLIT_GROUP_UNKNOWN, codes((record,), manifest))
        with self.assertRaises(InvalidDatasetSplitError) as caught:
            resolve_record_splits(records=(record,), manifest=manifest)
        self.assertFalse(caught.exception.report.is_valid)
        self.assertIn(
            ValidationIssueCode.SPLIT_GROUP_UNASSIGNED,
            tuple(issue.code for issue in caught.exception.report.errors),
        )

    def test_manifest_group_without_loaded_record_is_warning(self) -> None:
        manifest = split_manifest(("future-group", DatasetSplit.TEST))
        report = DatasetSplitValidator().validate(records=(), manifest=manifest)

        self.assertTrue(report.is_valid)
        self.assertEqual(
            tuple(issue.code for issue in report.warnings),
            (ValidationIssueCode.SPLIT_GROUP_UNKNOWN,),
        )
        self.assertEqual(resolve_record_splits(records=(), manifest=manifest), {})

    def test_duplicate_record_id_is_error(self) -> None:
        first = split_record(
            record_id="duplicate",
            document_id="doc-a",
            content_token="a",
            source_family_id="family-a",
            split_group_id="group-a",
            target_order=0,
        )
        second = split_record(
            record_id="duplicate",
            document_id="doc-b",
            content_token="b",
            source_family_id="family-b",
            split_group_id="group-a",
            target_order=1,
        )
        manifest = split_manifest(("group-a", DatasetSplit.TRAIN))

        self.assertIn(
            ValidationIssueCode.RECORD_ID_DUPLICATE,
            codes((first, second), manifest),
        )

    def test_same_family_same_group_same_split_passes(self) -> None:
        first = split_record(
            record_id="record-1",
            document_id="doc-1",
            content_token="a",
            source_family_id="family-shared",
            split_group_id="group-a",
            target_order=0,
        )
        second = split_record(
            record_id="record-2",
            document_id="doc-2",
            content_token="b",
            source_family_id="family-shared",
            split_group_id="group-a",
            target_order=1,
        )
        manifest = split_manifest(("group-a", DatasetSplit.TRAIN))

        self.assertEqual(codes((first, second), manifest), ())

    def test_same_family_multiple_groups_is_error_even_in_same_split(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="doc-1",
                content_token="a",
                source_family_id="family-shared",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="doc-2",
                content_token="b",
                source_family_id="family-shared",
                split_group_id="group-b",
                target_order=1,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.TRAIN),
            ("group-b", DatasetSplit.TRAIN),
        )

        found = codes(records, manifest)
        self.assertIn(
            ValidationIssueCode.SOURCE_FAMILY_CROSSES_SPLIT_GROUP,
            found,
        )
        self.assertNotIn(ValidationIssueCode.SOURCE_FAMILY_CROSSES_SPLIT, found)

    def test_same_family_train_and_test_reports_both_safety_layers(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="doc-1",
                content_token="a",
                source_family_id="family-shared",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="doc-2",
                content_token="b",
                source_family_id="family-shared",
                split_group_id="group-b",
                target_order=1,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.TRAIN),
            ("group-b", DatasetSplit.TEST),
        )

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.SOURCE_FAMILY_CROSSES_SPLIT_GROUP, found)
        self.assertIn(ValidationIssueCode.SOURCE_FAMILY_CROSSES_SPLIT, found)

    def test_same_content_hash_with_different_document_ids_cannot_cross_split(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="upload-1",
                content_token="a",
                source_family_id="family-1",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="upload-2",
                content_token="a",
                source_family_id="family-2",
                split_group_id="group-b",
                target_order=1,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.TRAIN),
            ("group-b", DatasetSplit.TEST),
        )

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.CONTENT_HASH_CROSSES_SPLIT_GROUP, found)
        self.assertIn(ValidationIssueCode.CONTENT_HASH_CROSSES_SPLIT, found)

    def test_same_content_hash_cannot_cross_groups_inside_one_split(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="upload-1",
                content_token="a",
                source_family_id="family-1",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="upload-2",
                content_token="a",
                source_family_id="family-2",
                split_group_id="group-b",
                target_order=1,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.TRAIN),
            ("group-b", DatasetSplit.TRAIN),
        )

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.CONTENT_HASH_CROSSES_SPLIT_GROUP, found)
        self.assertNotIn(ValidationIssueCode.CONTENT_HASH_CROSSES_SPLIT, found)

    def test_same_document_id_cannot_cross_group_or_split(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="doc-shared",
                content_token="a",
                source_family_id="family-1",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="doc-shared",
                content_token="b",
                source_family_id="family-2",
                split_group_id="group-b",
                target_order=1,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.DEV),
            ("group-b", DatasetSplit.TEST),
        )

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.DOCUMENT_ID_CROSSES_SPLIT_GROUP, found)
        self.assertIn(ValidationIssueCode.DOCUMENT_ID_CROSSES_SPLIT, found)

    def test_same_document_id_cannot_cross_groups_inside_one_split(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="doc-shared",
                content_token="a",
                source_family_id="family-1",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="doc-shared",
                content_token="b",
                source_family_id="family-2",
                split_group_id="group-b",
                target_order=1,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.DEV),
            ("group-b", DatasetSplit.DEV),
        )

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.DOCUMENT_ID_CROSSES_SPLIT_GROUP, found)
        self.assertNotIn(ValidationIssueCode.DOCUMENT_ID_CROSSES_SPLIT, found)

    def test_same_physical_target_duplicate_in_same_split_is_error(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="doc-1",
                content_token="a",
                source_family_id="family-1",
                split_group_id="group-a",
                target_order=0,
                target_id="runtime-id-1",
            ),
            split_record(
                record_id="record-2",
                document_id="doc-2",
                content_token="a",
                source_family_id="family-2",
                split_group_id="group-a",
                target_order=0,
                target_id="runtime-id-2",
            ),
        )
        manifest = split_manifest(("group-a", DatasetSplit.TRAIN))

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.SOURCE_TARGET_DUPLICATE, found)
        self.assertNotIn(ValidationIssueCode.SOURCE_TARGET_CROSSES_SPLIT, found)

    def test_same_physical_target_across_split_uses_cross_split_code(self) -> None:
        records = (
            split_record(
                record_id="record-1",
                document_id="doc-1",
                content_token="a",
                source_family_id="family-1",
                split_group_id="group-a",
                target_order=0,
            ),
            split_record(
                record_id="record-2",
                document_id="doc-2",
                content_token="a",
                source_family_id="family-2",
                split_group_id="group-b",
                target_order=0,
            ),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.TRAIN),
            ("group-b", DatasetSplit.TEST),
        )

        found = codes(records, manifest)
        self.assertIn(ValidationIssueCode.SOURCE_TARGET_CROSSES_SPLIT, found)
        self.assertNotIn(ValidationIssueCode.SOURCE_TARGET_DUPLICATE, found)

    def test_different_targets_same_document_same_split_pass(self) -> None:
        first = split_record(
            record_id="record-1",
            document_id="doc-shared",
            content_token="a",
            source_family_id="family-shared",
            split_group_id="group-a",
            target_order=0,
        )
        second = split_record(
            record_id="record-2",
            document_id="doc-shared",
            content_token="a",
            source_family_id="family-shared",
            split_group_id="group-a",
            target_order=1,
        )
        manifest = split_manifest(("group-a", DatasetSplit.TRAIN))

        self.assertEqual(codes((first, second), manifest), ())

    def test_minimal_pair_families_in_one_group_resolve_together(self) -> None:
        original = split_record(
            record_id="original",
            document_id="doc-original",
            content_token="a",
            source_family_id="family-original",
            split_group_id="minimal-pair-group",
            target_order=0,
        )
        derived = split_record(
            record_id="derived",
            document_id="doc-derived",
            content_token="b",
            source_family_id="family-derived",
            split_group_id="minimal-pair-group",
            target_order=1,
        )
        manifest = split_manifest(("minimal-pair-group", DatasetSplit.TEST))

        resolution = resolve_record_splits(
            records=(original, derived),
            manifest=manifest,
        )

        self.assertEqual(
            set(resolution.values()),
            {DatasetSplit.TEST},
        )


if __name__ == "__main__":
    unittest.main()
