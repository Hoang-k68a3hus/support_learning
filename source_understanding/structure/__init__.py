"""Structural evidence extraction and local boundary scoring."""

from .boundary import (
    BOUNDARY_POLICY_VERSION,
    BOUNDARY_VERSION,
    BoundaryClass,
    BoundaryComponents,
    BoundaryDecision,
    BoundaryError,
    BoundaryIntegrityGuard,
    BoundaryPolicy,
    BoundaryReason,
    BoundaryScorer,
    BoundarySet,
)
from .signals import (
    STRUCTURE_SIGNAL_VERSION,
    StructureSignal,
    StructureSignalError,
    StructureSignalExtractor,
    StructureSignalKind,
    StructureSignalSet,
)

__all__ = [
    "BOUNDARY_POLICY_VERSION",
    "BOUNDARY_VERSION",
    "BoundaryClass",
    "BoundaryComponents",
    "BoundaryDecision",
    "BoundaryError",
    "BoundaryIntegrityGuard",
    "BoundaryPolicy",
    "BoundaryReason",
    "BoundaryScorer",
    "BoundarySet",
    "STRUCTURE_SIGNAL_VERSION",
    "StructureSignal",
    "StructureSignalError",
    "StructureSignalExtractor",
    "StructureSignalKind",
    "StructureSignalSet",
]
