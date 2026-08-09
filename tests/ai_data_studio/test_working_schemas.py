from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    AnnotationSuggestion,
    ReviewAttempt,
    ReviewerKind,
    ReviewOutcome,
    SemanticWorkingRecord,
    WorkingBatch,
    WorkingRecordStatus,
    WorkingSourceSnapshot,
    WorkingTarget,
    annotation_decisions_hash,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticEvidenceSpan,
    SemanticTextView,
)
from source_understanding.semantics import SemanticOntologyLabel, SemanticTargetKind


CONTENT_HASH = "sha256:" + "a" * 64
ELEMENT_SNAPSHOT_HASH = "sha256:" + "b" * 64
BEFORE_HASH = "sha256:" + "c" * 64
AFTER_HASH = "sha256:" + "d" * 64
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
RAW_TEXT = "Gradient descent minimizes loss."


def source_snapshot() -> WorkingSourceSnapshot:
    return WorkingSourceSnapshot(
        document_id="doc-1",
        content_hash=CONTENT_HASH,
        element_snapshot_hash=ELEMENT_SNAPSHOT_HASH,
        language="en",
        source_family_id="course-optimization",
        split_group_id="course-optimization-v1",
    )


def target() -> WorkingTarget:
    return WorkingTarget(
        target_id="lu-1",
        target_kind=SemanticTargetKind.LOGICAL_UNIT,
        element_ids=("e-1",),
        element_orders=(0,),
        raw_text=RAW_TEXT,
        normalized_text=RAW_TEXT,
        logical_unit_type="TEXT_BLOCK",
    )


def evidence(quoted_text: str = "Gradient descent") -> tuple[SemanticEvidenceSpan, ...]:
    start = RAW_TEXT.index(quoted_text)
    return (
        SemanticEvidenceSpan(
            element_id="e-1",
            start_char=start,
            end_char=start + len(quoted_text),
            quoted_text=quoted_text,
            text_view=SemanticTextView.RAW_TEXT,
        ),
    )


def positive_definition() -> AnnotationDecision:
    return AnnotationDecision(
        annotation_type=SemanticAnnotationType.DEFINITION,
        state=AnnotationDecisionState.POSITIVE,
        confidence=AdjudicationConfidence.HIGH,
        rationale="The target states what gradient descent does.",
    )


def negative_example() -> AnnotationDecision:
    return AnnotationDecision(
        annotation_type=SemanticAnnotationType.EXAMPLE,
        state=AnnotationDecisionState.NEGATIVE,
        confidence=AdjudicationConfidence.HIGH,
        negative_reason="No concrete worked example is present.",
    )


def working_record(**updates: object) -> SemanticWorkingRecord:
    values: dict[str, object] = {
        "record_id": "record-1",
        "batch_id": "batch-1",
        "source": source_snapshot(),
        "target": target(),
        "evaluated_types": (
            SemanticAnnotationType.DEFINITION,
            SemanticAnnotationType.EXAMPLE,
        ),
    }
    values.update(updates)
    return SemanticWorkingRecord.model_validate(values)


