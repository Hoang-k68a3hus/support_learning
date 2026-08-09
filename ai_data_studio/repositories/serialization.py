from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

from pydantic import ValidationError

from ai_data_studio.schemas import SemanticWorkingRecord

from .errors import (
    RepositoryCorruptionError,
    RepositoryDuplicateRecordError,
    WorkingRepositoryError,
)


def serialize_working_record(record: SemanticWorkingRecord) -> str:
    payload = record.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_jsonl_records(path: Path) -> tuple[SemanticWorkingRecord, ...]:
    if not path.exists():
        return ()

    records: list[SemanticWorkingRecord] = []
    first_lines: dict[str, int] = {}
    try:
        with path.open("rb") as source:
            for line_number, raw_line in enumerate(source, start=1):
                line = _decode_jsonl_line(
                    raw_line,
                    path=path,
                    line_number=line_number,
                )
                record = _parse_working_record_line(
                    line,
                    path=path,
                    line_number=line_number,
                )
                first_line = first_lines.get(record.record_id)
                if first_line is not None:
                    raise RepositoryDuplicateRecordError(
                        f"duplicate record_id={record.record_id!r} in {path} "
                        f"line {line_number}; first seen at line {first_line}",
                        record_id=record.record_id,
                        path=path,
                        line_number=line_number,
                    )
                first_lines[record.record_id] = line_number
                records.append(record)
    except (RepositoryCorruptionError, RepositoryDuplicateRecordError):
        raise
    except OSError as exc:
        raise WorkingRepositoryError(
            f"cannot read working-record repository {path}: {exc}"
        ) from exc
    return tuple(records)


def _decode_jsonl_line(
    raw_line: bytes,
    *,
    path: Path,
    line_number: int,
) -> str:
    try:
        line = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryCorruptionError(
            f"invalid UTF-8 in working-record repository {path} line "
            f"{line_number}: {exc}",
            path=path,
            line_number=line_number,
        ) from exc
    if line.endswith("\n"):
        line = line[:-1]
        if line.endswith("\r"):
            line = line[:-1]
    if not line.strip():
        raise RepositoryCorruptionError(
            f"blank line in working-record repository {path} line {line_number}",
            path=path,
            line_number=line_number,
        )
    return line


def _parse_working_record_line(
    line: str,
    *,
    path: Path,
    line_number: int,
) -> SemanticWorkingRecord:
    try:
        payload = json.loads(line, parse_constant=_reject_non_finite_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RepositoryCorruptionError(
            f"invalid JSON in working-record repository {path} line "
            f"{line_number}: {exc}",
            path=path,
            line_number=line_number,
        ) from exc

    record_id = _payload_record_id(payload)
    try:
        return SemanticWorkingRecord.model_validate(payload)
    except ValidationError as exc:
        identity = f" record_id={record_id!r}" if record_id is not None else ""
        raise RepositoryCorruptionError(
            f"invalid working record in {path} line {line_number}:{identity}: {exc}",
            path=path,
            line_number=line_number,
            record_id=record_id,
        ) from exc


def _payload_record_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("record_id")
    return value if isinstance(value, str) else None


def _reject_non_finite_json(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not supported")
