from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_data_studio.repositories import JsonlWorkingRecordRepository
from ai_data_studio.repositories.serialization import serialize_working_record

from ._repository_fixtures import (
    make_repository_record,
    make_rich_repository_record,
)


class JsonlWorkingRecordRepositoryTests(unittest.TestCase):
    def test_canonical_serialization_is_deterministic_and_explicit(self) -> None:
        record = make_repository_record(normalized_text=None)

        first = serialize_working_record(record)
        second = serialize_working_record(record)
        payload = json.loads(first)

        self.assertEqual(first, second)
        self.assertIn("Định nghĩa", first)
        self.assertEqual(payload["target"]["normalized_text"], None)
        expected = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(first, expected)

    def test_unicode_newlines_and_nested_annotation_state_roundtrip_exactly(
        self,
    ) -> None:
        record = make_rich_repository_record()
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = JsonlWorkingRecordRepository(
                Path(temporary_directory) / "records.jsonl"
            )

            repository.save(record)
            loaded = repository.get(record.record_id)

        self.assertEqual(loaded, record)
        self.assertIsNotNone(loaded)
        if loaded is not None:
            self.assertEqual(loaded.target.raw_text, record.target.raw_text)
            self.assertEqual(
                loaded.target.normalized_text,
                record.target.normalized_text,
            )
            self.assertEqual(
                loaded.suggestions[0].evidence,
                record.suggestions[0].evidence,
            )
            self.assertEqual(
                loaded.reviews[0].decision_hash_after,
                record.decision_hash,
            )

    def test_same_state_produces_same_sorted_jsonl_bytes(self) -> None:
        first_record = make_repository_record(
            record_id="record-a",
            hash_token="a",
            snapshot_token="b",
        )
        second_record = make_repository_record(
            record_id="record-b",
            hash_token="c",
            snapshot_token="d",
            target_order=1,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_path = root / "first.jsonl"
            second_path = root / "second.jsonl"
            first_repository = JsonlWorkingRecordRepository(first_path)
            second_repository = JsonlWorkingRecordRepository(second_path)

            first_repository.save_many((second_record, first_record))
            second_repository.save_many((first_record, second_record))

            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertTrue(first_path.read_bytes().endswith(b"\n"))
            self.assertEqual(
                first_path.read_text(encoding="utf-8").splitlines(),
                [
                    serialize_working_record(first_record),
                    serialize_working_record(second_record),
                ],
            )

    def test_constructor_creates_explicit_repository_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "working" / "records.jsonl"

            repository = JsonlWorkingRecordRepository(path)
            repository.save(make_repository_record())

            self.assertTrue(path.is_file())

    def test_upsert_rewrites_one_current_line_instead_of_appending_history(
        self,
    ) -> None:
        original = make_repository_record()
        replacement = make_repository_record(metadata={"revision": 2})
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "records.jsonl"
            repository = JsonlWorkingRecordRepository(path)

            repository.save(original)
            repository.save(replacement)

            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines(),
                [serialize_working_record(replacement)],
            )


if __name__ == "__main__":
    unittest.main()
