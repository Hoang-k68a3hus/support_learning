from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CleanImportTests(unittest.TestCase):
    def test_public_packages_import_in_fresh_processes(self) -> None:
        for module_name in (
            "ai_data_studio.validation",
            "ai_data_studio.datasets",
            "ai_data_studio.training.role_classifier",
        ):
            with self.subTest(module=module_name):
                completed = subprocess.run(
                    [sys.executable, "-c", f"import {module_name}"],
                    cwd=REPOSITORY_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stderr or completed.stdout,
                )


if __name__ == "__main__":
    unittest.main()
