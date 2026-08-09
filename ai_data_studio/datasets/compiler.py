from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from ai_data_studio.schemas import (
    WORKING_RECORD_SCHEMA_VERSION,
    AnnotationDecision,
    AnnotationDecisionState,
    SemanticWorkingRecord,
)
from ai_data_studio.validation import (
    InvalidDatasetSplitError,
    resolve_record_splits,
    working_element_snapshot_hash,
)
from source_understanding.evaluation import (
    BenchmarkSplit,
    GoldSemanticAnnotation,
    GoldSemanticDocument,
    GoldSemanticElement,
    GoldSemanticEvaluationScope,
    GoldSemanticTarget,
    SemanticGoldDataset,
    semantic_element_snapshot_hash,
)
from source_understanding.evaluation.semantic import GoldSemanticEvidenceSpan
from source_understanding.schemas.context import Identifier
from source_understanding.schemas.document import (
    CanonicalDocument,
    SemanticAnnotationType,
)

from .eligibility import (
    GoldEligibilityEvaluator,
    GoldEligibilityPolicy,
)
from .errors import (
    GoldDuplicateTargetError,
    GoldEligibilityError,
    GoldSourceResolutionError,
    GoldSplitResolutionError,
    GoldUnsupportedDecisionError,
)
from .splits import (
    DatasetSplit,
    DatasetSplitManifest,
    dataset_split_manifest_hash,
)


SEMANTIC_GOLD_COMPILER_VERSION = "1"


