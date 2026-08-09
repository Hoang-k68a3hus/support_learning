from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_data_studio.repositories import JsonlWorkingRecordRepository
from ai_data_studio.repositories.errors import RepositoryWriteError

from ._repository_fixtures import make_repository_record


class JsonlWorkingRecordRepositoryAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "records.jsonl"
        self.repository = JsonlWorkingRecordRepository(self.path)
        self.original = make_repository_record()
        self.repository.save(self.original)
        self.original_bytes = self.path.read_bytes()

    def test_replace_failure_preserves_original_and_cleans_temporary_file(self) -> None:
        added = make_repository_record(
            record_id="record-2",
            hash_token="c",
            snapshot_token="d",
            target_order=1,
        )

        with patch(
            "ai_data_studio.repositories.jsonl.os.replace",
            side_effect=OSError("simulated replace failure"),
        ):
            with self.assertRaisesRegex(RepositoryWriteError, "replace failure"):
                self.repository.save(added)

        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(tuple(self.path.parent.glob(".records.jsonl.*.tmp")), ())
        self.assertEqual(tuple(self.repository.iter_all()), (self.original,))

    def test_serialization_failure_preserves_original_without_partial_write(
        self,
    ) -> None:
        added = make_repository_record(
            record_id="record-2",
            hash_token="c",
            snapshot_token="d",
            target_order=1,
        )

        with patch(
            "ai_data_studio.repositories.jsonl.serialize_working_record",
            side_effect=ValueError("simulated serialization failure"),
        ):
            with self.assertRaisesRegex(RepositoryWriteError, "serialization failure"):
                self.repository.save_many((added,))

        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(tuple(self.path.parent.glob(".records.jsonl.*.tmp")), ())
        self.assertEqual(tuple(self.repository.iter_all()), (self.original,))


if __name__ == "__main__":
    unittest.main()
