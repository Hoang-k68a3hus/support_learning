from __future__ import annotations

from datetime import datetime, timezone

from ai_data_studio.datasets import (
    DatasetSplit,
    DatasetSplitManifest,
    SplitAssignment,
)
from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    AnnotationSuggestion,
    ReviewAttempt,
    ReviewerKind,
    ReviewOutcome,
    SemanticWorkingRecord,
    WorkingRecordStatus,
    WorkingSourceSnapshot,
)
from ai_data_studio.validation import working_element_snapshot_hash
from source_understanding.schemas.document import (
    CanonicalDocument,
    SemanticAnnotationType,
    SemanticEvidenceSpan,
)
from source_understanding.semantics import (
    SemanticOntologyLabel,
    SemanticTargetKind,
)

from ._validation_fixtures import canonical_document, working_target


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def document_variant(
    *,
    document_id: str,
    content_token: str,
) -> CanonicalDocument:
    return canonical_document().model_copy(
        update={
            "document_id": document_id,
            "content_hash": "sha256:" + content_token * 64,
        }
    )


def positive_decision(
    annotation_type: SemanticAnnotationType = SemanticAnnotationType.DEFINITION,
    *,
    confidence: AdjudicationConfidence = AdjudicationConfidence.HIGH,
    rule_keys: tuple[str, ...] = ("gold.explicit-marker",),
    value: str | None = None,
    evidence: tuple[SemanticEvidenceSpan, ...] = (),
    ontology: SemanticOntologyLabel | None = None,
) -> AnnotationDecision:
    return AnnotationDecision(
        annotation_type=annotation_type,
        state=AnnotationDecisionState.POSITIVE,
        value=value,
        evidence=evidence,
        ontology=ontology,
        rule_keys=rule_keys,
        rationale="The adjudicated source supports this positive label.",
        confidence=confidence,
    )


def negative_decision(
    annotation_type: SemanticAnnotationType,
    *,
    confidence: AdjudicationConfidence = AdjudicationConfidence.HIGH,
) -> AnnotationDecision:
    return AnnotationDecision(
        annotation_type=annotation_type,
        state=AnnotationDecisionState.NEGATIVE,
        confidence=confidence,
        negative_reason="The adjudicated source does not express this label.",
    )


def not_applicable_decision(
    annotation_type: SemanticAnnotationType,
) -> AnnotationDecision:
    return AnnotationDecision(
        annotation_type=annotation_type,
        state=AnnotationDecisionState.NOT_APPLICABLE,
        confidence=AdjudicationConfidence.HIGH,
    )


def adjudicated_record(
    *,
    document: CanonicalDocument | None = None,
    record_id: str = "record-1",
    target_id: str = "lu-1",
    target_kind: SemanticTargetKind = SemanticTargetKind.LOGICAL_UNIT,
    decisions: tuple[AnnotationDecision, ...] | None = None,
    status: WorkingRecordStatus = WorkingRecordStatus.PASS,
    with_review: bool = True,
    batch_id: str = "batch-1",
    source_family_id: str = "family-1",
    split_group_id: str = "group-1",
    suggestions: tuple[AnnotationSuggestion, ...] = (),
    metadata: dict[str, object] | None = None,
) -> SemanticWorkingRecord:
    canonical = document or canonical_document()
    selected_decisions = decisions or (positive_decision(),)
    evaluated_types = tuple(
        annotation_type
        for annotation_type in SemanticAnnotationType
        if annotation_type in {
            decision.annotation_type for decision in selected_decisions
        }
    )
    provisional = SemanticWorkingRecord(
        record_id=record_id,
        batch_id=batch_id,
        source=WorkingSourceSnapshot(
            document_id=canonical.document_id,
            content_hash=canonical.content_hash,
            element_snapshot_hash=working_element_snapshot_hash(canonical),
            language=canonical.metadata.language or "und",
            source_family_id=source_family_id,
            split_group_id=split_group_id,
        ),
        target=working_target(
            canonical,
            target_id=target_id,
            target_kind=target_kind,
        ),
        evaluated_types=evaluated_types,
        suggestions=suggestions,
        decisions=selected_decisions,
        status=status,
        metadata=metadata or {},
    )
    if not with_review:
        return provisional
    review = ReviewAttempt(
        reviewer_id="reviewer-1",
        reviewer_kind=ReviewerKind.HUMAN,
        guideline_version="roles-v1",
        reviewed_at=NOW,
        decision_hash_before=provisional.decision_hash,
        decision_hash_after=provisional.decision_hash,
        outcome=ReviewOutcome.ACCEPT,
        notes="Reviewed against the pilot semantic guideline.",
    )
    payload = provisional.model_dump(mode="python")
    payload["reviews"] = (review,)
    return SemanticWorkingRecord.model_validate(payload)


def split_manifest(
    *assignments: tuple[str, DatasetSplit],
) -> DatasetSplitManifest:
    return DatasetSplitManifest(
        name="semantic-gold-splits",
        dataset_version="semantic-gold-splits-v1",
        assignments=tuple(
            SplitAssignment(split_group_id=group_id, split=split)
            for group_id, split in sorted(assignments)
        ),
        created_by="operator-1",
        created_at=NOW,
    )
