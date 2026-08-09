from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError

from source_understanding.evaluation import (
    SEMANTIC_GOLD_SCHEMA_VERSION,
    SemanticGoldDataset,
)

from .errors import (
    DatasetFreezeError,
    DatasetFreezeInvariantError,
    DatasetFreezeVerificationError,
    DatasetFreezeWriteError,
    DatasetVersionAlreadyFrozenError,
)
from .hashing import (
    dataset_hash_from_splits,
    semantic_gold_split_hash,
    source_corpus_hash,
)
from .manifest import (
    FreezePolicy,
    FreezeProvenance,
    FrozenDatasetManifest,
    FrozenDatasetVerificationIssue,
    FrozenDatasetVerificationIssueCode,
    FrozenDatasetVerificationReport,
    FrozenSplitArtifact,
)
from .splits import (
    DatasetSplit,
    DatasetSplitManifest,
    dataset_split_manifest_hash,
)


MANIFEST_FILENAME = "manifest.json"


class SemanticGoldFreezer:
    """Atomically publish an already-compiled semantic gold dataset."""

    def freeze(
        self,
        *,
        dataset: SemanticGoldDataset,
        output_dir: Path,
        dataset_name: str,
        dataset_version: str,
        split_manifest: DatasetSplitManifest,
        provenance: FreezeProvenance,
        policy: FreezePolicy | None = None,
    ) -> FrozenDatasetManifest:
        selected_policy = policy or FreezePolicy()
        _validate_release_identity(
            dataset=dataset,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
        )
        split_datasets = _build_split_datasets(dataset)
        _validate_freeze_inputs(
            dataset=dataset,
            split_datasets=split_datasets,
            split_manifest=split_manifest,
            provenance=provenance,
            policy=selected_policy,
        )

        root = Path(output_dir)
        dataset_root = root / dataset_name
        final_root = dataset_root / dataset_version
        if _path_lexists(final_root):
            raise DatasetVersionAlreadyFrozenError(
                f"dataset {dataset_name!r} version {dataset_version!r} is "
                f"already frozen at {final_root}"
            )
        try:
            dataset_root.mkdir(parents=True, exist_ok=True)
            temporary_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{dataset_version}.tmp-",
                    dir=dataset_root,
                )
            )
        except OSError as exc:
            raise DatasetFreezeWriteError(
                f"cannot prepare freeze directory for dataset {dataset_name!r} "
                f"version {dataset_version!r} at {final_root}: {exc}"
            ) from exc

        published = False
        try:
            manifest = _build_manifest(
                dataset=dataset,
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                split_datasets=split_datasets,
                split_manifest=split_manifest,
                provenance=provenance,
            )
            _write_freeze_candidate(
                temporary_root,
                split_datasets=split_datasets,
                manifest=manifest,
            )
            _verify_round_trip(
                temporary_root,
                expected_splits=split_datasets,
                expected_manifest=manifest,
            )
            if _path_lexists(final_root):
                raise DatasetVersionAlreadyFrozenError(
                    f"dataset {dataset_name!r} version {dataset_version!r} "
                    f"appeared during freeze at {final_root}"
                )
            try:
                os.rename(temporary_root, final_root)
            except OSError as exc:
                if _path_lexists(final_root):
                    raise DatasetVersionAlreadyFrozenError(
                        f"dataset {dataset_name!r} version "
                        f"{dataset_version!r} was frozen concurrently at "
                        f"{final_root}"
                    ) from exc
                raise DatasetFreezeWriteError(
                    f"cannot atomically publish dataset {dataset_name!r} "
                    f"version {dataset_version!r} to {final_root}: {exc}"
                ) from exc
            published = True
            return manifest
        except DatasetFreezeError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise DatasetFreezeWriteError(
                f"cannot write dataset {dataset_name!r} version "
                f"{dataset_version!r} at {final_root}: {exc}"
            ) from exc
        finally:
            if not published:
                _cleanup_temporary_directory(temporary_root)


def write_canonical_json(path: Path, payload: object) -> None:
    if isinstance(payload, BaseModel):
        serializable = payload.model_dump(mode="json", exclude_none=False)
    else:
        serializable = payload
    encoded = json.dumps(
        serializable,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(encoded)
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())


