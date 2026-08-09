from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_data_studio.datasets import (
    DatasetSplit,
    FreezePolicy,
    FrozenDatasetVerificationIssueCode,
    SemanticGoldFreezer,
    verify_frozen_dataset,
)

from ._freeze_fixtures import compiled_gold_dataset, freeze_provenance


class FrozenDatasetVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name) / "frozen"
        dataset, split_manifest = compiled_gold_dataset()
        SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
        )
        self.release_root = self.output_dir / "semantic-role" / "0.1.0"

    def test_tampered_semantic_case_is_rejected_by_split_hash(self) -> None:
        path = self.release_root / "test.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cases"][0]["language"] = "fr"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        report = verify_frozen_dataset(self.release_root)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.SPLIT_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_tampered_dataset_hash_is_rejected(self) -> None:
        path = self.release_root / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["dataset_hash"] = "sha256:" + "f" * 64
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        report = verify_frozen_dataset(self.release_root)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.DATASET_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_deleted_split_file_is_rejected(self) -> None:
        (self.release_root / "dev.json").unlink()

        report = verify_frozen_dataset(self.release_root)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.SPLIT_FILE_MISSING,
            {issue.code for issue in report.issues},
        )

    def test_tampered_manifest_count_is_rejected(self) -> None:
        path = self.release_root / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["target_count"] += 1
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        report = verify_frozen_dataset(self.release_root)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.MANIFEST_COUNT_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_unreferenced_split_file_is_rejected(self) -> None:
        # This release declares every split, so use a second release with only DEV.
        temporary = Path(self.temporary_directory.name) / "pilot"
        dataset, split_manifest = compiled_gold_dataset((DatasetSplit.DEV,))
        SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=temporary,
            dataset_name="semantic-role",
            dataset_version="pilot-1",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
            policy=FreezePolicy(required_splits=(DatasetSplit.DEV,)),
        )
        release = temporary / "semantic-role" / "pilot-1"
        (release / "test.json").write_text("{}", encoding="utf-8")

        report = verify_frozen_dataset(release)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.SPLIT_FILE_UNEXPECTED,
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
