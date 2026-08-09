from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from ai_data_studio.datasets import (
    DatasetSplit,
    DatasetSplitManifest,
    SplitAssignment,
    dataset_split_manifest_hash,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def manifest(**updates: object) -> DatasetSplitManifest:
    values: dict[str, object] = {
        "name": "semantic-role-splits",
        "dataset_version": "semantic-role-splits-v1",
        "assignments": (
            SplitAssignment(split_group_id="group-a", split=DatasetSplit.TRAIN),
            SplitAssignment(split_group_id="group-b", split=DatasetSplit.TEST),
        ),
        "created_by": "operator-1",
        "created_at": NOW,
    }
    values.update(updates)
    return DatasetSplitManifest.model_validate(values)


class DatasetSplitManifestTests(unittest.TestCase):
    def test_valid_manifest_is_immutable_and_canonically_ordered(self) -> None:
        value = manifest()
        self.assertEqual(
            tuple(item.split_group_id for item in value.assignments),
            ("group-a", "group-b"),
        )
        self.assertTrue(dataset_split_manifest_hash(value).startswith("sha256:"))

    def test_duplicate_split_group_id_is_rejected_locally(self) -> None:
        assignments = (
            SplitAssignment(split_group_id="group-a", split=DatasetSplit.TRAIN),
            SplitAssignment(split_group_id="group-a", split=DatasetSplit.TEST),
        )
        with self.assertRaisesRegex(ValidationError, "must be unique"):
            manifest(assignments=assignments)

    def test_assignments_must_use_lexical_group_order(self) -> None:
        assignments = (
            SplitAssignment(split_group_id="group-b", split=DatasetSplit.TEST),
            SplitAssignment(split_group_id="group-a", split=DatasetSplit.TRAIN),
        )
        with self.assertRaisesRegex(ValidationError, "lexical"):
            manifest(assignments=assignments)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unsupported"):
            manifest(schema_version="2")

    def test_blank_name_and_dataset_version_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            manifest(name=" ")
        with self.assertRaises(ValidationError):
            manifest(dataset_version=" ")

    def test_naive_created_at_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "timezone-aware"):
            manifest(created_at=datetime(2026, 8, 10, 12, 0))

    def test_manifest_content_hash_is_assignment_order_independent(self) -> None:
        canonical = manifest()
        reordered = canonical.model_copy(
            update={"assignments": tuple(reversed(canonical.assignments))}
        )

        self.assertEqual(
            dataset_split_manifest_hash(canonical),
            dataset_split_manifest_hash(reordered),
        )

    def test_manifest_content_hash_excludes_audit_metadata(self) -> None:
        first = manifest()
        second = manifest(
            created_by="operator-2",
            created_at=NOW + timedelta(days=1),
            metadata={"ticket": "DATA-42"},
        )

        self.assertEqual(
            dataset_split_manifest_hash(first),
            dataset_split_manifest_hash(second),
        )

    def test_manifest_content_hash_tracks_split_contract_content(self) -> None:
        baseline = manifest()
        renamed = manifest(name="semantic-role-splits-renamed")
        versioned = manifest(dataset_version="semantic-role-splits-v2")
        reassigned = manifest(
            assignments=(
                SplitAssignment(
                    split_group_id="group-a",
                    split=DatasetSplit.DEV,
                ),
                SplitAssignment(
                    split_group_id="group-b",
                    split=DatasetSplit.TEST,
                ),
            )
        )

        baseline_hash = dataset_split_manifest_hash(baseline)
        self.assertNotEqual(baseline_hash, dataset_split_manifest_hash(renamed))
        self.assertNotEqual(baseline_hash, dataset_split_manifest_hash(versioned))
        self.assertNotEqual(baseline_hash, dataset_split_manifest_hash(reassigned))


if __name__ == "__main__":
    unittest.main()