def verify_frozen_dataset(root: Path) -> FrozenDatasetVerificationReport:
    release_root = Path(root)
    manifest_path = release_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return _verification_report(
            FrozenDatasetVerificationIssue(
                code=FrozenDatasetVerificationIssueCode.MANIFEST_MISSING,
                message=f"frozen dataset manifest is missing at {manifest_path}",
                path=str(manifest_path),
            )
        )

    try:
        manifest = FrozenDatasetManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        code = _manifest_error_code(exc)
        return _verification_report(
            FrozenDatasetVerificationIssue(
                code=code,
                message=f"frozen dataset manifest is invalid: {exc}",
                path=str(manifest_path),
            )
        )

    issues: list[FrozenDatasetVerificationIssue] = []
    loaded_splits: dict[DatasetSplit, SemanticGoldDataset] = {}
    actual_hashes: dict[DatasetSplit, str] = {}
    actual_counts: dict[DatasetSplit, tuple[int, int, int]] = {}

    for split in DatasetSplit:
        artifact = manifest.artifact_for(split)
        canonical_path = release_root / f"{split.value}.json"
        if artifact is None:
            if _path_lexists(canonical_path):
                issues.append(
                    FrozenDatasetVerificationIssue(
                        code=(
                            FrozenDatasetVerificationIssueCode.
                            SPLIT_FILE_UNEXPECTED
                        ),
                        message=(
                            f"unreferenced {split.value} split artifact exists at "
                            f"{canonical_path}"
                        ),
                        path=str(canonical_path),
                    )
                )
            continue

        split_path = release_root / artifact.filename
        if not split_path.is_file():
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=FrozenDatasetVerificationIssueCode.SPLIT_FILE_MISSING,
                    message=(
                        f"manifest-declared {split.value} split artifact is "
                        f"missing at {split_path}"
                    ),
                    path=str(split_path),
                )
            )
            continue
        try:
            loaded = SemanticGoldDataset.model_validate_json(
                split_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.DATASET_SCHEMA_INVALID
                    ),
                    message=(
                        f"{split.value} split artifact is not a valid semantic "
                        f"gold dataset: {exc}"
                    ),
                    path=str(split_path),
                )
            )
            continue

        loaded_splits[split] = loaded
        if loaded.name != manifest.dataset_name:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.
                        DATASET_IDENTITY_MISMATCH
                    ),
                    message=(
                        f"{split.value} dataset name {loaded.name!r} does not "
                        f"match manifest name {manifest.dataset_name!r}"
                    ),
                    path=str(split_path),
                )
            )
        if loaded.schema_version != manifest.gold_schema_version:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.
                        DATASET_IDENTITY_MISMATCH
                    ),
                    message=(
                        f"{split.value} gold schema {loaded.schema_version!r} "
                        f"does not match manifest "
                        f"{manifest.gold_schema_version!r}"
                    ),
                    path=str(split_path),
                )
            )
        if any(case.split.value != split.value for case in loaded.cases):
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=FrozenDatasetVerificationIssueCode.SPLIT_CASE_MISMATCH,
                    message=(
                        f"{split.value} artifact contains a case assigned to "
                        "another split"
                    ),
                    path=str(split_path),
                )
            )
            continue

        actual_hash = semantic_gold_split_hash(loaded, split=split)
        actual_hashes[split] = actual_hash
        if actual_hash != artifact.content_hash:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=FrozenDatasetVerificationIssueCode.SPLIT_HASH_MISMATCH,
                    message=(
                        f"{split.value} split hash mismatch: "
                        f"{actual_hash!r} != {artifact.content_hash!r}"
                    ),
                    path=str(split_path),
                )
            )
        counts = _dataset_counts(loaded)
        actual_counts[split] = counts
        declared_counts = (
            artifact.document_count,
            artifact.target_count,
            artifact.annotation_count,
        )
        if counts != declared_counts:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.
                        MANIFEST_COUNT_MISMATCH
                    ),
                    message=(
                        f"{split.value} actual counts {counts!r} do not match "
                        f"manifest counts {declared_counts!r}"
                    ),
                    path=str(split_path),
                )
            )

    declared_splits = {
        split
        for split in DatasetSplit
        if manifest.artifact_for(split) is not None
    }
    if set(actual_hashes) == declared_splits:
        actual_dataset_hash = dataset_hash_from_splits(actual_hashes)
        if actual_dataset_hash != manifest.dataset_hash:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.DATASET_HASH_MISMATCH
                    ),
                    message=(
                        f"dataset hash mismatch: {actual_dataset_hash!r} != "
                        f"{manifest.dataset_hash!r}"
                    ),
                    path=str(manifest_path),
                )
            )

    if set(loaded_splits) == declared_splits:
        combined = _combine_split_datasets(
            manifest.dataset_name,
            loaded_splits,
        )
        actual_source_hash = source_corpus_hash(combined)
        if actual_source_hash != manifest.source_corpus_hash:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.
                        SOURCE_CORPUS_HASH_MISMATCH
                    ),
                    message=(
                        f"source corpus hash mismatch: {actual_source_hash!r} != "
                        f"{manifest.source_corpus_hash!r}"
                    ),
                    path=str(manifest_path),
                )
            )

    if set(actual_counts) == declared_splits:
        total_counts = tuple(
            sum(counts[index] for counts in actual_counts.values())
            for index in range(3)
        )
        manifest_counts = (
            manifest.document_count,
            manifest.target_count,
            manifest.annotation_count,
        )
        if total_counts != manifest_counts:
            issues.append(
                FrozenDatasetVerificationIssue(
                    code=(
                        FrozenDatasetVerificationIssueCode.
                        MANIFEST_COUNT_MISMATCH
                    ),
                    message=(
                        f"actual dataset counts {total_counts!r} do not match "
                        f"manifest counts {manifest_counts!r}"
                    ),
                    path=str(manifest_path),
                )
            )
    return FrozenDatasetVerificationReport(
        valid=not issues,
        issues=tuple(issues),
    )


