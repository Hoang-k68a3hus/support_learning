from __future__ import annotations

from pathlib import Path

from source_understanding.evaluation import SemanticGoldDataset

from .errors import DatasetFreezeInvariantError
from .freeze import SemanticGoldFreezer as _AtomicSemanticGoldFreezer
from .manifest import FreezePolicy, FreezeProvenance, FrozenDatasetManifest
from .splits import DatasetSplitManifest


class SemanticGoldFreezer(_AtomicSemanticGoldFreezer):
    """Public freezer that binds declared provenance to compiler-owned metadata."""

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
        _validate_compilation_provenance(dataset=dataset, provenance=provenance)
        return super().freeze(
            dataset=dataset,
            output_dir=output_dir,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            split_manifest=split_manifest,
            provenance=provenance,
            policy=policy,
        )


def _validate_compilation_provenance(
    *,
    dataset: SemanticGoldDataset,
    provenance: FreezeProvenance,
) -> None:
    expected = {
        "guideline_version": provenance.guideline_version,
        "eligibility_policy_name": provenance.eligibility_policy_name,
        "eligibility_policy_version": provenance.eligibility_policy_version,
    }
    for metadata_key, declared_value in expected.items():
        compiled_value = dataset.metadata.get(metadata_key)
        if compiled_value != declared_value:
            raise DatasetFreezeInvariantError(
                f"compiled dataset {metadata_key} does not match freeze provenance: "
                f"{compiled_value!r} != {declared_value!r}"
            )

    for metadata_key in (
        "eligibility_policy_hash",
        "validated_working_set_hash",
    ):
        value = dataset.metadata.get(metadata_key)
        if not isinstance(value, str) or not value.startswith("sha256:"):
            raise DatasetFreezeInvariantError(
                f"compiled dataset is missing trustworthy {metadata_key} provenance"
            )
