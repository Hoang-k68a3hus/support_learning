from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, runtime_checkable

from ai_data_studio.schemas import SemanticWorkingRecord
from source_understanding.schemas.context import Identifier


@runtime_checkable
class WorkingRecordRepository(Protocol):
    """Persistence boundary for current SemanticWorkingRecord snapshots."""

    def get(
        self,
        record_id: Identifier,
    ) -> SemanticWorkingRecord | None:
        ...

    def save(
        self,
        record: SemanticWorkingRecord,
    ) -> None:
        ...

    def save_many(
        self,
        records: Iterable[SemanticWorkingRecord],
    ) -> None:
        ...

    def iter_all(self) -> Iterator[SemanticWorkingRecord]:
        ...

    def iter_batch(
        self,
        batch_id: Identifier,
    ) -> Iterator[SemanticWorkingRecord]:
        ...
