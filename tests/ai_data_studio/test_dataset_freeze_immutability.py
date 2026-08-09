from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_data_studio.datasets import (
    DatasetVersionAlreadyFrozenError,
    SemanticGoldFreezer,
)

from ._freeze_fixtures import compiled_gold_dataset, freeze_provenance


class SemanticGoldDatasetFreezeImmutabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name) / "frozen"
        self.dataset, self.split_manifest = compiled_gold_dataset()
        self.freezer = SemanticGoldFreezer()

    def test_existing_version_is_rejected_without_overwriting_any_file(
        self,
    ) -> None:
        self._freeze("0.1.0")
        release_root = self.output_dir / "semantic-role" / "0.1.0"
        before = {
            path.name: path.read_bytes()
            for path in release_root.iterdir()
            if path.is_file()
        }

        with self.assertRaises(DatasetVersionAlreadyFrozenError):
            self._freeze("0.1.0")

        after = {
            path.name: path.read_bytes()
            for path in release_root.iterdir()
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_different_version_can_freeze_same_semantic_content(self) -> None:
        first = self._freeze("0.1.0")
        second = self._freeze("0.1.1")

        self.assertEqual(first.dataset_hash, second.dataset_hash)
        self.assertTrue(
            (self.output_dir / "semantic-role" / "0.1.0").is_dir()
        )
        self.assertTrue(
            (self.output_dir / "semantic-role" / "0.1.1").is_dir()
        )

    def test_existing_non_directory_version_path_is_also_immutable(self) -> None:
        dataset_root = self.output_dir / "semantic-role"
        dataset_root.mkdir(parents=True)
        version_path = dataset_root / "0.1.0"
        version_path.write_text("reserved", encoding="utf-8")

        with self.assertRaises(DatasetVersionAlreadyFrozenError):
            self._freeze("0.1.0")

        self.assertEqual(version_path.read_text(encoding="utf-8"), "reserved")

    def _freeze(self, version: str):
        return self.freezer.freeze(
            dataset=self.dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version=version,
            split_manifest=self.split_manifest,
            provenance=freeze_provenance(),
        )


if __name__ == "__main__":
    unittest.main()
