"""M1 domain contracts for annotation working data."""

from .batch import WORKING_BATCH_SCHEMA_VERSION, WorkingBatch
from .decision import (
    ANNOTATION_DECISION_HASH_VERSION,
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    AnnotationSuggestion,
    CompetingLabelDecision,
    annotation_decisions_hash,
)
from .review import ReviewAttempt, ReviewerKind, ReviewOutcome
from .working import (
    WORKING_RECORD_SCHEMA_VERSION,
    SemanticWorkingRecord,
    WorkingRecordStatus,
    WorkingSourceSnapshot,
    WorkingTarget,
)

__all__ = [
    "ANNOTATION_DECISION_HASH_VERSION",
    "WORKING_BATCH_SCHEMA_VERSION",
    "WORKING_RECORD_SCHEMA_VERSION",
    "AdjudicationConfidence",
    "AnnotationDecision",
    "AnnotationDecisionState",
    "AnnotationSuggestion",
    "CompetingLabelDecision",
    "ReviewAttempt",
    "ReviewerKind",
    "ReviewOutcome",
    "SemanticWorkingRecord",
    "WorkingBatch",
    "WorkingRecordStatus",
    "WorkingSourceSnapshot",
    "WorkingTarget",
    "annotation_decisions_hash",
]
