from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_data_studio.repositories import (
    JsonlWorkingRecordRepository,
    RepositoryCorruptionError,
)
from ai_data_studio.repositories.errors import RepositoryDuplicateRecordError
from ai_data_studio.repositories.serialization import serialize_working_record

from ._repository_fixtures import make_repository_record


class JsonlWorkingRecordRepositoryCorruptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "records.jsonl"
        self.repository = JsonlWorkingRecordRepository(self.path)

    def test_invalid_json_line_is_rejected_with_file_and_line(self) -> None:
        self.path.write_text('{"record_id":', encoding="utf-8")

        with self.assertRaises(RepositoryCorruptionError) as caught:
            tuple(self.repository.iter_all())

        self.assertEqual(caught.exception.path, self.path)
        self.assertEqual(caught.exception.line_number, 1)
        self.assertIn(str(self.path), str(caught.exception))
        self.assertIn("line 1", str(caught.exception))

    def test_unsupported_schema_version_is_rejected(self) -> None:
        payload = make_repository_record().model_dump(mode="json")
        payload["schema_version"] = "999"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            RepositoryCorruptionError,
            "unsupported working record schema_version",
        ):
            tuple(self.repository.iter_all())

    def test_duplicate_record_id_in_file_is_rejected_instead_of_last_wins(self) -> None:
        line = serialize_working_record(make_repository_record())
        self.path.write_text(f"{line}\n{line}\n", encoding="utf-8")

        with self.assertRaises(RepositoryDuplicateRecordError) as caught:
            tuple(self.repository.iter_all())

        self.assertEqual(caught.exception.record_id, "record-1")
        self.assertEqual(caught.exception.line_number, 2)
        self.assertIn("first seen at line 1", str(caught.exception))

    def test_malformed_record_reports_record_id_and_underlying_path(self) -> None:
        payload = make_repository_record().model_dump(mode="json")
        payload["target"]["element_orders"] = []
        valid = serialize_working_record(
            make_repository_record(
                record_id="record-valid",
                hash_token="c",
                snapshot_token="d",
            )
        )
        self.path.write_text(
            valid + "\n" + json.dumps(payload, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(RepositoryCorruptionError) as caught:
            tuple(self.repository.iter_all())

        self.assertEqual(caught.exception.line_number, 2)
        self.assertEqual(caught.exception.record_id, "record-1")
        self.assertIn("target.element_orders", str(caught.exception))

    def test_blank_line_is_corruption_but_one_trailing_newline_is_valid(self) -> None:
        line = serialize_working_record(make_repository_record())
        self.path.write_text(line + "\n", encoding="utf-8")
        self.assertEqual(len(tuple(self.repository.iter_all())), 1)

        self.path.write_text(line + "\n\n", encoding="utf-8")
        with self.assertRaisesRegex(RepositoryCorruptionError, "blank line"):
            tuple(self.repository.iter_all())

    def test_invalid_utf8_and_non_finite_json_are_rejected(self) -> None:
        with self.subTest(corruption="utf8"):
            self.path.write_bytes(b"\xff\n")
            with self.assertRaisesRegex(RepositoryCorruptionError, "UTF-8"):
                tuple(self.repository.iter_all())

        with self.subTest(corruption="nan"):
            self.path.write_text(
                '{"record_id":"record-1","value":NaN}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RepositoryCorruptionError, "non-finite"):
                tuple(self.repository.iter_all())

    def test_save_refuses_to_overwrite_a_corrupted_repository(self) -> None:
        corrupted = b'{"record_id":\n'
        self.path.write_bytes(corrupted)

        with self.assertRaises(RepositoryCorruptionError):
            self.repository.save(make_repository_record())

        self.assertEqual(self.path.read_bytes(), corrupted)


if __name__ == "__main__":
    unittest.main()
