from __future__ import annotations

from collections.abc import Mapping

from source_understanding.schemas.context import Identifier
from source_understanding.schemas.document import SemanticEvidenceSpan, SemanticTextView
from source_understanding.schemas.element import Element

from .issues import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationSeverity,
)


def validate_evidence_span(
    *,
    span: SemanticEvidenceSpan,
    allowed_element_ids: set[str],
    elements_by_id: Mapping[str, Element],
    path: str,
    record_id: Identifier | None = None,
) -> tuple[ValidationIssue, ...]:
    element = elements_by_id.get(span.element_id)
    if element is None:
        return (
            ValidationIssue(
                code=ValidationIssueCode.EVIDENCE_ELEMENT_UNKNOWN,
                severity=ValidationSeverity.ERROR,
                message=f"Evidence references unknown element {span.element_id!r}.",
                record_id=record_id,
                path=f"{path}.element_id",
                related_ids=(span.element_id,),
            ),
        )
    if span.element_id not in allowed_element_ids:
        return (
            ValidationIssue(
                code=ValidationIssueCode.EVIDENCE_OUTSIDE_TARGET,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Evidence element {span.element_id!r} is outside the working "
                    "target element scope."
                ),
                record_id=record_id,
                path=f"{path}.element_id",
                related_ids=(span.element_id,),
            ),
        )

    text = (
        element.raw_text
        if span.text_view == SemanticTextView.RAW_TEXT
        else element.normalized_text
    )
    if text is None:
        return (
            ValidationIssue(
                code=ValidationIssueCode.EVIDENCE_TEXT_VIEW_MISSING,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Element {span.element_id!r} has no "
                    f"{span.text_view.value} for this evidence span."
                ),
                record_id=record_id,
                path=f"{path}.text_view",
                related_ids=(span.element_id,),
            ),
        )
    if span.end_char > len(text):
        return (
            ValidationIssue(
                code=ValidationIssueCode.EVIDENCE_RANGE_OUT_OF_BOUNDS,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Evidence range [{span.start_char}, {span.end_char}) exceeds "
                    f"element {span.element_id!r} {span.text_view.value} length "
                    f"{len(text)}."
                ),
                record_id=record_id,
                path=path,
                related_ids=(span.element_id,),
            ),
        )
    actual = text[span.start_char : span.end_char]
    if actual != span.quoted_text:
        return (
            ValidationIssue(
                code=ValidationIssueCode.EVIDENCE_QUOTE_MISMATCH,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Evidence quote does not exactly match element "
                    f"{span.element_id!r} {span.text_view.value}."
                ),
                record_id=record_id,
                path=f"{path}.quoted_text",
                related_ids=(span.element_id,),
            ),
        )
    return ()
