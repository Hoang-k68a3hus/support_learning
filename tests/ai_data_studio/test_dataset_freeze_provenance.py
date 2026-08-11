from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_data_studio.datasets import (
    DatasetFreezeInvariantError,
    SemanticGoldFreezer,
)

from ._freeze_fixtures import compiled_gold_dataset, freeze_provenance


class SemanticGoldFreezeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset, self.split_manifest = compiled_gold_dataset()
        self.provenance = freeze_provenance()

    def test_declared_guideline_must_match_compiler_metadata(self) -> None:
        stale = self.provenance.model_copy(update={"guideline_version": "roles-v999"})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                DatasetFreezeInvariantError,
                "guideline_version",
            ):
                self._freeze(Path(directory), stale)

    def test_declared_policy_identity_must_match_compiler_metadata(self) -> None:
        stale = self.provenance.model_copy(
            update={"eligibility_policy_version": "999"}
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                DatasetFreezeInvariantError,
                "eligibility_policy_version",
            ):
                self._freeze(Path(directory), stale)

    def test_compiled_dataset_requires_validation_and_policy_hashes(self) -> None:
        metadata = dict(self.dataset.metadata)
        metadata.pop("validated_working_set_hash")
        unbound = self.dataset.model_copy(update={"metadata": metadata})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                DatasetFreezeInvariantError,
                "validated_working_set_hash",
            ):
                SemanticGoldFreezer().freeze(
                    dataset=unbound,
                    output_dir=Path(directory),
                    dataset_name="semantic-role",
                    dataset_version="0.1.0",
                    split_manifest=self.split_manifest,
                    provenance=self.provenance,
                )

    def _freeze(self, output_dir: Path, provenance):
        return SemanticGoldFreezer().freeze(
            dataset=self.dataset,
            output_dir=output_dir,
            dataset_name="semantic-role",
            dataset_version="0.1.0",
            split_manifest=self.split_manifest,
            provenance=provenance,
        )


if __name__ == "__main__":
    unittest.main()
