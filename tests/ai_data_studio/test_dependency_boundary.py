from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_UNDERSTANDING_ROOT = REPOSITORY_ROOT / "source_understanding"
DATA_STUDIO_SCHEMAS_ROOT = REPOSITORY_ROOT / "ai_data_studio" / "schemas"
DATA_STUDIO_REPOSITORIES_ROOT = (
    REPOSITORY_ROOT / "ai_data_studio" / "repositories"
)
DATA_STUDIO_DATASETS_ROOT = REPOSITORY_ROOT / "ai_data_studio" / "datasets"


class DataStudioDependencyBoundaryTests(unittest.TestCase):
    def test_source_understanding_never_imports_ai_data_studio(self) -> None:
        violations: list[str] = []
        for source_path in SOURCE_UNDERSTANDING_ROOT.rglob("*.py"):
            relative_path = source_path.relative_to(REPOSITORY_ROOT).as_posix()
            tree = ast.parse(source_path.read_text(encoding="utf-8"), relative_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported_names = (node.module or "",)
                else:
                    continue
                if any(
                    name == "ai_data_studio" or name.startswith("ai_data_studio.")
                    for name in imported_names
                ):
                    violations.append(f"{relative_path}:{node.lineno}")

        self.assertEqual(
            violations,
            [],
            "source_understanding must not import ai_data_studio",
        )

    def test_source_understanding_public_api_has_no_training_dataset_exports(self) -> None:
        import source_understanding.semantics as semantics

        forbidden_names = (
            "RoleClassifierTrainingDataset",
            "RoleClassifierTrainingExample",
            "RoleClassifierDatasetSplit",
            "RoleClassifierLabelSource",
            "RoleClassifierTeacher",
            "load_role_classifier_training_dataset",
            "WorkingRecordValidator",
            "WorkingBatchValidator",
            "ValidationReport",
            "working_element_snapshot_hash",
        )

        self.assertEqual(
            tuple(name for name in forbidden_names if hasattr(semantics, name)),
            (),
        )

    def test_data_studio_schemas_do_not_import_repositories(self) -> None:
        violations: list[str] = []
        for source_path in DATA_STUDIO_SCHEMAS_ROOT.rglob("*.py"):
            relative_path = source_path.relative_to(REPOSITORY_ROOT).as_posix()
            tree = ast.parse(source_path.read_text(encoding="utf-8"), relative_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported_names = (node.module or "",)
                else:
                    continue
                if any(
                    name == "ai_data_studio.repositories"
                    or name.startswith("ai_data_studio.repositories.")
                    for name in imported_names
                ):
                    violations.append(f"{relative_path}:{node.lineno}")

        self.assertEqual(violations, [])

    def test_repositories_do_not_import_orchestration_layers(self) -> None:
        forbidden_prefixes = (
            "ai_data_studio.datasets",
            "ai_data_studio.training",
            "ai_data_studio.validation",
            "source_understanding.evaluation",
            "source_understanding.pipeline",
            "source_understanding.semantics",
        )
        violations: list[str] = []
        for source_path in DATA_STUDIO_REPOSITORIES_ROOT.rglob("*.py"):
            relative_path = source_path.relative_to(REPOSITORY_ROOT).as_posix()
            tree = ast.parse(source_path.read_text(encoding="utf-8"), relative_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported_names = (node.module or "",)
                else:
                    continue
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for name in imported_names
                    for prefix in forbidden_prefixes
                ):
                    violations.append(f"{relative_path}:{node.lineno}")

        self.assertEqual(violations, [])

    def test_generic_datasets_do_not_import_training_projections(self) -> None:
        violations: list[str] = []
        for source_path in DATA_STUDIO_DATASETS_ROOT.rglob("*.py"):
            relative_path = source_path.relative_to(REPOSITORY_ROOT).as_posix()
            tree = ast.parse(source_path.read_text(encoding="utf-8"), relative_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported_names = (node.module or "",)
                else:
                    continue
                if any(
                    name == "ai_data_studio.training"
                    or name.startswith("ai_data_studio.training.")
                    for name in imported_names
                ):
                    violations.append(f"{relative_path}:{node.lineno}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
