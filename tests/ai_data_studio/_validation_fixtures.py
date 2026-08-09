from __future__ import annotations

from datetime import datetime, timezone

from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    SemanticWorkingRecord,
    WorkingBatch,
    WorkingSourceSnapshot,
    WorkingTarget,
)
from ai_data_studio.validation.fingerprint import (
    build_target_text_snapshot,
    working_element_snapshot_hash,
)
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import (
    CanonicalDocument,
    DocumentMetadata,
    ProcessingManifest,
    SemanticAnnotationType,
    SemanticTextView,
)
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.semantics.provider import SemanticTargetKind


CONTENT_HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def canonical_document(*, language: str | None = "en") -> CanonicalDocument:
    elements = (
        Element(
            id="e-1",
            order=0,
            type=ElementType.PARAGRAPH,
            raw_text="Gradient  descent",
            normalized_text="Gradient descent",
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="validation-fixture",
            ),
        ),
        Element(
            id="e-2",
            order=1,
            type=ElementType.PARAGRAPH,
            raw_text="minimizes loss.",
            normalized_text="minimizes loss.",
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="validation-fixture",
            ),
        ),
        Element(
            id="e-context",
            order=2,
            type=ElementType.PARAGRAPH,
            raw_text="Context only.",
            normalized_text="Context only.",
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="validation-fixture",
            ),
        ),
        Element(
            id="e-normalized-only",
            order=3,
            type=ElementType.PARAGRAPH,
            raw_text=None,
            normalized_text="Normalized only.",
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="validation-fixture",
            ),
        ),
        Element(
            id="e-raw-only",
            order=4,
            type=ElementType.PARAGRAPH,
            raw_text="Raw only.",
            normalized_text=None,
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="validation-fixture",
            ),
        ),
    )
    logical_units = (
        LogicalUnit(
            id="lu-1",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e-1", "e-2"),
            source=StructureSource.DERIVED,
            confidence=0.9,
        ),
        LogicalUnit(
            id="lu-normalized-only",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e-normalized-only",),
            source=StructureSource.DERIVED,
            confidence=0.9,
        ),
        LogicalUnit(
            id="lu-raw-only",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e-raw-only",),
            source=StructureSource.DERIVED,
            confidence=0.9,
        ),
    )
    return CanonicalDocument(
        document_id="doc-1",
        content_hash=CONTENT_HASH,
        processing=ProcessingManifest(
            adapter_name="validation-fixture",
            processed_at=NOW,
        ),
        metadata=DocumentMetadata(language=language),
        elements=elements,
        logical_units=logical_units,
    )


def working_target(
    document: CanonicalDocument,
    *,
    target_id: str = "lu-1",
    target_kind: SemanticTargetKind = SemanticTargetKind.LOGICAL_UNIT,
) -> WorkingTarget:
    elements_by_id = {element.id: element for element in document.elements}
    if target_kind == SemanticTargetKind.ELEMENT:
        selected = (elements_by_id[target_id],)
        logical_unit_type = None
    else:
        logical_unit = next(
            unit for unit in document.logical_units if unit.id == target_id
        )
        selected = tuple(
            elements_by_id[element_id] for element_id in logical_unit.element_ids
        )
        logical_unit_type = logical_unit.type.value
    return WorkingTarget(
        target_id=target_id,
        target_kind=target_kind,
        element_ids=tuple(element.id for element in selected),
        element_orders=tuple(element.order for element in selected),
        raw_text=build_target_text_snapshot(
            selected,
            view=SemanticTextView.RAW_TEXT,
        ),
        normalized_text=build_target_text_snapshot(
            selected,
            view=SemanticTextView.NORMALIZED_TEXT,
        ),
        logical_unit_type=logical_unit_type,
    )


def positive_definition() -> AnnotationDecision:
    return AnnotationDecision(
        annotation_type=SemanticAnnotationType.DEFINITION,
        state=AnnotationDecisionState.POSITIVE,
        rationale="The target states a definition.",
        confidence=AdjudicationConfidence.HIGH,
    )


def working_record(
    document: CanonicalDocument | None = None,
    **updates: object,
) -> SemanticWorkingRecord:
    canonical = document or canonical_document()
    values: dict[str, object] = {
        "record_id": "record-1",
        "batch_id": "batch-1",
        "source": WorkingSourceSnapshot(
            document_id=canonical.document_id,
            content_hash=canonical.content_hash,
            element_snapshot_hash=working_element_snapshot_hash(canonical),
            language=canonical.metadata.language or "und",
            source_family_id="family-1",
            split_group_id="group-1",
        ),
        "target": working_target(canonical),
        "evaluated_types": (SemanticAnnotationType.DEFINITION,),
    }
    values.update(updates)
    return SemanticWorkingRecord.model_validate(values)


def working_batch(**updates: object) -> WorkingBatch:
    values: dict[str, object] = {
        "batch_id": "batch-1",
        "name": "Semantic Roles",
        "guideline_version": "roles-v1",
        "created_by": "operator-1",
        "created_at": NOW,
        "evaluated_types": (SemanticAnnotationType.DEFINITION,),
        "record_ids": ("record-1",),
    }
    values.update(updates)
    return WorkingBatch.model_validate(values)
