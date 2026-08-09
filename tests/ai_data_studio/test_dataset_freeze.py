from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_data_studio.datasets import (
    DatasetFreezeInvariantError,
    DatasetSplit,
    SemanticGoldFreezer,
    semantic_gold_dataset_hash,
    semantic_gold_split_hash,
    verify_frozen_dataset,
)
from source_understanding.evaluation import (
    GoldSemanticElement,
    SemanticGoldDataset,
    semantic_element_snapshot_hash,
)

from ._freeze_fixtures import (
    compiled_gold_dataset,
    freeze_policy,
    freeze_provenance,
)


class SemanticGoldDatasetFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name) / "frozen"

    def test_freeze_creates_manifest_and_exact_split_artifacts(self) -> None:
        dataset, split_manifest = compiled_gold_dataset()
        manifest = SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
        )
        release_root = self.output_dir / "semantic-role" / "0.1.0"

        self.assertEqual(
            {path.name for path in release_root.iterdir()},
            {"manifest.json", "train.json", "dev.json", "test.json"},
        )
        self.assertEqual(manifest.dataset_hash, semantic_gold_dataset_hash(dataset))
        self.assertEqual(manifest.document_count, 3)
        self.assertEqual(manifest.target_count, 3)
        self.assertEqual(manifest.annotation_count, 3)
        self.assertTrue(verify_frozen_dataset(release_root).valid)

        for split in DatasetSplit:
            loaded = SemanticGoldDataset.model_validate_json(
                (release_root / f"{split.value}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(loaded.cases), 1)
            self.assertTrue(
                all(case.split.value == split.value for case in loaded.cases)
            )
            self.assertEqual(
                manifest.artifact_for(split).content_hash,
                semantic_gold_split_hash(loaded, split=split),
            )

    def test_missing_split_is_not_written_and_policy_controls_requirement(
        self,
    ) -> None:
        dataset, split_manifest = compiled_gold_dataset((DatasetSplit.DEV,))
        manifest = SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="pilot-1",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
            policy=freeze_policy(DatasetSplit.DEV),
        )
        release_root = self.output_dir / "semantic-role" / "pilot-1"

        self.assertIsNone(manifest.train)
        self.assertIsNotNone(manifest.dev)
        self.assertIsNone(manifest.test)
        self.assertFalse((release_root / "train.json").exists())
        self.assertFalse((release_root / "test.json").exists())

    def test_required_split_and_compiler_manifest_provenance_fail_closed(
        self,
    ) -> None:
        dataset, split_manifest = compiled_gold_dataset((DatasetSplit.DEV,))
        with self.assertRaisesRegex(
            DatasetFreezeInvariantError,
            "missing required frozen splits",
        ):
            SemanticGoldFreezer().freeze(
                dataset=dataset,
                output_dir=self.output_dir,
                dataset_name="semantic-role",
                dataset_version="0.1.0",
                split_manifest=split_manifest,
                provenance=freeze_provenance(),
            )

        changed_manifest = split_manifest.model_copy(
            update={"dataset_version": "different-split-release"}
        )
        with self.assertRaisesRegex(
            DatasetFreezeInvariantError,
            "split_manifest_hash",
        ):
            SemanticGoldFreezer().freeze(
                dataset=dataset,
                output_dir=self.output_dir,
                dataset_name="semantic-role",
                dataset_version="0.1.0",
                split_manifest=changed_manifest,
                provenance=freeze_provenance(),
                policy=freeze_policy(DatasetSplit.DEV),
            )

    def test_unicode_source_text_round_trips_without_escaping_corruption(
        self,
    ) -> None:
        dataset, split_manifest = compiled_gold_dataset((DatasetSplit.TEST,))
        unicode_text = "Thuật toán tìm kiếm theo chiều sâu"
        payload = dataset.model_dump(mode="python")
        elements = list(payload["cases"][0]["elements"])
        elements[0]["raw_text"] = unicode_text
        elements[0]["normalized_text"] = unicode_text
        gold_elements = tuple(
            GoldSemanticElement.model_validate(element) for element in elements
        )
        payload["cases"][0]["elements"] = gold_elements
        payload["cases"][0]["element_snapshot_hash"] = (
            semantic_element_snapshot_hash(gold_elements)
        )
        unicode_dataset = SemanticGoldDataset.model_validate(payload)

        SemanticGoldFreezer().freeze(
            dataset=unicode_dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="unicode-1",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
            policy=freeze_policy(DatasetSplit.TEST),
        )
        path = self.output_dir / "semantic-role" / "unicode-1" / "test.json"
        serialized = path.read_text(encoding="utf-8")
        loaded = SemanticGoldDataset.model_validate_json(serialized)

        self.assertIn(unicode_text, serialized)
        self.assertEqual(loaded.cases[0].elements[0].raw_text, unicode_text)

    def test_all_negative_targets_survive_round_trip(self) -> None:
        dataset, split_manifest = compiled_gold_dataset(
            (DatasetSplit.TEST,),
            all_negative=True,
        )
        SemanticGoldFreezer().freeze(
            dataset=dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="negative-1",
            split_manifest=split_manifest,
            provenance=freeze_provenance(),
            policy=freeze_policy(DatasetSplit.TEST),
        )
        path = self.output_dir / "semantic-role" / "negative-1" / "test.json"
        loaded = SemanticGoldDataset.model_validate_json(
            path.read_text(encoding="utf-8")
        )

        self.assertEqual(loaded.cases[0].annotations, ())
        self.assertEqual(len(loaded.cases[0].evaluation_scopes), 1)


if __name__ == "__main__":
    unittest.main()
