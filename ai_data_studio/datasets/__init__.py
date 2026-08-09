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
from .freeze import (
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
    from .compiler import SemanticGoldCompiler


def __getattr__(name: str) -> Any:
    """Load compiler symbols lazily to keep validation imports acyclic.

    ``ai_data_studio.validation.split`` depends only on the split contract.  An
    eager compiler import here would pull ``ai_data_studio.validation`` back in
    while that package is still initializing, making clean-process imports
    depend on import order.
    """

    if name in {"SEMANTIC_GOLD_COMPILER_VERSION", "SemanticGoldCompiler"}:
        from . import compiler as compiler_module

        return getattr(compiler_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DATASET_SPLIT_MANIFEST_HASH_VERSION",
    "FROZEN_DATASET_MANIFEST_SCHEMA_VERSION",
    "FROZEN_MANIFEST_HASH_VERSION",
    "GOLD_DATASET_HASH_VERSION",
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
    "semantic_gold_dataset_hash",
    "semantic_gold_split_hash",
    "source_corpus_hash",
    "verify_frozen_dataset",
    "write_canonical_json",
]
