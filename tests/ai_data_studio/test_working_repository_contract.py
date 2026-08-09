from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_data_studio.repositories import (
    JsonlWorkingRecordRepository,
    RepositoryIdentityConflictError,
    WorkingRecordRepository,
)
from ai_data_studio.repositories.errors import RepositoryDuplicateRecordError
from ai_data_studio.schemas import SemanticWorkingRecord, WorkingRecordStatus
from source_understanding.semantics import SemanticTargetKind

from ._repository_fixtures import make_repository_record


class WorkingRecordRepositoryContractMixin:
    repository: WorkingRecordRepository

    def make_repository(self, path: Path) -> WorkingRecordRepository:
        raise NotImplementedError

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        path = Path(self.temporary_directory.name) / "records.jsonl"
        self.repository = self.make_repository(path)

    def test_save_then_get_roundtrip(self) -> None:
        record = make_repository_record()

        self.repository.save(record)

        self.assertEqual(self.repository.get(record.record_id), record)

    def test_save_existing_replaces_whole_mutable_snapshot(self) -> None:
        original = make_repository_record()
        replacement = make_repository_record(
            status=WorkingRecordStatus.REVIEW_REQUIRED,
            metadata={"review_queue": "priority"},
        )
        self.repository.save(original)

        self.repository.save(replacement)

        self.assertEqual(self.repository.get(original.record_id), replacement)
        self.assertEqual(tuple(self.repository.iter_all()), (replacement,))

    def test_save_existing_rejects_immutable_identity_changes(self) -> None:
        original = make_repository_record()
        self.repository.save(original)
        variants: dict[str, SemanticWorkingRecord] = {
            "batch_id": original.model_copy(update={"batch_id": "batch-2"}),
            "document_id": original.model_copy(
                update={
                    "source": original.source.model_copy(
                        update={"document_id": "document-other"}
                    )
                }
            ),
            "content_hash": original.model_copy(
                update={
                    "source": original.source.model_copy(
                        update={"content_hash": "sha256:" + "c" * 64}
                    )
                }
            ),
            "element_snapshot_hash": original.model_copy(
                update={
                    "source": original.source.model_copy(
                        update={"element_snapshot_hash": "sha256:" + "d" * 64}
                    )
                }
            ),
            "target_kind": original.model_copy(
                update={
                    "target": original.target.model_copy(
                        update={"target_kind": SemanticTargetKind.LOGICAL_UNIT}
                    )
                }
            ),
            "target_id": original.model_copy(
                update={
                    "target": original.target.model_copy(
                        update={"target_id": "target-other"}
                    )
                }
            ),
            "element_ids": original.model_copy(
                update={
                    "target": original.target.model_copy(
                        update={"element_ids": ("element-other",)}
                    )
                }
            ),
            "element_orders": original.model_copy(
                update={
                    "target": original.target.model_copy(
                        update={"element_orders": (1,)}
                    )
                }
            ),
        }

        for expected_field, replacement in variants.items():
            with self.subTest(field=expected_field):
                with self.assertRaises(RepositoryIdentityConflictError) as caught:
                    self.repository.save(replacement)
                self.assertIn(expected_field, caught.exception.conflicting_fields)
                self.assertEqual(self.repository.get(original.record_id), original)

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.repository.get("missing-record"))

    def test_iter_all_is_lexical_and_iter_batch_filters(self) -> None:
        records = (
            make_repository_record(
                record_id="record-c",
                batch_id="batch-2",
                hash_token="c",
                snapshot_token="d",
                target_order=2,
            ),
            make_repository_record(
                record_id="record-a",
                batch_id="batch-1",
                hash_token="a",
                snapshot_token="b",
                target_order=0,
            ),
            make_repository_record(
                record_id="record-b",
                batch_id="batch-1",
                hash_token="b",
                snapshot_token="c",
                target_order=1,
            ),
        )
        self.repository.save_many(records)

        self.assertEqual(
            tuple(record.record_id for record in self.repository.iter_all()),
            ("record-a", "record-b", "record-c"),
        )
        self.assertEqual(
            tuple(record.record_id for record in self.repository.iter_batch("batch-1")),
            ("record-a", "record-b"),
        )

    def test_save_many_identity_conflict_is_all_or_nothing(self) -> None:
        original = make_repository_record()
        self.repository.save(original)
        added = make_repository_record(
            record_id="record-2",
            hash_token="c",
            snapshot_token="d",
            target_order=1,
        )
        conflict = original.model_copy(update={"batch_id": "batch-other"})

        with self.assertRaises(RepositoryIdentityConflictError):
            self.repository.save_many((added, conflict))

        self.assertEqual(tuple(self.repository.iter_all()), (original,))

    def test_save_many_duplicate_input_is_rejected(self) -> None:
        record = make_repository_record()

        with self.assertRaises(RepositoryDuplicateRecordError):
            self.repository.save_many((record, record))

        self.assertEqual(tuple(self.repository.iter_all()), ())


class JsonlWorkingRecordRepositoryContractTests(
    WorkingRecordRepositoryContractMixin,
    unittest.TestCase,
):
    def make_repository(self, path: Path) -> WorkingRecordRepository:
        repository = JsonlWorkingRecordRepository(path)
        self.assertIsInstance(repository, WorkingRecordRepository)
        return repository


if __name__ == "__main__":
    unittest.main()
