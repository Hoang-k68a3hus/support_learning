"""Optional semantic understanding after structural CanonicalDocument assembly."""

from .annotator import (
    SEMANTIC_ANNOTATOR_VERSION,
    SemanticAnnotationError,
    SemanticAnnotationPolicy,
    SemanticAnnotationResult,
    SemanticAnnotator,
)
from .heuristic import (
    HEURISTIC_SEMANTIC_PROVIDER_VERSION,
    HeuristicSemanticProvider,
)
from .provider import (
    SEMANTIC_PROVIDER_PROTOCOL_VERSION,
    SemanticCandidate,
    SemanticCapability,
    SemanticOntologyLabel,
    SemanticProvider,
    SemanticProviderCapabilities,
    SemanticRequest,
    SemanticTargetKind,
)
from .quality import SemanticCoverageReport, evaluate_semantic_coverage

__all__ = [
    "HEURISTIC_SEMANTIC_PROVIDER_VERSION",
    "SEMANTIC_ANNOTATOR_VERSION",
    "SEMANTIC_PROVIDER_PROTOCOL_VERSION",
    "HeuristicSemanticProvider",
    "SemanticAnnotationError",
    "SemanticAnnotationPolicy",
    "SemanticAnnotationResult",
    "SemanticAnnotator",
    "SemanticCandidate",
    "SemanticCapability",
    "SemanticCoverageReport",
    "SemanticOntologyLabel",
    "SemanticProvider",
    "SemanticProviderCapabilities",
    "SemanticRequest",
    "SemanticTargetKind",
    "evaluate_semantic_coverage",
]
