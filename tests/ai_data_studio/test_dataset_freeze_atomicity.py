from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_data_studio.datasets.freeze as freeze_module
from ai_data_studio.datasets import (
    DatasetFreezeVerificationError,
    DatasetFreezeWriteError,
    DatasetVersionAlreadyFrozenError,
    SemanticGoldFreezer,
)

from ._freeze_fixtures import compiled_gold_dataset, freeze_provenance


class SemanticGoldDatasetFreezeAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output_dir = Path(self.temporary_directory.name) / "frozen"
        self.dataset, self.split_manifest = compiled_gold_dataset()
        self.final_root = self.output_dir / "semantic-role" / "0.1.0"

    def test_split_write_failure_never_publishes_partial_release(self) -> None:
        original_writer = freeze_module.write_canonical_json

        def fail_on_dev(path: Path, payload: object) -> None:
            if path.name == "dev.json":
                raise OSError("simulated dev write failure")
            original_writer(path, payload)

        with patch(
            "ai_data_studio.datasets.freeze.write_canonical_json",
            side_effect=fail_on_dev,
        ):
            with self.assertRaisesRegex(
                DatasetFreezeWriteError,
                "dev write failure",
            ):
                self._freeze()

        self.assertFalse(self.final_root.exists())
        self.assertEqual(self._temporary_candidates(), ())

    def test_verification_failure_never_publishes_candidate(self) -> None:
        with patch(
            "ai_data_studio.datasets.freeze._verify_round_trip",
            side_effect=DatasetFreezeVerificationError(
                "simulated verification failure"
            ),
        ):
            with self.assertRaisesRegex(
                DatasetFreezeVerificationError,
                "verification failure",
            ):
                self._freeze()

        self.assertFalse(self.final_root.exists())
        self.assertEqual(self._temporary_candidates(), ())

    def test_concurrent_publication_collision_is_version_error(self) -> None:
        def collide(source: Path, destination: Path) -> None:
            destination.mkdir()
            raise FileExistsError("simulated concurrent freeze")

        with patch(
            "ai_data_studio.datasets.freeze.os.rename",
            side_effect=collide,
        ):
            with self.assertRaises(DatasetVersionAlreadyFrozenError):
                self._freeze()

        self.assertTrue(self.final_root.is_dir())
        self.assertEqual(tuple(self.final_root.iterdir()), ())
        self.assertEqual(self._temporary_candidates(), ())

    def _freeze(self):
        return SemanticGoldFreezer().freeze(
            dataset=self.dataset,
            output_dir=self.output_dir,
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            split_manifest=self.split_manifest,
            provenance=freeze_provenance(),
        )

    def _temporary_candidates(self) -> tuple[Path, ...]:
        dataset_root = self.output_dir / "semantic-role"
        if not dataset_root.exists():
            return ()
        return tuple(dataset_root.glob(".0.1.0.tmp-*"))


if __name__ == "__main__":
    unittest.main()