class SemanticGoldCompiler:
    version = SEMANTIC_GOLD_COMPILER_VERSION

    def __init__(self) -> None:
        self._eligibility = GoldEligibilityEvaluator()

    def compile_document(
        self,
        *,
        document: CanonicalDocument,
        records: Sequence[SemanticWorkingRecord],
        split: DatasetSplit,
        policy: GoldEligibilityPolicy,
    ) -> GoldSemanticDocument:
        if not records:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: no working records"
            )
        self._validate_document_sources(document=document, records=records)
        self._validate_supported_decisions(records)
        self._require_eligible(records=records, policy=policy)

        ordered_records = tuple(sorted(records, key=_record_target_sort_key))
        seen_targets: dict[tuple[object, ...], str] = {}
        element_order_by_id = {
            element.id: element.order for element in document.elements
        }
        scopes: list[GoldSemanticEvaluationScope] = []
        annotations: list[GoldSemanticAnnotation] = []

        for record in ordered_records:
            target_key = (
                record.target.target_kind,
                record.target.element_orders,
            )
            previous_record_id = seen_targets.get(target_key)
            if previous_record_id is not None:
                raise GoldDuplicateTargetError(
                    f"cannot compile document {document.document_id!r}: records "
                    f"{previous_record_id!r} and {record.record_id!r} claim duplicate "
                    f"target {record.target.target_kind.value}:"
                    f"{record.target.element_orders!r}"
                )
            seen_targets[target_key] = record.record_id

            target = GoldSemanticTarget(
                kind=record.target.target_kind,
                element_orders=record.target.element_orders,
            )
            scopes.append(
                GoldSemanticEvaluationScope(
                    target=target,
                    evaluated_types=record.evaluated_types,
                )
            )
            for decision in sorted(
                record.decisions,
                key=lambda item: _ANNOTATION_TYPE_RANK[item.annotation_type],
            ):
                if decision.state == AnnotationDecisionState.POSITIVE:
                    annotations.append(
                        _compile_positive_decision(
                            record=record,
                            decision=decision,
                            target=target,
                            element_order_by_id=element_order_by_id,
                        )
                    )
                elif decision.state in {
                    AnnotationDecisionState.NEGATIVE,
                    AnnotationDecisionState.NOT_APPLICABLE,
                }:
                    continue
                else:
                    raise GoldUnsupportedDecisionError(
                        f"cannot compile record {record.record_id!r}: decision "
                        f"{decision.annotation_type.value} has unsupported state "
                        f"{decision.state.value}"
                    )

        gold_elements = tuple(
            GoldSemanticElement(
                order=element.order,
                raw_text=element.raw_text,
                normalized_text=element.normalized_text,
                type=element.type,
            )
            for element in sorted(document.elements, key=lambda item: item.order)
        )
        ordered_scopes = tuple(sorted(scopes, key=_scope_sort_key))
        ordered_annotations = tuple(
            sorted(annotations, key=_annotation_sort_key)
        )
        language = document.metadata.language
        if language is None:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: canonical "
                "document language is unavailable"
            )
        return GoldSemanticDocument(
            document_id=document.document_id,
            content_hash=document.content_hash,
            element_snapshot_hash=semantic_element_snapshot_hash(gold_elements),
            split=BenchmarkSplit(split.value),
            language=language,
            elements=gold_elements,
            evaluation_scopes=ordered_scopes,
            annotations=ordered_annotations,
            metadata={
                "compiler_version": self.version,
                "working_record_ids": [
                    record.record_id
                    for record in sorted(records, key=lambda item: item.record_id)
                ],
            },
        )

    def compile_dataset(
        self,
        *,
        name: str,
        documents: Mapping[Identifier, CanonicalDocument],
        records: Sequence[SemanticWorkingRecord],
        split_manifest: DatasetSplitManifest,
        policy: GoldEligibilityPolicy,
    ) -> SemanticGoldDataset:
        if not records:
            raise GoldSourceResolutionError(
                "cannot compile semantic gold dataset without working records"
            )
        for document_id, document in documents.items():
            if document_id != document.document_id:
                raise GoldSourceResolutionError(
                    f"canonical document mapping key {document_id!r} does not match "
                    f"document_id {document.document_id!r}"
                )
        try:
            record_splits = resolve_record_splits(
                records=records,
                manifest=split_manifest,
            )
        except InvalidDatasetSplitError as exc:
            codes = ", ".join(issue.code.value for issue in exc.report.errors)
            raise GoldSplitResolutionError(
                f"cannot compile semantic gold dataset: invalid split topology: {codes}"
            ) from exc

        self._validate_supported_decisions(records)
        self._require_eligible(records=records, policy=policy)

        records_by_document: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
        for record in records:
            records_by_document[record.source.document_id].append(record)

        cases: list[GoldSemanticDocument] = []
        for document_id in sorted(records_by_document):
            document = documents.get(document_id)
            if document is None:
                raise GoldSourceResolutionError(
                    f"cannot compile document {document_id!r}: "
                    "CanonicalDocument is missing"
                )
            document_records = records_by_document[document_id]
            splits = {
                record_splits[record.record_id] for record in document_records
            }
            if len(splits) != 1:
                raise GoldSplitResolutionError(
                    f"cannot compile document {document_id!r}: working records "
                    f"resolve to multiple splits: "
                    f"{sorted(split.value for split in splits)!r}"
                )
            cases.append(
                self.compile_document(
                    document=document,
                    records=document_records,
                    split=next(iter(splits)),
                    policy=policy,
                )
            )

        return SemanticGoldDataset(
            name=name,
            cases=tuple(sorted(cases, key=lambda case: case.document_id)),
            metadata={
                "compiler_version": self.version,
                "working_schema_version": WORKING_RECORD_SCHEMA_VERSION,
                "split_manifest_hash": dataset_split_manifest_hash(split_manifest),
                "eligibility_policy": policy.model_dump(mode="json"),
            },
        )

    def _require_eligible(
        self,
        *,
        records: Sequence[SemanticWorkingRecord],
        policy: GoldEligibilityPolicy,
    ) -> None:
        record_reasons: list[tuple[str, tuple[str, ...]]] = []
        for record in sorted(records, key=lambda item: item.record_id):
            result = self._eligibility.evaluate(record, policy=policy)
            if not result.eligible:
                record_reasons.append(
                    (
                        record.record_id,
                        tuple(reason.value for reason in result.reasons),
                    )
                )
        if record_reasons:
            raise GoldEligibilityError(tuple(record_reasons))

    @staticmethod
    def _validate_supported_decisions(
        records: Sequence[SemanticWorkingRecord],
    ) -> None:
        supported_states = {
            AnnotationDecisionState.POSITIVE,
            AnnotationDecisionState.NEGATIVE,
            AnnotationDecisionState.NOT_APPLICABLE,
        }
        for record in sorted(records, key=lambda item: item.record_id):
            for decision in sorted(
                record.decisions,
                key=lambda item: _ANNOTATION_TYPE_RANK[item.annotation_type],
            ):
                if decision.state not in supported_states:
                    raise GoldUnsupportedDecisionError(
                        f"cannot compile record {record.record_id!r}: decision "
                        f"{decision.annotation_type.value} has unsupported state "
                        f"{decision.state.value}"
                    )

    @staticmethod
    def _validate_document_sources(
        *,
        document: CanonicalDocument,
        records: Sequence[SemanticWorkingRecord],
    ) -> None:
        if not document.elements:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: canonical "
                "document has no elements"
            )
        document_ids = {record.source.document_id for record in records}
        if document_ids != {document.document_id}:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working record "
                f"document_ids are {sorted(document_ids)!r}"
            )
        content_hashes = {record.source.content_hash for record in records}
        if len(content_hashes) != 1:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working records "
                f"resolve to multiple source revisions: {sorted(content_hashes)!r}"
            )
        if content_hashes != {document.content_hash}:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working record "
                "content_hash does not match the canonical source revision"
            )

        snapshot_hashes = {
            record.source.element_snapshot_hash for record in records
        }
        if len(snapshot_hashes) != 1:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working records "
                "resolve to multiple element snapshots"
            )
        expected_snapshot_hash = working_element_snapshot_hash(document)
        if snapshot_hashes != {expected_snapshot_hash}:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working record "
                "element_snapshot_hash does not match the canonical document"
            )

        languages = {record.source.language for record in records}
        if len(languages) != 1:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working records "
                f"declare multiple languages: {sorted(languages)!r}"
            )
        if document.metadata.language is None:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: canonical "
                "document language is unavailable"
            )
        if languages != {document.metadata.language}:
            raise GoldSourceResolutionError(
                f"cannot compile document {document.document_id!r}: working record "
                "language does not match the canonical document"
            )


