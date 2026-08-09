from __future__ import annotations

from pathlib import Path

from source_understanding.evaluation import SemanticGoldDataset

from .eligibility import (
    GoldEligibilityPolicy,
    gold_eligibility_policy_hash,
)
from .errors import DatasetFreezeInvariantError
from .freeze import (
    MANIFEST_FILENAME,
    SemanticGoldFreezer as _BaseSemanticGoldFreezer,
    verify_frozen_dataset as _base_verify_frozen_dataset,
    write_canonical_json,
)
from .manifest import (
    FreezePolicy,
    FreezeProvenance,
    FrozenDatasetManifest,
    FrozenDatasetVerificationIssue,
    FrozenDatasetVerificationIssueCode,
    FrozenDatasetVerificationReport,
)
from .splits import DatasetSplit, DatasetSplitManifest


class SemanticGoldFreezer(_BaseSemanticGoldFreezer):
    """Freeze only compiler-certified gold with matching release provenance."""

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
        _validate_compiled_certification(dataset=dataset, provenance=provenance)
        return super().freeze(
            dataset=dataset,
            output_dir=output_dir,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            split_manifest=split_manifest,
            provenance=provenance,
            policy=policy,
        )


def verify_frozen_dataset(root: Path) -> FrozenDatasetVerificationReport:
    base_report = _base_verify_frozen_dataset(root)
    if not base_report.valid:
        return base_report

    release_root = Path(root)
    manifest = FrozenDatasetManifest.model_validate_json(
        (release_root / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    issues: list[FrozenDatasetVerificationIssue] = []
    for split in DatasetSplit:
        artifact = manifest.artifact_for(split)
        if artifact is None:
            continue
        split_path = release_root / artifact.filename
        dataset = SemanticGoldDataset.model_validate_json(
            split_path.read_text(encoding="utf-8")
        )
        issues.extend(
            _certification_issues(
                dataset=dataset,
                manifest=manifest,
                path=split_path,
            )
        )
    return FrozenDatasetVerificationReport(
        valid=not issues,
        issues=tuple(issues),
    )


def _validate_compiled_certification(
    *,
    dataset: SemanticGoldDataset,
    provenance: FreezeProvenance,
) -> None:
    expected = {
        "compiler_version": provenance.compiler_version,
        "working_schema_version": provenance.working_record_schema_version,
        "eligibility_policy_name": provenance.eligibility_policy_name,
        "eligibility_policy_version": provenance.eligibility_policy_version,
    }
    for key, expected_value in expected.items():
        actual = dataset.metadata.get(key)
        if actual != expected_value:
            raise DatasetFreezeInvariantError(
                f"compiled dataset {key} does not match freeze provenance: "
                f"{actual!r} != {expected_value!r}"
            )

    guideline_versions = tuple(dataset.metadata.get("guideline_versions", ()))
    if guideline_versions != (provenance.guideline_version,):
        raise DatasetFreezeInvariantError(
            "compiled dataset guideline_versions do not match freeze provenance: "
            f"{guideline_versions!r} != {(provenance.guideline_version,)!r}"
        )

    policy_payload = dataset.metadata.get("eligibility_policy")
    try:
        compiled_policy = GoldEligibilityPolicy.model_validate(policy_payload)
    except ValueError as exc:
        raise DatasetFreezeInvariantError(
            f"compiled dataset eligibility_policy is invalid: {exc}"
        ) from exc
    expected_policy_hash = gold_eligibility_policy_hash(compiled_policy)
    if dataset.metadata.get("eligibility_policy_hash") != expected_policy_hash:
        raise DatasetFreezeInvariantError(
            "compiled dataset eligibility_policy_hash does not match its policy"
        )

    for case in dataset.cases:
        _require_case_certification(
            case_metadata=case.metadata,
            document_id=case.document_id,
            expected={
                **expected,
                "guideline_version": provenance.guideline_version,
                "eligibility_policy_hash": expected_policy_hash,
            },
        )


def _require_case_certification(
    *,
    case_metadata: object,
    document_id: str,
    expected: dict[str, object],
) -> None:
    metadata = (
        case_metadata
        if isinstance(case_metadata, dict)
        else dict(case_metadata)
    )
    for key, expected_value in expected.items():
        actual = metadata.get(key)
        if actual != expected_value:
            raise DatasetFreezeInvariantError(
                f"gold case {document_id!r} {key} does not match compiled "
                f"certification: {actual!r} != {expected_value!r}"
            )


def _certification_issues(
    *,
    dataset: SemanticGoldDataset,
    manifest: FrozenDatasetManifest,
    path: Path,
) -> tuple[FrozenDatasetVerificationIssue, ...]:
    issues: list[FrozenDatasetVerificationIssue] = []
    expected = {
        "compiler_version": manifest.compiler_version,
        "working_schema_version": manifest.working_record_schema_version,
        "eligibility_policy_name": manifest.eligibility_policy_name,
        "eligibility_policy_version": manifest.eligibility_policy_version,
        "guideline_version": manifest.guideline_version,
    }

    policy_payload = dataset.metadata.get("eligibility_policy")
    try:
        policy = GoldEligibilityPolicy.model_validate(policy_payload)
        policy_hash = gold_eligibility_policy_hash(policy)
    except ValueError as exc:
        issues.append(
            FrozenDatasetVerificationIssue(
                code=FrozenDatasetVerificationIssueCode.DATASET_IDENTITY_MISMATCH,
                message=f"frozen eligibility policy is invalid: {exc}",
                path=str(path),
            )
        )
        return tuple(issues)

    policy_identity = (policy.name, policy.version)
    manifest_policy_identity = (
        manifest.eligibility_policy_name,
        manifest.eligibility_policy_version,
    )
    if policy_identity != manifest_policy_identity:
        issues.append(
            FrozenDatasetVerificationIssue(
                code=FrozenDatasetVerificationIssueCode.DATASET_IDENTITY_MISMATCH,
                message=(
                    "frozen eligibility policy identity does not match manifest: "
                    f"{policy_identity!r} != {manifest_policy_identity!r}"
                ),
                path=str(path),
            )
        )

    guideline_versions = tuple(dataset.metadata.get("guideline_versions", ()))
    if guideline_versions != (manifest.guideline_version,):
        issues.append(
            FrozenDatasetVerificationIssue(
                code=FrozenDatasetVerificationIssueCode.DATASET_IDENTITY_MISMATCH,
                message=(
                    "frozen guideline_versions do not match manifest: "
                    f"{guideline_versions!r} != {(manifest.guideline_version,)!r}"
                ),
                path=str(path),
            )
        )

    for case in dataset.cases:
        case_expected = {
            **expected,
            "eligibility_policy_hash": policy_hash,
        }
        for key, expected_value in case_expected.items():
            actual = case.metadata.get(key)
            if actual != expected_value:
                issues.append(
                    FrozenDatasetVerificationIssue(
                        code=(
                            FrozenDatasetVerificationIssueCode.
                            DATASET_IDENTITY_MISMATCH
                        ),
                        message=(
                            f"gold case {case.document_id!r} {key} mismatch: "
                            f"{actual!r} != {expected_value!r}"
                        ),
                        path=str(path),
                    )
                )
    return tuple(issues)


__all__ = [
    "MANIFEST_FILENAME",
    "SemanticGoldFreezer",
    "verify_frozen_dataset",
    "write_canonical_json",
]