def _build_split_datasets(
    dataset: SemanticGoldDataset,
) -> dict[DatasetSplit, SemanticGoldDataset]:
    split_datasets: dict[DatasetSplit, SemanticGoldDataset] = {}
    for split in DatasetSplit:
        cases = tuple(
            sorted(
                (
                    case
                    for case in dataset.cases
                    if case.split.value == split.value
                ),
                key=lambda case: case.document_id,
            )
        )
        if not cases:
            continue
        split_datasets[split] = SemanticGoldDataset(
            name=dataset.name,
            schema_version=dataset.schema_version,
            benchmark_version=dataset.benchmark_version,
            cases=cases,
            metadata=dataset.metadata,
        )
    return split_datasets


def _validate_release_identity(
    *,
    dataset: SemanticGoldDataset,
    dataset_name: str,
    dataset_version: str,
) -> None:
    for field_name, value in (
        ("dataset_name", dataset_name),
        ("dataset_version", dataset_version),
    ):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is None:
            raise DatasetFreezeInvariantError(
                f"freeze {field_name} {value!r} is not a portable path segment"
            )
    if dataset.name != dataset_name:
        raise DatasetFreezeInvariantError(
            f"compiled dataset name {dataset.name!r} does not match freeze "
            f"identity {dataset_name!r}"
        )


def _validate_freeze_inputs(
    *,
    dataset: SemanticGoldDataset,
    split_datasets: Mapping[DatasetSplit, SemanticGoldDataset],
    split_manifest: DatasetSplitManifest,
    provenance: FreezeProvenance,
    policy: FreezePolicy,
) -> None:
    present_splits = set(split_datasets)
    missing_required = set(policy.required_splits) - present_splits
    if missing_required:
        raise DatasetFreezeInvariantError(
            "compiled gold dataset is missing required frozen splits: "
            f"{sorted(split.value for split in missing_required)!r}"
        )
    manifest_splits = {
        assignment.split for assignment in split_manifest.assignments
    }
    if present_splits != manifest_splits:
        raise DatasetFreezeInvariantError(
            "compiled gold splits do not match split manifest assignments: "
            f"dataset={sorted(split.value for split in present_splits)!r}, "
            f"manifest={sorted(split.value for split in manifest_splits)!r}"
        )

    expected_split_hash = dataset_split_manifest_hash(split_manifest)
    compiled_split_hash = dataset.metadata.get("split_manifest_hash")
    if compiled_split_hash != expected_split_hash:
        raise DatasetFreezeInvariantError(
            "compiled dataset split_manifest_hash does not match the supplied "
            f"manifest: {compiled_split_hash!r} != {expected_split_hash!r}"
        )
    compiled_version = dataset.metadata.get("compiler_version")
    if compiled_version != provenance.compiler_version:
        raise DatasetFreezeInvariantError(
            "compiled dataset compiler_version does not match freeze provenance: "
            f"{compiled_version!r} != {provenance.compiler_version!r}"
        )
    compiled_working_version = dataset.metadata.get("working_schema_version")
    if compiled_working_version != provenance.working_record_schema_version:
        raise DatasetFreezeInvariantError(
            "compiled dataset working_schema_version does not match freeze "
            f"provenance: {compiled_working_version!r} != "
            f"{provenance.working_record_schema_version!r}"
        )
    if dataset.schema_version != SEMANTIC_GOLD_SCHEMA_VERSION:
        raise DatasetFreezeInvariantError(
            f"unsupported compiled gold schema_version {dataset.schema_version!r}"
        )


