from __future__ import annotations

from pathlib import Path


class WorkingRepositoryError(RuntimeError):
    """Base error for working-record persistence failures."""


class RepositoryCorruptionError(WorkingRepositoryError):
    """Persisted repository bytes do not represent valid working records."""

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        line_number: int | None = None,
        record_id: str | None = None,
    ) -> None:
        self.path = path
        self.line_number = line_number
        self.record_id = record_id
        super().__init__(message)


class RepositoryIdentityConflictError(WorkingRepositoryError):
    """An upsert attempted to move an existing record to another identity."""

    def __init__(
        self,
        *,
        record_id: str,
        conflicting_fields: tuple[str, ...],
    ) -> None:
        self.record_id = record_id
        self.conflicting_fields = conflicting_fields
        fields = ", ".join(conflicting_fields)
        super().__init__(
            f"cannot replace record_id={record_id!r}; immutable identity fields "
            f"changed: {fields}"
        )


class RepositoryDuplicateRecordError(WorkingRepositoryError):
    """A file or bulk request contains an ambiguous duplicate record ID."""

    def __init__(
        self,
        message: str,
        *,
        record_id: str,
        path: Path | None = None,
        line_number: int | None = None,
    ) -> None:
        self.record_id = record_id
        self.path = path
        self.line_number = line_number
        super().__init__(message)


class RepositoryWriteError(WorkingRepositoryError):
    """Working records could not be atomically persisted."""

    def __init__(self, message: str, *, path: Path) -> None:
        self.path = path
        super().__init__(message)
