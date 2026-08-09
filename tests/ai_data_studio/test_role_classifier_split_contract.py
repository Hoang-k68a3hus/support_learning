from __future__ import annotations

import ast
import unittest
from pathlib import Path

from ai_data_studio.datasets import DatasetSplit
from ai_data_studio.schemas import SemanticWorkingRecord, WorkingBatch
from ai_data_studio.training.role_classifier import (
    RoleClassifierDatasetSplit,
    RoleClassifierTrainingExample,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RoleClassifierSplitContractTests(unittest.TestCase):
    def test_role_classifier_uses_generic_dataset_split_with_compatibility_alias(self) -> None:
        self.assertIs(RoleClassifierDatasetSplit, DatasetSplit)
        self.assertIs(
            RoleClassifierTrainingExample.model_fields["split"].annotation,
            DatasetSplit,
        )

    def test_working_record_and_batch_do_not_own_dataset_split(self) -> None:
        self.assertNotIn("split", SemanticWorkingRecord.model_fields)
        self.assertNotIn("split", WorkingBatch.model_fields)

    def test_generic_dataset_package_does_not_import_role_classifier(self) -> None:
        violations: list[str] = []
        datasets_root = REPOSITORY_ROOT / "ai_data_studio" / "datasets"
        for path in datasets_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    name = node.module or ""
                elif isinstance(node, ast.Import):
                    name = ",".join(alias.name for alias in node.names)
                else:
                    continue
                if "role_classifier" in name:
                    violations.append(f"{path.name}:{node.lineno}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
