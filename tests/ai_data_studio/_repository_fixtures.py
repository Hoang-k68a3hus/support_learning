from __future__ import annotations

from datetime import datetime, timezone

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
    WorkingTarget,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticEvidenceSpan,
    SemanticTextView,
)
from source_understanding.semantics import SemanticTargetKind


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def make_repository_record(
    *,
    record_id: str = "record-1",
    batch_id: str = "batch-1",
    hash_token: str = "a",
    snapshot_token: str = "b",
    target_order: int = 0,
    raw_text: str = "Định nghĩa thuật toán tìm kiếm.",
    normalized_text: str | None = "Định nghĩa thuật toán tìm kiếm.",
    status: WorkingRecordStatus = WorkingRecordStatus.DRAFT,
    suggestions: tuple[AnnotationSuggestion, ...] = (),
    decisions: tuple[AnnotationDecision, ...] = (),
    reviews: tuple[ReviewAttempt, ...] = (),
    metadata: dict[str, object] | None = None,
) -> SemanticWorkingRecord:
    element_id = f"element-{record_id}-{target_order}"
    return SemanticWorkingRecord(
        record_id=record_id,
        batch_id=batch_id,
        source=WorkingSourceSnapshot(
            document_id=f"document-{record_id}",
            content_hash="sha256:" + hash_token * 64,
            element_snapshot_hash="sha256:" + snapshot_token * 64,
            language="vi",
            source_family_id=f"family-{record_id}",
            split_group_id=f"group-{record_id}",
        ),
        target=WorkingTarget(
            target_id=f"target-{record_id}",
            target_kind=SemanticTargetKind.ELEMENT,
            element_ids=(element_id,),
            element_orders=(target_order,),
            raw_text=raw_text,
            normalized_text=normalized_text,
        ),
        evaluated_types=(SemanticAnnotationType.DEFINITION,),
        suggestions=suggestions,
        decisions=decisions,
        reviews=reviews,
        status=status,
        metadata=metadata or {},
    )


def make_rich_repository_record() -> SemanticWorkingRecord:
    raw_text = "Định nghĩa thuật toán tìm kiếm.\nVí dụ minh họa."
    quoted_text = "thuật toán tìm kiếm"
    start = raw_text.index(quoted_text)
    evidence = (
        SemanticEvidenceSpan(
            element_id="element-record-rich-0",
            start_char=start,
            end_char=start + len(quoted_text),
            quoted_text=quoted_text,
            text_view=SemanticTextView.RAW_TEXT,
        ),
    )
    suggestion = AnnotationSuggestion(
        agent="role-classifier",
        agent_version="1",
        annotation_type=SemanticAnnotationType.DEFINITION,
        evidence=evidence,
        score=0.91,
        score_method=SemanticConfidenceMethod.CALIBRATED_PROBABILITY,
        calibration_version="role-calibration-v1",
    )
    decision = AnnotationDecision(
        annotation_type=SemanticAnnotationType.DEFINITION,
        state=AnnotationDecisionState.POSITIVE,
        evidence=evidence,
        rationale="Đoạn văn nêu định nghĩa trực tiếp.",
        confidence=AdjudicationConfidence.HIGH,
    )
    provisional = make_repository_record(
        record_id="record-rich",
        raw_text=raw_text,
        normalized_text=(
            "Định nghĩa thuật toán tìm kiếm. Ví dụ minh họa."
        ),
        suggestions=(suggestion,),
        decisions=(decision,),
        metadata={"source_note": "Dữ liệu tiếng Việt"},
    )
    review = ReviewAttempt(
        reviewer_id="reviewer-1",
        reviewer_kind=ReviewerKind.HUMAN,
        guideline_version="roles-v1",
        reviewed_at=NOW,
        decision_hash_before=provisional.decision_hash,
        decision_hash_after=provisional.decision_hash,
        outcome=ReviewOutcome.ACCEPT,
        notes="Giữ nguyên nhãn và bằng chứng.",
    )
    payload = provisional.model_dump(mode="python")
    payload.update(
        {
            "reviews": (review,),
            "status": WorkingRecordStatus.PASS,
        }
    )
    return SemanticWorkingRecord.model_validate(payload)
