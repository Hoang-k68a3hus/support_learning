from __future__ import annotations

import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from pathlib import Path

from ai_data_studio.schemas import SemanticWorkingRecord
from source_understanding.schemas.context import Identifier

from .errors import (
    RepositoryDuplicateRecordError,
    RepositoryIdentityConflictError,
    RepositoryWriteError,
    WorkingRepositoryError,
)
from .serialization import load_jsonl_records, serialize_working_record


@dataclass(frozen=True)
class _WorkingRecordIdentity:
    record_id: str
    batch_id: str
    document_id: str
    content_hash: str
    element_snapshot_hash: str
    target_kind: str
    target_id: str
    element_ids: tuple[str, ...]
    element_orders: tuple[int, ...]


class JsonlWorkingRecordRepository:
    """Deterministic, single-writer JSONL storage for working records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkingRepositoryError(
                f"cannot create working-record repository directory "
                f"{self.path.parent}: {exc}"
            ) from exc

    def get(self, record_id: Identifier) -> SemanticWorkingRecord | None:
        return self._load_index().get(record_id)

    def save(self, record: SemanticWorkingRecord) -> None:
        current = self._load_index()
        existing = current.get(record.record_id)
        if existing is not None:
            _validate_identity_compatibility(old=existing, new=record)
        current[record.record_id] = record
        self._atomic_write(current.values())

    def save_many(self, records: Iterable[SemanticWorkingRecord]) -> None:
        incoming = tuple(records)
        current = self._load_index()
        if not incoming:
            return

        counts = Counter(record.record_id for record in incoming)
        duplicate_ids = tuple(
            sorted(record_id for record_id, count in counts.items() if count > 1)
        )
        if duplicate_ids:
            record_id = duplicate_ids[0]
            raise RepositoryDuplicateRecordError(
                f"duplicate record_id={record_id!r} in save_many input",
                record_id=record_id,
            )

        merged = dict(current)
        for record in incoming:
            existing = current.get(record.record_id)
            if existing is not None:
                _validate_identity_compatibility(old=existing, new=record)
            merged[record.record_id] = record
        self._atomic_write(merged.values())

    def iter_all(self) -> Iterator[SemanticWorkingRecord]:
        records = sorted(
            load_jsonl_records(self.path),
            key=lambda record: str(record.record_id),
        )
        return iter(records)

    def iter_batch(self, batch_id: Identifier) -> Iterator[SemanticWorkingRecord]:
        return (
            record for record in self.iter_all() if record.batch_id == batch_id
        )

    def _load_index(self) -> dict[str, SemanticWorkingRecord]:
        return {record.record_id: record for record in self.iter_all()}

    def _atomic_write(self, records: Iterable[SemanticWorkingRecord]) -> None:
        ordered = sorted(records, key=lambda record: str(record.record_id))
        temp_path: Path | None = None
        try:
            lines = tuple(serialize_working_record(record) for record in ordered)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)
                for line in lines:
                    temporary.write(line)
                    temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            assert temp_path is not None
            os.replace(temp_path, self.path)
            temp_path = None
        except Exception as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise RepositoryWriteError(
                f"cannot persist working records to {self.path}: {exc}",
                path=self.path,
            ) from exc


def _working_record_identity(record: SemanticWorkingRecord) -> _WorkingRecordIdentity:
    return _WorkingRecordIdentity(
        record_id=record.record_id,
        batch_id=record.batch_id,
        document_id=record.source.document_id,
        content_hash=record.source.content_hash,
        element_snapshot_hash=record.source.element_snapshot_hash,
        target_kind=record.target.target_kind.value,
        target_id=record.target.target_id,
        element_ids=record.target.element_ids,
        element_orders=record.target.element_orders,
    )


def _validate_identity_compatibility(
    *,
    old: SemanticWorkingRecord,
    new: SemanticWorkingRecord,
) -> None:
    old_identity = _working_record_identity(old)
    new_identity = _working_record_identity(new)
    conflicting_fields = tuple(
        field.name
        for field in fields(_WorkingRecordIdentity)
        if getattr(old_identity, field.name) != getattr(new_identity, field.name)
    )
    if conflicting_fields:
        raise RepositoryIdentityConflictError(
            record_id=old.record_id,
            conflicting_fields=conflicting_fields,
        )
