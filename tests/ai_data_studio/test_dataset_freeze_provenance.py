from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_data_studio.datasets import (
    DatasetFreezeInvariantError,
    FrozenDatasetVerificationIssueCode,
    SemanticGoldFreezer,
    verify_frozen_dataset,
)

from ._freeze_fixtures import compiled_gold_dataset, freeze_provenance


class FrozenDatasetProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name) / "frozen"

    def test_freeze_rejects_misdeclared_guideline(self) -> None:
        dataset, split_manifest = compiled_gold_dataset()
        provenance = freeze_provenance().model_copy(
            update={"guideline_version": "roles-v999"}
        )

        with self.assertRaisesRegex(
            DatasetFreezeInvariantError,
            "guideline_versions",
        ):
            SemanticGoldFreezer().freeze(
                dataset=dataset,
                output_dir=self.output_dir,
                dataset_name="semantic-role",
                dataset_version="bad-guideline",
                split_manifest=split_manifest,
                provenance=provenance,
            )

    def test_freeze_rejects_misdeclared_policy_identity(self) -> None:
        dataset, split_manifest = compiled_gold_dataset()
        provenance = freeze_provenance().model_copy(
            update={"eligibility_policy_version": "999"}
        )

        with self.assertRaisesRegex(
            DatasetFreezeInvariantError,
            "eligibility_policy_version",
        ):
            SemanticGoldFreezer().freeze(
                dataset=dataset,
                output_dir=self.output_dir,
                dataset_name="semantic-role",
                dataset_version="bad-policy",
                split_manifest=split_manifest,
                provenance=provenance,
            )

    def test_verifier_rejects_manifest_policy_tampering(self) -> None:
        dataset, split_manifest = compiled_gold_dataset()
        SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
        )
        release_root = self.output_dir / "semantic-role" / "0.1.0"
        manifest_path = release_root / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["eligibility_policy_version"] = "999"
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        report = verify_frozen_dataset(release_root)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.DATASET_IDENTITY_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_verifier_rejects_policy_metadata_tampering(self) -> None:
        dataset, split_manifest = compiled_gold_dataset()
        SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
        )
        release_root = self.output_dir / "semantic-role" / "0.1.0"
        test_path = release_root / "test.json"
        payload = json.loads(test_path.read_text(encoding="utf-8"))
        payload["metadata"]["eligibility_policy"]["require_review"] = False
        test_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        report = verify_frozen_dataset(release_root)

        self.assertFalse(report.valid)
        self.assertIn(
            FrozenDatasetVerificationIssueCode.DATASET_IDENTITY_MISMATCH,
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