class AnnotationDecisionSchemaTests(unittest.TestCase):
    def test_negative_decision_requires_reason_and_rejects_positive_payload(self) -> None:
        with self.assertRaisesRegex(ValidationError, "require negative_reason"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.EXAMPLE,
                state=AnnotationDecisionState.NEGATIVE,
                confidence=AdjudicationConfidence.HIGH,
            )

        with self.assertRaisesRegex(ValidationError, "cannot carry positive"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.EXAMPLE,
                state=AnnotationDecisionState.NEGATIVE,
                value="An example",
                confidence=AdjudicationConfidence.HIGH,
                negative_reason="Not accepted.",
            )

    def test_undecided_decision_requires_ambiguity_rationale(self) -> None:
        with self.assertRaisesRegex(ValidationError, "ambiguity rationale"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.DEFINITION,
                state=AnnotationDecisionState.UNDECIDED,
                confidence=AdjudicationConfidence.LOW,
            )

    def test_undecided_decision_rejects_final_annotation_payload(self) -> None:
        with self.assertRaisesRegex(ValidationError, "cannot carry final"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.DEFINITION,
                state=AnnotationDecisionState.UNDECIDED,
                value="Candidate definition",
                evidence=evidence(),
                ontology=SemanticOntologyLabel(
                    namespace="education",
                    label="CANDIDATE",
                ),
                rationale="The evidence supports two competing roles.",
                confidence=AdjudicationConfidence.LOW,
            )

    def test_label_only_value_requires_task_specific_rationale(self) -> None:
        with self.assertRaisesRegex(ValidationError, "task-specific rationale"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.DEFINITION,
                state=AnnotationDecisionState.POSITIVE,
                value="Generated definition text",
                confidence=AdjudicationConfidence.MEDIUM,
            )

        decision = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.POSITIVE,
            value="Canonical rubric label used by this task.",
            rationale="This task stores the rubric-facing label as its display value.",
            confidence=AdjudicationConfidence.MEDIUM,
        )
        self.assertEqual(decision.value, "Canonical rubric label used by this task.")

    def test_positive_concept_requires_matching_evidence(self) -> None:
        with self.assertRaisesRegex(ValidationError, "requires source evidence"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.CONCEPT,
                state=AnnotationDecisionState.POSITIVE,
                value="Gradient descent",
                confidence=AdjudicationConfidence.HIGH,
            )

        with self.assertRaisesRegex(ValidationError, "must match an evidence quote"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.CONCEPT,
                state=AnnotationDecisionState.POSITIVE,
                value="Stochastic gradient descent",
                evidence=evidence(),
                confidence=AdjudicationConfidence.HIGH,
            )

    def test_positive_custom_decision_requires_ontology(self) -> None:
        with self.assertRaisesRegex(ValidationError, "require ontology"):
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.CUSTOM,
                state=AnnotationDecisionState.POSITIVE,
                confidence=AdjudicationConfidence.MEDIUM,
            )

        decision = AnnotationDecision(
            annotation_type=SemanticAnnotationType.CUSTOM,
            state=AnnotationDecisionState.POSITIVE,
            ontology=SemanticOntologyLabel(namespace="education", label="LEMMA"),
            confidence=AdjudicationConfidence.MEDIUM,
        )
        self.assertEqual(decision.ontology.key, "education:LEMMA")

    def test_suggestion_is_not_a_decision_and_preserves_score_provenance(self) -> None:
        suggestion = AnnotationSuggestion(
            agent="role-classifier",
            agent_version="1",
            annotation_type=SemanticAnnotationType.DEFINITION,
            score=0.91,
            score_method=SemanticConfidenceMethod.CALIBRATED_PROBABILITY,
            calibration_version="role-calibration-v1",
        )
        record = working_record(suggestions=(suggestion,))

        self.assertEqual(record.status, WorkingRecordStatus.DRAFT)
        self.assertEqual(record.decisions, ())
        self.assertEqual(record.suggestions[0].score, 0.91)

    def test_decision_hash_is_deterministic_and_content_sensitive(self) -> None:
        first = (positive_definition(), negative_example())
        second = (positive_definition(), negative_example())
        changed = (
            positive_definition(),
            AnnotationDecision(
                annotation_type=SemanticAnnotationType.EXAMPLE,
                state=AnnotationDecisionState.NOT_APPLICABLE,
                confidence=AdjudicationConfidence.MEDIUM,
            ),
        )

        self.assertEqual(annotation_decisions_hash(first), annotation_decisions_hash(second))
        self.assertNotEqual(annotation_decisions_hash(first), annotation_decisions_hash(changed))


class ReviewSchemaTests(unittest.TestCase):
    def test_review_timestamp_must_be_aware(self) -> None:
        with self.assertRaisesRegex(ValidationError, "timezone-aware"):
            ReviewAttempt(
                reviewer_id="reviewer-1",
                reviewer_kind=ReviewerKind.HUMAN,
                guideline_version="roles-v1",
                reviewed_at=datetime(2026, 8, 9, 12, 0),
                decision_hash_before=BEFORE_HASH,
                decision_hash_after=BEFORE_HASH,
                outcome=ReviewOutcome.ACCEPT,
            )

    def test_review_outcome_agrees_with_hash_transition(self) -> None:
        with self.assertRaisesRegex(ValidationError, "ACCEPT.*cannot change"):
            ReviewAttempt(
                reviewer_id="reviewer-1",
                reviewer_kind=ReviewerKind.HUMAN,
                guideline_version="roles-v1",
                reviewed_at=NOW,
                decision_hash_before=BEFORE_HASH,
                decision_hash_after=AFTER_HASH,
                outcome=ReviewOutcome.ACCEPT,
            )
        with self.assertRaisesRegex(ValidationError, "MODIFY.*must change"):
            ReviewAttempt(
                reviewer_id="reviewer-1",
                reviewer_kind=ReviewerKind.HUMAN,
                guideline_version="roles-v1",
                reviewed_at=NOW,
                decision_hash_before=BEFORE_HASH,
                decision_hash_after=BEFORE_HASH,
                outcome=ReviewOutcome.MODIFY,
            )


