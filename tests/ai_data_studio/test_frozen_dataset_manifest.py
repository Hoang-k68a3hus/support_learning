from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from ai_data_studio.datasets import (
    DatasetSplit,
    FreezePolicy,
    FrozenDatasetManifest,
    FrozenSplitArtifact,
    frozen_manifest_hash,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class FrozenDatasetManifestTests(unittest.TestCase):
    def test_manifest_accepts_portable_split_artifacts_and_exact_counts(
        self,
    ) -> None:
        manifest = self._manifest()

        self.assertEqual(manifest.train.filename, "train.json")
        self.assertEqual(manifest.document_count, 1)
        self.assertEqual(manifest.target_count, 2)
        self.assertEqual(manifest.annotation_count, 1)

    def test_split_filename_cannot_escape_release_directory(self) -> None:
        with self.assertRaises(ValidationError):
            FrozenSplitArtifact(
                split=DatasetSplit.TRAIN,
                filename="../train.json",
                content_hash=HASH_A,
                document_count=1,
                target_count=1,
                annotation_count=0,
            )

    def test_manifest_rejects_nonportable_identity_and_count_drift(self) -> None:
        values = self._manifest().model_dump(mode="python")
        values["dataset_name"] = "../semantic-role"
        with self.assertRaises(ValidationError):
            FrozenDatasetManifest.model_validate(values)

        values = self._manifest().model_dump(mode="python")
        values["target_count"] = 3
        with self.assertRaisesRegex(ValidationError, "total counts"):
            FrozenDatasetManifest.model_validate(values)

    def test_manifest_requires_timezone_aware_created_at(self) -> None:
        values = self._manifest().model_dump(mode="python")
        values["created_at"] = datetime(2026, 8, 10, 12, 0)
        with self.assertRaisesRegex(ValidationError, "timezone-aware"):
            FrozenDatasetManifest.model_validate(values)

    def test_manifest_hash_excludes_created_at_but_includes_release_inputs(
        self,
    ) -> None:
        manifest = self._manifest()
        later = manifest.model_copy(update={"created_at": NOW + timedelta(days=1)})
        next_version = manifest.model_copy(update={"dataset_version": "0.1.1"})

        self.assertEqual(
            frozen_manifest_hash(manifest),
            frozen_manifest_hash(later),
        )
        self.assertNotEqual(
            frozen_manifest_hash(manifest),
            frozen_manifest_hash(next_version),
        )

    def test_freeze_policy_requires_canonical_unique_split_order(self) -> None:
        with self.assertRaises(ValidationError):
            FreezePolicy(
                required_splits=(DatasetSplit.TEST, DatasetSplit.TRAIN)
            )
        with self.assertRaises(ValidationError):
            FreezePolicy(
                required_splits=(DatasetSplit.DEV, DatasetSplit.DEV)
            )

    @staticmethod
    def _manifest() -> FrozenDatasetManifest:
        train = FrozenSplitArtifact(
            split=DatasetSplit.TRAIN,
            filename="train.json",
            content_hash=HASH_A,
            document_count=1,
            target_count=2,
            annotation_count=1,
        )
        return FrozenDatasetManifest(
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            gold_schema_version="3",
            compiler_version="1",
            working_record_schema_version="1",
            split_manifest_schema_version="1",
            guideline_version="roles-v1",
            eligibility_policy_name="semantic-gold-strict",
            eligibility_policy_version="1",
            split_manifest_hash=HASH_B,
            source_corpus_hash=HASH_C,
            dataset_hash=HASH_A,
            train=train,
            document_count=1,
            target_count=2,
            annotation_count=1,
            created_at=NOW,
        )


if __name__ == "__main__":
    unittest.main()
