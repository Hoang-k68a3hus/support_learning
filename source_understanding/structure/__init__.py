"""Structural evidence extraction, boundary scoring, grouping, hierarchy, and integration."""

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
from .hierarchy import (
    HIERARCHY_POLICY_VERSION,
    HIERARCHY_VERSION,
    ElementContextAssignment,
    HierarchyBuilder,
    HierarchyError,
    HierarchyPolicy,
    HierarchyResult,
)
from .integration import (
    CONTEXT_INTEGRATION_VERSION,
    ContextIntegrationError,
    ContextIntegrationResult,
    ContextIntegrator,
)
from .log import LogWindowBuilder, LogWindowCandidate
from .qa import QAPairBuilder, QAPairCandidate, QAPairRule
from .quality import (
    STRUCTURE_QUALITY_VERSION,
    StructureQualityError,
    StructureQualityEstimator,
    StructureQualityMetrics,
    StructureQualityPolicy,
    StructureQualityReport,
)
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
    "CONTEXT_INTEGRATION_VERSION",
    "ContextIntegrationError",
    "ContextIntegrationResult",
    "ContextIntegrator",
    "DialogueSegmentBuilder",
    "DialogueSegmentCandidate",
    "ElementContextAssignment",
    "GROUPING_POLICY_VERSION",
    "GROUPING_VERSION",
    "GroupingError",
    "GroupingPolicy",
    "GroupingResult",
    "HIERARCHY_POLICY_VERSION",
    "HIERARCHY_VERSION",
    "HierarchyBuilder",
    "HierarchyError",
    "HierarchyPolicy",
    "HierarchyResult",
    "LogicalGroupBuilder",
    "LogWindowBuilder",
    "LogWindowCandidate",
    "QAPairBuilder",
    "QAPairCandidate",
    "QAPairRule",
    "STRUCTURE_QUALITY_VERSION",
    "STRUCTURE_SIGNAL_VERSION",
    "StructureQualityError",
    "StructureQualityEstimator",
    "StructureQualityMetrics",
    "StructureQualityPolicy",
    "StructureQualityReport",
    "StructureSignal",
    "StructureSignalError",
    "StructureSignalExtractor",
    "StructureSignalKind",
    "StructureSignalSet",
    "SubDocumentDetector",
]