class SemanticWorkingRecordSchemaTests(unittest.TestCase):
    def test_draft_without_decisions_is_valid_and_preserves_both_text_views(self) -> None:
        record = working_record()

        self.assertEqual(record.status, WorkingRecordStatus.DRAFT)
        self.assertEqual(record.decisions, ())
        self.assertEqual(record.target.raw_text, RAW_TEXT)
        self.assertEqual(record.target.normalized_text, RAW_TEXT)
        self.assertTrue(record.decision_hash.startswith("sha256:"))

    def test_pass_requires_complete_decisions(self) -> None:
        with self.assertRaisesRegex(ValidationError, "every evaluated type"):
            working_record(
                decisions=(positive_definition(),),
                status=WorkingRecordStatus.PASS,
            )

    def test_record_rejects_duplicate_decisions_and_reversed_review_history(self) -> None:
        with self.assertRaisesRegex(ValidationError, "one decision per"):
            working_record(
                decisions=(positive_definition(), positive_definition()),
            )

        earlier = ReviewAttempt(
            reviewer_id="reviewer-1",
            reviewer_kind=ReviewerKind.HUMAN,
            guideline_version="roles-v1",
            reviewed_at=NOW,
            decision_hash_before=BEFORE_HASH,
            decision_hash_after=BEFORE_HASH,
            outcome=ReviewOutcome.ACCEPT,
        )
        later = earlier.model_copy(
            update={"reviewed_at": NOW + timedelta(minutes=5)}
        )
        with self.assertRaisesRegex(ValidationError, "reviews must be chronological"):
            working_record(reviews=(later, earlier))

    def test_pass_rejects_undecided_and_unresolved_review(self) -> None:
        undecided = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.UNDECIDED,
            confidence=AdjudicationConfidence.LOW,
            rationale="Could be explanatory rather than definitional.",
        )
        with self.assertRaisesRegex(ValidationError, "UNDECIDED"):
            working_record(
                decisions=(undecided, negative_example()),
                status=WorkingRecordStatus.PASS,
            )

        conflict = ReviewAttempt(
            reviewer_id="reviewer-2",
            reviewer_kind=ReviewerKind.HUMAN,
            guideline_version="roles-v1",
            reviewed_at=NOW,
            decision_hash_before=BEFORE_HASH,
            decision_hash_after=BEFORE_HASH,
            outcome=ReviewOutcome.CONFLICT,
            notes="Reviewers disagree on DEFINITION.",
        )
        with self.assertRaisesRegex(ValidationError, "unresolved review"):
            working_record(
                decisions=(positive_definition(), negative_example()),
                reviews=(conflict,),
                status=WorkingRecordStatus.PASS,
            )

    def test_pass_accepts_complete_decisions_and_resolved_review_history(self) -> None:
        conflict = ReviewAttempt(
            reviewer_id="critic-1",
            reviewer_kind=ReviewerKind.AI,
            guideline_version="roles-v1",
            reviewed_at=NOW,
            decision_hash_before=BEFORE_HASH,
            decision_hash_after=BEFORE_HASH,
            outcome=ReviewOutcome.CONFLICT,
            notes="Requested human adjudication.",
        )
        accepted = ReviewAttempt(
            reviewer_id="reviewer-1",
            reviewer_kind=ReviewerKind.HUMAN,
            guideline_version="roles-v1",
            reviewed_at=NOW + timedelta(minutes=5),
            decision_hash_before=AFTER_HASH,
            decision_hash_after=AFTER_HASH,
            outcome=ReviewOutcome.ACCEPT,
        )

        record = working_record(
            decisions=(positive_definition(), negative_example()),
            reviews=(conflict, accepted),
            status=WorkingRecordStatus.PASS,
        )

        self.assertEqual(record.status, WorkingRecordStatus.PASS)
        self.assertEqual(len(record.reviews), 2)


class WorkingBatchSchemaTests(unittest.TestCase):
    def test_batch_requires_aware_timestamp_and_unique_record_ids(self) -> None:
        with self.assertRaisesRegex(ValidationError, "timezone-aware"):
            WorkingBatch(
                batch_id="batch-1",
                name="Role Pilot",
                guideline_version="roles-v1",
                created_by="operator-1",
                created_at=datetime(2026, 8, 9, 12, 0),
                evaluated_types=(SemanticAnnotationType.DEFINITION,),
            )

        with self.assertRaisesRegex(ValidationError, "record_ids must be unique"):
            WorkingBatch(
                batch_id="batch-1",
                name="Role Pilot",
                guideline_version="roles-v1",
                created_by="operator-1",
                created_at=NOW,
                evaluated_types=(SemanticAnnotationType.DEFINITION,),
                record_ids=("record-1", "record-1"),
            )


if __name__ == "__main__":
    unittest.main()
