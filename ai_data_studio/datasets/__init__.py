from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .splits import (
    DATASET_SPLIT_MANIFEST_HASH_VERSION,
    SPLIT_MANIFEST_SCHEMA_VERSION,
    DatasetSplit,
    DatasetSplitManifest,
    SplitAssignment,
    dataset_split_manifest_hash,
)
from .eligibility import (
    GoldEligibilityEvaluator,
    GoldEligibilityPolicy,
    GoldEligibilityResult,
    GoldIneligibilityReason,
)
from .errors import (
    DatasetFreezeError,
    DatasetFreezeInvariantError,
    DatasetFreezeVerificationError,
    DatasetFreezeWriteError,
    DatasetVersionAlreadyFrozenError,
    GoldCompilationError,
    GoldDuplicateTargetError,
    GoldEligibilityError,
    GoldSourceResolutionError,
    GoldSplitResolutionError,
    GoldUnsupportedDecisionError,
)
from .hardened_freeze import (
    MANIFEST_FILENAME,
    SemanticGoldFreezer,
    verify_frozen_dataset,
    write_canonical_json,
)
from .hashing import (
    FROZEN_MANIFEST_HASH_VERSION,
    GOLD_DATASET_HASH_VERSION,
    SOURCE_CORPUS_HASH_VERSION,
    canonical_json_bytes,
    dataset_hash_from_splits,
    frozen_manifest_hash,
    semantic_gold_dataset_hash,
    semantic_gold_split_hash,
    source_corpus_hash,
)
from .manifest import (
    FROZEN_DATASET_MANIFEST_SCHEMA_VERSION,
    FreezePolicy,
    FreezeProvenance,
    FrozenDatasetManifest,
    FrozenDatasetVerificationIssue,
    FrozenDatasetVerificationIssueCode,
    FrozenDatasetVerificationReport,
    FrozenSplitArtifact,
)

if TYPE_CHECKING:
    from .hardened_compiler import (
        GOLD_ELIGIBILITY_POLICY_HASH_VERSION,
        SEMANTIC_GOLD_COMPILER_VERSION,
        SemanticGoldCompiler,
        gold_eligibility_policy_hash,
    )


def __getattr__(name: str) -> Any:
    """Load compiler symbols lazily to keep validation imports acyclic."""

    if name in {
        "GOLD_ELIGIBILITY_POLICY_HASH_VERSION",
        "SEMANTIC_GOLD_COMPILER_VERSION",
        "SemanticGoldCompiler",
        "gold_eligibility_policy_hash",
    }:
        from . import hardened_compiler as compiler_module

        return getattr(compiler_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DATASET_SPLIT_MANIFEST_HASH_VERSION",
    "FROZEN_DATASET_MANIFEST_SCHEMA_VERSION",
    "FROZEN_MANIFEST_HASH_VERSION",
    "GOLD_DATASET_HASH_VERSION",
    "GOLD_ELIGIBILITY_POLICY_HASH_VERSION",
    "MANIFEST_FILENAME",
    "SEMANTIC_GOLD_COMPILER_VERSION",
    "SOURCE_CORPUS_HASH_VERSION",
    "SPLIT_MANIFEST_SCHEMA_VERSION",
    "DatasetSplit",
    "DatasetSplitManifest",
    "DatasetFreezeError",
    "DatasetFreezeInvariantError",
    "DatasetFreezeVerificationError",
    "DatasetFreezeWriteError",
    "DatasetVersionAlreadyFrozenError",
    "FreezePolicy",
    "FreezeProvenance",
    "FrozenDatasetManifest",
    "FrozenDatasetVerificationIssue",
    "FrozenDatasetVerificationIssueCode",
    "FrozenDatasetVerificationReport",
    "FrozenSplitArtifact",
    "GoldCompilationError",
    "GoldDuplicateTargetError",
    "GoldEligibilityError",
    "GoldEligibilityEvaluator",
    "GoldEligibilityPolicy",
    "GoldEligibilityResult",
    "GoldIneligibilityReason",
    "GoldSourceResolutionError",
    "GoldSplitResolutionError",
    "GoldUnsupportedDecisionError",
    "SemanticGoldCompiler",
    "SemanticGoldFreezer",
    "SplitAssignment",
    "canonical_json_bytes",
    "dataset_hash_from_splits",
    "dataset_split_manifest_hash",
    "frozen_manifest_hash",
    "gold_eligibility_policy_hash",
    "semantic_gold_dataset_hash",
    "semantic_gold_split_hash",
    "source_corpus_hash",
    "verify_frozen_dataset",
    "write_canonical_json",
]