def _compile_positive_decision(
    *,
    record: SemanticWorkingRecord,
    decision: AnnotationDecision,
    target: GoldSemanticTarget,
    element_order_by_id: Mapping[str, int],
) -> GoldSemanticAnnotation:
    evidence: list[GoldSemanticEvidenceSpan] = []
    for span in decision.evidence:
        element_order = element_order_by_id.get(span.element_id)
        if element_order is None:
            raise GoldSourceResolutionError(
                f"cannot compile record {record.record_id!r}: evidence element "
                f"{span.element_id!r} is absent from the canonical document"
            )
        evidence.append(
            GoldSemanticEvidenceSpan(
                element_order=element_order,
                start_char=span.start_char,
                end_char=span.end_char,
                quoted_text=span.quoted_text,
                text_view=span.text_view,
            )
        )
    return GoldSemanticAnnotation(
        target=target,
        type=decision.annotation_type,
        value=decision.value,
        ontology=decision.ontology,
        evidence=tuple(sorted(evidence, key=_evidence_sort_key)),
        metadata={},
    )


def _record_target_sort_key(record: SemanticWorkingRecord) -> tuple[object, ...]:
    return (
        record.target.target_kind.value,
        record.target.element_orders,
        record.record_id,
    )


def _scope_sort_key(scope: GoldSemanticEvaluationScope) -> tuple[object, ...]:
    return (scope.target.kind.value, scope.target.element_orders)


def _annotation_sort_key(annotation: GoldSemanticAnnotation) -> tuple[object, ...]:
    return (
        annotation.target.kind.value,
        annotation.target.element_orders,
        _ANNOTATION_TYPE_RANK[annotation.type],
    )


def _evidence_sort_key(span: GoldSemanticEvidenceSpan) -> tuple[object, ...]:
    return (
        span.element_order,
        span.text_view.value,
        span.start_char,
        span.end_char,
        span.quoted_text,
    )


_ANNOTATION_TYPE_RANK = {
    annotation_type: index
    for index, annotation_type in enumerate(SemanticAnnotationType)
}
