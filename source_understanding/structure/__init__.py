"""Structural evidence extraction, boundary scoring, and logical grouping."""

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
from .dialogue import DialogueSegmentBuilder, DialogueSegmentCandidate
from .grouping import (
    GROUPING_POLICY_VERSION,
    GROUPING_VERSION,
    GroupingError,
    GroupingPolicy,
    GroupingResult,
    LogicalGroupBuilder,
)
from .log import LogWindowBuilder, LogWindowCandidate
from .qa import QAPairBuilder, QAPairCandidate, QAPairRule
from .signals import (
    STRUCTURE_SIGNAL_VERSION,
    StructureSignal,
    StructureSignalError,
    StructureSignalExtractor,
    StructureSignalKind,
    StructureSignalSet,
)
from .subdocument import SubDocumentDetector

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
    "DialogueSegmentBuilder",
    "DialogueSegmentCandidate",
    "GROUPING_POLICY_VERSION",
    "GROUPING_VERSION",
    "GroupingError",
    "GroupingPolicy",
    "GroupingResult",
    "LogicalGroupBuilder",
    "LogWindowBuilder",
    "LogWindowCandidate",
    "QAPairBuilder",
    "QAPairCandidate",
    "QAPairRule",
    "STRUCTURE_SIGNAL_VERSION",
    "StructureSignal",
    "StructureSignalError",
    "StructureSignalExtractor",
    "StructureSignalKind",
    "StructureSignalSet",
    "SubDocumentDetector",
]
