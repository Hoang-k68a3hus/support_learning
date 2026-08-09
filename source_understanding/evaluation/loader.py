from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .schemas import BenchmarkCase, BenchmarkManifest, GoldDocumentStructure


class EvaluationLoadError(ValueError):
    """A benchmark bundle cannot be loaded without violating gold-data invariants."""


@dataclass(frozen=True)
class LoadedBenchmarkCase:
    case: BenchmarkCase
    gold: GoldDocumentStructure
    source_path: Path
    annotation_path: Path


@dataclass(frozen=True)
class LoadedBenchmark:
    root: Path
    manifest: BenchmarkManifest
    cases: tuple[LoadedBenchmarkCase, ...]


def load_gold_document(path: str | Path) -> GoldDocumentStructure:
    source = Path(path)
    payload = _load_json(source, kind="gold annotation")
    try:
        return GoldDocumentStructure.model_validate(payload)
    except ValueError as exc:
        raise EvaluationLoadError(f"invalid gold annotation {source}: {exc}") from exc


def load_benchmark_manifest(path: str | Path) -> BenchmarkManifest:
    source = Path(path)
    payload = _load_json(source, kind="benchmark manifest")
    try:
        return BenchmarkManifest.model_validate(payload)
    except ValueError as exc:
        raise EvaluationLoadError(f"invalid benchmark manifest {source}: {exc}") from exc


def load_materialized_benchmark(root: str | Path) -> LoadedBenchmark:
    """Load and cross-validate a materialized benchmark directory.

    This is intentionally stricter than loading JSON models independently. It
    verifies path containment, exact source bytes, manifest↔gold identity, and
    source file naming so a stale/corrupt benchmark cannot silently be scored.
    """

    benchmark_root = Path(root).resolve()
    if not benchmark_root.is_dir():
        raise EvaluationLoadError(f"benchmark root is not a directory: {benchmark_root}")
    manifest = load_benchmark_manifest(benchmark_root / "manifest.json")
    loaded: list[LoadedBenchmarkCase] = []
    for case in manifest.cases:
        source_path = _resolve_member(benchmark_root, case.source_file)
        annotation_path = _resolve_member(benchmark_root, case.annotation_file)
        try:
            source_bytes = source_path.read_bytes()
        except OSError as exc:
            raise EvaluationLoadError(
                f"cannot read benchmark source {source_path}: {exc}"
            ) from exc
        actual_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
        if actual_hash != case.sha256:
            raise EvaluationLoadError(
                f"benchmark source hash mismatch for {case.document_id!r}: "
                f"manifest={case.sha256}, actual={actual_hash}"
            )
        gold = load_gold_document(annotation_path)
        if gold.document_id != case.document_id:
            raise EvaluationLoadError(
                f"manifest document_id {case.document_id!r} disagrees with gold "
                f"{gold.document_id!r}"
            )
        if gold.source.sha256 != case.sha256:
            raise EvaluationLoadError(
                f"manifest hash for {case.document_id!r} disagrees with gold source hash"
            )
        if gold.source.file_name != source_path.name:
            raise EvaluationLoadError(
                f"gold source file_name {gold.source.file_name!r} disagrees with "
                f"materialized file {source_path.name!r}"
            )
        if gold.benchmark_version != manifest.benchmark_version:
            raise EvaluationLoadError(
                f"gold benchmark_version for {case.document_id!r} disagrees with manifest"
            )
        if gold.schema_version != manifest.schema_version:
            raise EvaluationLoadError(
                f"gold schema_version for {case.document_id!r} disagrees with manifest"
            )
        loaded.append(
            LoadedBenchmarkCase(
                case=case,
                gold=gold,
                source_path=source_path,
                annotation_path=annotation_path,
            )
        )
    return LoadedBenchmark(
        root=benchmark_root,
        manifest=manifest,
        cases=tuple(loaded),
    )


def _resolve_member(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EvaluationLoadError(
            f"benchmark path escapes root: {relative!r}"
        ) from exc
    return candidate


def _load_json(path: Path, *, kind: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationLoadError(f"cannot read {kind} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationLoadError(f"invalid JSON in {kind} {path}: {exc}") from exc
