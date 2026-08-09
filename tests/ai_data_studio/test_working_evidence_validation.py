from __future__ import annotations

import unittest

from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    AnnotationSuggestion,
)
from ai_data_studio.validation import (
    ValidationIssueCode,
    WorkingRecordValidator,
    validate_evidence_span,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticEvidenceSpan,
    SemanticTextView,
)
from tests.ai_data_studio._validation_fixtures import (
    canonical_document,
    working_batch,
    working_record,
    working_target,
)


def exact_span(
    element_id: str,
    text: str,
    quote: str,
    *,
    view: SemanticTextView,
) -> SemanticEvidenceSpan:
    start = text.index(quote)
    return SemanticEvidenceSpan(
        element_id=element_id,
        start_char=start,
        end_char=start + len(quote),
        quoted_text=quote,
        text_view=view,
    )


class WorkingEvidenceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = canonical_document()
        self.elements_by_id = {
            element.id: element for element in self.document.elements
        }

    def validate(self, span: SemanticEvidenceSpan) -> tuple[ValidationIssueCode, ...]:
        return tuple(
            issue.code
            for issue in validate_evidence_span(
                span=span,
                allowed_element_ids={"e-1", "e-2"},
                elements_by_id=self.elements_by_id,
                path="decisions[0].evidence[0]",
                record_id="record-1",
            )
        )

    def test_raw_evidence_exact_quote_passes(self) -> None:
        span = exact_span(
            "e-1",
            "Gradient  descent",
            "descent",
            view=SemanticTextView.RAW_TEXT,
        )
        self.assertEqual(self.validate(span), ())

    def test_normalized_evidence_exact_quote_passes(self) -> None:
        span = exact_span(
            "e-1",
            "Gradient descent",
            "descent",
            view=SemanticTextView.NORMALIZED_TEXT,
        )
        self.assertEqual(self.validate(span), ())

    def test_unknown_evidence_element_rejected(self) -> None:
        span = SemanticEvidenceSpan(
            element_id="missing",
            start_char=0,
            end_char=4,
            quoted_text="text",
        )
        self.assertEqual(
            self.validate(span),
            (ValidationIssueCode.EVIDENCE_ELEMENT_UNKNOWN,),
        )

    def test_context_element_cannot_be_used_as_target_evidence(self) -> None:
        span = exact_span(
            "e-context",
            "Context only.",
            "Context",
            view=SemanticTextView.RAW_TEXT,
        )
        self.assertEqual(
            self.validate(span),
            (ValidationIssueCode.EVIDENCE_OUTSIDE_TARGET,),
        )

    def test_missing_raw_view_rejected_without_fallback(self) -> None:
        span = SemanticEvidenceSpan(
            element_id="e-normalized-only",
            start_char=0,
            end_char=10,
            quoted_text="Normalized",
            text_view=SemanticTextView.RAW_TEXT,
        )
        issues = validate_evidence_span(
            span=span,
            allowed_element_ids={"e-normalized-only"},
            elements_by_id=self.elements_by_id,
            path="decisions[0].evidence[0]",
        )
        self.assertEqual(
            tuple(issue.code for issue in issues),
            (ValidationIssueCode.EVIDENCE_TEXT_VIEW_MISSING,),
        )

    def test_missing_normalized_view_rejected_without_fallback(self) -> None:
        span = SemanticEvidenceSpan(
            element_id="e-raw-only",
            start_char=0,
            end_char=8,
            quoted_text="Raw only",
            text_view=SemanticTextView.NORMALIZED_TEXT,
        )
        issues = validate_evidence_span(
            span=span,
            allowed_element_ids={"e-raw-only"},
            elements_by_id=self.elements_by_id,
            path="suggestions[0].evidence[0]",
        )
        self.assertEqual(
            tuple(issue.code for issue in issues),
            (ValidationIssueCode.EVIDENCE_TEXT_VIEW_MISSING,),
        )

    def test_evidence_end_out_of_bounds_rejected(self) -> None:
        span = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=20,
            end_char=25,
            quoted_text="xxxxx",
            text_view=SemanticTextView.RAW_TEXT,
        )
        self.assertEqual(
            self.validate(span),
            (ValidationIssueCode.EVIDENCE_RANGE_OUT_OF_BOUNDS,),
        )

    def test_evidence_quote_mismatch_rejected_without_normalization(self) -> None:
        span = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=0,
            end_char=8,
            quoted_text="gradient",
            text_view=SemanticTextView.RAW_TEXT,
        )
        self.assertEqual(
            self.validate(span),
            (ValidationIssueCode.EVIDENCE_QUOTE_MISMATCH,),
        )

    def test_valid_decision_and_suggestion_evidence_pass(self) -> None:
        span = exact_span(
            "e-1",
            "Gradient  descent",
            "Gradient",
            view=SemanticTextView.RAW_TEXT,
        )
        decision = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.POSITIVE,
            evidence=(span,),
            rationale="The target is definitional.",
            confidence=AdjudicationConfidence.HIGH,
        )
        suggestion = AnnotationSuggestion(
            agent="role-classifier",
            agent_version="1",
            annotation_type=SemanticAnnotationType.DEFINITION,
            evidence=(span,),
            score_method=SemanticConfidenceMethod.UNCALIBRATED,
        )
        record = working_record(
            self.document,
            decisions=(decision,),
            suggestions=(suggestion,),
        )

        report = WorkingRecordValidator().validate(
            record=record,
            document=self.document,
            batch=working_batch(),
        )

        self.assertTrue(report.is_valid)

    def test_stale_suggestion_evidence_is_reported_with_exact_path(self) -> None:
        stale = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=0,
            end_char=8,
            quoted_text="gradient",
            text_view=SemanticTextView.RAW_TEXT,
        )
        suggestion = AnnotationSuggestion(
            agent="role-classifier",
            agent_version="1",
            annotation_type=SemanticAnnotationType.DEFINITION,
            evidence=(stale,),
            score_method=SemanticConfidenceMethod.UNCALIBRATED,
        )
        record = working_record(self.document, suggestions=(suggestion,))

        report = WorkingRecordValidator().validate(
            record=record,
            document=self.document,
            batch=working_batch(),
        )

        issue = next(
            item
            for item in report.issues
            if item.code == ValidationIssueCode.EVIDENCE_QUOTE_MISMATCH
        )
        self.assertEqual(issue.path, "suggestions[0].evidence[0].quoted_text")

    def test_stale_decision_evidence_is_reported_with_exact_path(self) -> None:
        stale = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=0,
            end_char=8,
            quoted_text="gradient",
            text_view=SemanticTextView.RAW_TEXT,
        )
        decision = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.POSITIVE,
            evidence=(stale,),
            rationale="The target is definitional.",
            confidence=AdjudicationConfidence.HIGH,
        )
        record = working_record(self.document, decisions=(decision,))

        report = WorkingRecordValidator().validate(
            record=record,
            document=self.document,
            batch=working_batch(),
        )

        issue = next(
            item
            for item in report.issues
            if item.code == ValidationIssueCode.EVIDENCE_QUOTE_MISMATCH
        )
        self.assertEqual(issue.path, "decisions[0].evidence[0].quoted_text")


if __name__ == "__main__":
    unittest.main()
