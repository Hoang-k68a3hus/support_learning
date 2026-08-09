from __future__ import annotations

from collections.abc import Sequence

from ai_data_studio.schemas.batch import WorkingBatch
from ai_data_studio.schemas.working import SemanticWorkingRecord
from source_understanding.schemas.document import CanonicalDocument, SemanticTextView
from source_understanding.schemas.element import Element
from source_understanding.schemas.logical_unit import LogicalUnit
from source_understanding.semantics.provider import SemanticTargetKind

from .batch import validate_record_batch_membership
from .evidence import validate_evidence_span
from .fingerprint import build_target_text_snapshot, working_element_snapshot_hash
from .issues import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationReport,
    ValidationSeverity,
)
from .review import validate_review_chain, validate_review_guideline


class WorkingRecordValidator:
    def validate(
        self,
        *,
        record: SemanticWorkingRecord,
        document: CanonicalDocument,
        batch: WorkingBatch,
    ) -> ValidationReport:
        elements_by_id = {element.id: element for element in document.elements}
        logical_units_by_id = {
            unit.id: unit for unit in document.logical_units
        }
        issues: list[ValidationIssue] = []

        issues.extend(self._validate_source(record=record, document=document))
        issues.extend(validate_record_batch_membership(record=record, batch=batch))

        target_elements = self._resolve_and_validate_target(
            record=record,
            elements_by_id=elements_by_id,
            logical_units_by_id=logical_units_by_id,
            issues=issues,
        )
        if target_elements is not None:
            self._validate_target_snapshots(
                record=record,
                target_elements=target_elements,
                issues=issues,
            )

        allowed_element_ids = set(record.target.element_ids)
        for decision_index, decision in enumerate(record.decisions):
            for evidence_index, span in enumerate(decision.evidence):
                issues.extend(
                    validate_evidence_span(
                        span=span,
                        allowed_element_ids=allowed_element_ids,
                        elements_by_id=elements_by_id,
                        path=(
                            f"decisions[{decision_index}].evidence["
                            f"{evidence_index}]"
                        ),
                        record_id=record.record_id,
                    )
                )
        for suggestion_index, suggestion in enumerate(record.suggestions):
            for evidence_index, span in enumerate(suggestion.evidence):
                issues.extend(
                    validate_evidence_span(
                        span=span,
                        allowed_element_ids=allowed_element_ids,
                        elements_by_id=elements_by_id,
                        path=(
                            f"suggestions[{suggestion_index}].evidence["
                            f"{evidence_index}]"
                        ),
                        record_id=record.record_id,
                    )
                )

        issues.extend(
            validate_review_chain(
                reviews=record.reviews,
                current_decision_hash=record.decision_hash,
                record_id=record.record_id,
            )
        )
        issues.extend(
            validate_review_guideline(
                reviews=record.reviews,
                batch_guideline_version=batch.guideline_version,
                record_id=record.record_id,
            )
        )
        return ValidationReport(issues=tuple(issues))

    @staticmethod
    def _validate_source(
        *,
        record: SemanticWorkingRecord,
        document: CanonicalDocument,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if record.source.document_id != document.document_id:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SOURCE_DOCUMENT_ID_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Record document_id {record.source.document_id!r} does not "
                        f"match canonical document {document.document_id!r}."
                    ),
                    record_id=record.record_id,
                    path="source.document_id",
                    related_ids=(document.document_id,),
                )
            )
        if record.source.content_hash != document.content_hash:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SOURCE_CONTENT_HASH_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message="Record content_hash does not match the canonical source revision.",
                    record_id=record.record_id,
                    path="source.content_hash",
                    related_ids=(document.document_id,),
                )
            )
        expected_snapshot_hash = working_element_snapshot_hash(document)
        if record.source.element_snapshot_hash != expected_snapshot_hash:
            issues.append(
                ValidationIssue(
                    code=(
                        ValidationIssueCode.SOURCE_ELEMENT_SNAPSHOT_HASH_MISMATCH
                    ),
                    severity=ValidationSeverity.ERROR,
                    message=(
                        "Record element snapshot hash does not match the canonical "
                        "element representation."
                    ),
                    record_id=record.record_id,
                    path="source.element_snapshot_hash",
                    related_ids=(document.document_id,),
                )
            )
        canonical_language = document.metadata.language
        if canonical_language is None:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SOURCE_LANGUAGE_UNAVAILABLE,
                    severity=ValidationSeverity.WARNING,
                    message="Canonical document language is unavailable for comparison.",
                    record_id=record.record_id,
                    path="source.language",
                    related_ids=(document.document_id,),
                )
            )
        elif record.source.language != canonical_language:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SOURCE_LANGUAGE_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Record language {record.source.language!r} does not match "
                        f"canonical language {canonical_language!r}."
                    ),
                    record_id=record.record_id,
                    path="source.language",
                    related_ids=(document.document_id,),
                )
            )
        return tuple(issues)

    @staticmethod
    def _resolve_and_validate_target(
        *,
        record: SemanticWorkingRecord,
        elements_by_id: dict[str, Element],
        logical_units_by_id: dict[str, LogicalUnit],
        issues: list[ValidationIssue],
    ) -> tuple[Element, ...] | None:
        target = record.target
        target_id = target.target_id
        element = elements_by_id.get(target_id)
        logical_unit = logical_units_by_id.get(target_id)

        expected_kind: SemanticTargetKind | None = None
        if element is not None:
            expected_kind = SemanticTargetKind.ELEMENT
        elif logical_unit is not None:
            expected_kind = SemanticTargetKind.LOGICAL_UNIT
        if expected_kind is None:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_NOT_FOUND,
                    severity=ValidationSeverity.ERROR,
                    message=f"Working target {target_id!r} does not exist in the document.",
                    record_id=record.record_id,
                    path="target.target_id",
                    related_ids=(target_id,),
                )
            )
            return None
        if target.target_kind != expected_kind:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_KIND_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Working target kind {target.target_kind.value} does not "
                        f"match canonical kind {expected_kind.value}."
                    ),
                    record_id=record.record_id,
                    path="target.target_kind",
                    related_ids=(target_id,),
                )
            )
            return None

        if expected_kind == SemanticTargetKind.ELEMENT:
            if element is None:
                raise AssertionError("resolved ELEMENT target is unavailable")
            expected_elements = (element,)
            expected_element_ids = (element.id,)
            expected_logical_type = None
        else:
            if logical_unit is None:
                raise AssertionError("resolved LOGICAL_UNIT target is unavailable")
            expected_element_ids = tuple(logical_unit.element_ids)
            expected_elements = tuple(
                elements_by_id[element_id] for element_id in expected_element_ids
            )
            expected_logical_type = logical_unit.type.value

        if target.element_ids != expected_element_ids:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_ELEMENT_IDS_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message="Working target element_ids do not exactly match the canonical target.",
                    record_id=record.record_id,
                    path="target.element_ids",
                    related_ids=tuple(
                        dict.fromkeys((target_id, *expected_element_ids))
                    ),
                )
            )
        expected_orders = tuple(item.order for item in expected_elements)
        if target.element_orders != expected_orders:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_ELEMENT_ORDERS_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message="Working target element_orders do not match canonical order.",
                    record_id=record.record_id,
                    path="target.element_orders",
                    related_ids=(target_id,),
                )
            )
        if (
            expected_kind == SemanticTargetKind.LOGICAL_UNIT
            and target.logical_unit_type != expected_logical_type
        ):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_LOGICAL_UNIT_TYPE_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Working logical_unit_type {target.logical_unit_type!r} does "
                        f"not match canonical type {expected_logical_type!r}."
                    ),
                    record_id=record.record_id,
                    path="target.logical_unit_type",
                    related_ids=(target_id,),
                )
            )
        return expected_elements

    @staticmethod
    def _validate_target_snapshots(
        *,
        record: SemanticWorkingRecord,
        target_elements: Sequence[Element],
        issues: list[ValidationIssue],
    ) -> None:
        raw_text = build_target_text_snapshot(
            target_elements,
            view=SemanticTextView.RAW_TEXT,
        )
        if record.target.raw_text != raw_text:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_RAW_TEXT_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message="Working target raw_text does not match the canonical snapshot.",
                    record_id=record.record_id,
                    path="target.raw_text",
                    related_ids=(record.target.target_id,),
                )
            )
        normalized_text = build_target_text_snapshot(
            target_elements,
            view=SemanticTextView.NORMALIZED_TEXT,
        )
        if record.target.normalized_text != normalized_text:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.TARGET_NORMALIZED_TEXT_MISMATCH,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        "Working target normalized_text does not match the "
                        "canonical snapshot."
                    ),
                    record_id=record.record_id,
                    path="target.normalized_text",
                    related_ids=(record.target.target_id,),
                )
            )
