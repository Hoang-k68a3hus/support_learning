"""Deterministic structural relation construction."""

from .builder import (
    RELATION_BUILDER_VERSION,
    RelationBuildError,
    RelationBuildDiagnostic,
    RelationBuildPolicy,
    RelationBuildResult,
    RelationDiagnosticOutcome,
    StructuralRelationBuilder,
)
from .table_continuation import (
    TABLE_CONTINUATION_CONTRACT_VERSION,
    TABLE_CONTINUATION_EVIDENCE_COMPARISON_TOLERANCE,
    TABLE_CONTINUATION_EVIDENCE_ATTRIBUTE,
    TableContinuationEvidence,
)

__all__ = [
    "RELATION_BUILDER_VERSION",
    "RelationBuildError",
    "RelationBuildDiagnostic",
    "RelationBuildPolicy",
    "RelationBuildResult",
    "RelationDiagnosticOutcome",
    "StructuralRelationBuilder",
    "TABLE_CONTINUATION_CONTRACT_VERSION",
    "TABLE_CONTINUATION_EVIDENCE_COMPARISON_TOLERANCE",
    "TABLE_CONTINUATION_EVIDENCE_ATTRIBUTE",
    "TableContinuationEvidence",
]