def _build_manifest(
    *,
    dataset: SemanticGoldDataset,
    dataset_name: str,
    dataset_version: str,
    split_datasets: Mapping[DatasetSplit, SemanticGoldDataset],
    split_manifest: DatasetSplitManifest,
    provenance: FreezeProvenance,
) -> FrozenDatasetManifest:
    artifacts = {
        split: _split_artifact(split, split_dataset)
        for split, split_dataset in split_datasets.items()
    }
    dataset_hash = dataset_hash_from_splits(
        {
            split: artifact.content_hash
            for split, artifact in artifacts.items()
        }
    )
    counts = _dataset_counts(dataset)
    return FrozenDatasetManifest(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        gold_schema_version=dataset.schema_version,
        compiler_version=provenance.compiler_version,
        working_record_schema_version=(
            provenance.working_record_schema_version
        ),
        split_manifest_schema_version=split_manifest.schema_version,
        guideline_version=provenance.guideline_version,
        eligibility_policy_name=provenance.eligibility_policy_name,
        eligibility_policy_version=provenance.eligibility_policy_version,
        producer_revision=provenance.producer_revision,
        split_manifest_hash=dataset_split_manifest_hash(split_manifest),
        source_corpus_hash=source_corpus_hash(dataset),
        dataset_hash=dataset_hash,
        train=artifacts.get(DatasetSplit.TRAIN),
        dev=artifacts.get(DatasetSplit.DEV),
        test=artifacts.get(DatasetSplit.TEST),
        document_count=counts[0],
        target_count=counts[1],
        annotation_count=counts[2],
        created_at=datetime.now(timezone.utc),
    )


def _split_artifact(
    split: DatasetSplit,
    dataset: SemanticGoldDataset,
) -> FrozenSplitArtifact:
    counts = _dataset_counts(dataset)
    return FrozenSplitArtifact(
        split=split,
        filename=f"{split.value}.json",
        content_hash=semantic_gold_split_hash(dataset, split=split),
        document_count=counts[0],
        target_count=counts[1],
        annotation_count=counts[2],
    )


def _dataset_counts(dataset: SemanticGoldDataset) -> tuple[int, int, int]:
    return (
        len(dataset.cases),
        sum(len(case.evaluation_scopes) for case in dataset.cases),
        sum(len(case.annotations) for case in dataset.cases),
    )


def _write_freeze_candidate(
    root: Path,
    *,
    split_datasets: Mapping[DatasetSplit, SemanticGoldDataset],
    manifest: FrozenDatasetManifest,
) -> None:
    for split in DatasetSplit:
        split_dataset = split_datasets.get(split)
        if split_dataset is not None:
            write_canonical_json(root / f"{split.value}.json", split_dataset)
    write_canonical_json(root / MANIFEST_FILENAME, manifest)


def _verify_round_trip(
    root: Path,
    *,
    expected_splits: Mapping[DatasetSplit, SemanticGoldDataset],
    expected_manifest: FrozenDatasetManifest,
) -> None:
    report = verify_frozen_dataset(root)
    if not report.valid:
        details = "; ".join(
            f"{issue.code.value}: {issue.message}" for issue in report.issues
        )
        raise DatasetFreezeVerificationError(
            f"freeze candidate verification failed at {root}: {details}"
        )
    reloaded_manifest = FrozenDatasetManifest.model_validate_json(
        (root / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    if reloaded_manifest != expected_manifest:
        raise DatasetFreezeVerificationError(
            f"freeze candidate manifest round-trip changed at {root}"
        )
    for split, expected_dataset in expected_splits.items():
        reloaded = SemanticGoldDataset.model_validate_json(
            (root / f"{split.value}.json").read_text(encoding="utf-8")
        )
        if reloaded != expected_dataset:
            raise DatasetFreezeVerificationError(
                f"freeze candidate {split.value} round-trip changed at {root}"
            )


def _combine_split_datasets(
    name: str,
    datasets: Mapping[DatasetSplit, SemanticGoldDataset],
) -> SemanticGoldDataset:
    cases = tuple(
        sorted(
            (
                case
                for split in DatasetSplit
                if split in datasets
                for case in datasets[split].cases
            ),
            key=lambda case: case.document_id,
        )
    )
    first = next(iter(datasets.values()))
    return SemanticGoldDataset(
        name=name,
        schema_version=first.schema_version,
        benchmark_version=first.benchmark_version,
        cases=cases,
        metadata={},
    )


def _manifest_error_code(
    error: Exception,
) -> FrozenDatasetVerificationIssueCode:
    if "total counts must equal per-split counts" in str(error):
        return FrozenDatasetVerificationIssueCode.MANIFEST_COUNT_MISMATCH
    return FrozenDatasetVerificationIssueCode.MANIFEST_INVALID


def _verification_report(
    *issues: FrozenDatasetVerificationIssue,
) -> FrozenDatasetVerificationReport:
    return FrozenDatasetVerificationReport(valid=not issues, issues=issues)


def _cleanup_temporary_directory(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)
