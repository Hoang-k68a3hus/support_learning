from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    ContentHash,
    Identifier,
    JsonObject,
    SchemaModel,
)
from source_understanding.schemas.document import (
    CanonicalDocument,
    SemanticAnnotation,
    SemanticAnnotationType,
    SemanticPayloadMode,
    SemanticTextView,
    semantic_extractive_value_key,
    semantic_payload_mode_for_type,
)
from source_understanding.schemas.element import ElementType
from source_understanding.semantics.provider import (
    EXTRACTIVE_SEMANTIC_ANNOTATION_TYPES,
    SemanticOntologyLabel,
    SemanticTargetKind,
)

from .metrics import LabelPRF, PRFScore, macro_f1, prf_counts, prf_from_sets
from .schemas import BenchmarkSplit


SEMANTIC_GOLD_SCHEMA_VERSION = "3"
SEMANTIC_GOLD_BENCHMARK_VERSION = "semantic-roles-v0.3"
SEMANTIC_ROLE_EVALUATOR_VERSION = "3"


class SemanticEvaluationError(ValueError):
    """Semantic gold or predictions cannot be compared without false alignment."""


class GoldSemanticElement(SchemaModel):
    order: int = Field(ge=0)
    raw_text: str | None = Field(default=None, max_length=32768)
    normalized_text: str | None = Field(default=None, max_length=32768)
    type: ElementType = ElementType.PARAGRAPH

    def text_for_view(self, text_view: SemanticTextView) -> str | None:
        if text_view == SemanticTextView.RAW_TEXT:
            return self.raw_text
        return self.normalized_text


class GoldSemanticTarget(SchemaModel):
    kind: SemanticTargetKind
    element_orders: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_orders(self) -> "GoldSemanticTarget":
        if len(self.element_orders) != len(set(self.element_orders)):
            raise ValueError("semantic target element_orders must be unique")
        if self.element_orders != tuple(sorted(self.element_orders)):
            raise ValueError("semantic target element_orders must follow source order")
        if self.kind == SemanticTargetKind.ELEMENT and len(self.element_orders) != 1:
            raise ValueError("ELEMENT semantic targets require exactly one element order")
        return self

    @property
    def key(self) -> str:
        orders = ",".join(str(order) for order in self.element_orders)
        return f"{self.kind.value}:{orders}"


class GoldSemanticEvaluationScope(SchemaModel):
    target: GoldSemanticTarget
    evaluated_types: tuple[SemanticAnnotationType, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evaluated_types(self) -> "GoldSemanticEvaluationScope":
        if len(self.evaluated_types) != len(set(self.evaluated_types)):
            raise ValueError("semantic evaluation scope types must be unique")
        canonical_types = tuple(
            annotation_type
            for annotation_type in SemanticAnnotationType
            if annotation_type in self.evaluated_types
        )
        if self.evaluated_types != canonical_types:
            raise ValueError(
                "semantic evaluation scope types must use canonical semantic order"
            )
        return self


class GoldSemanticEvidenceSpan(SchemaModel):
    element_order: int = Field(ge=0)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quoted_text: str = Field(min_length=1, max_length=32768)
    text_view: SemanticTextView = SemanticTextView.RAW_TEXT

    @model_validator(mode="after")
    def validate_span(self) -> "GoldSemanticEvidenceSpan":
        if self.end_char <= self.start_char:
            raise ValueError("gold semantic evidence range must be non-empty")
        if self.end_char - self.start_char != len(self.quoted_text):
            raise ValueError(
                "gold semantic evidence range length must equal quoted_text length"
            )
        return self


class GoldSemanticAnnotation(SchemaModel):
    target: GoldSemanticTarget
    type: SemanticAnnotationType
    value: str | None = Field(default=None, min_length=1, max_length=8192)
    ontology: SemanticOntologyLabel | None = None
    evidence: tuple[GoldSemanticEvidenceSpan, ...] = Field(default_factory=tuple)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_annotation(self) -> "GoldSemanticAnnotation":
        if self.type == SemanticAnnotationType.CUSTOM and self.ontology is None:
            raise ValueError("CUSTOM semantic gold requires a namespaced ontology label")
        if self.type in EXTRACTIVE_SEMANTIC_ANNOTATION_TYPES:
            if self.value is None or not self.evidence:
                raise ValueError(
                    f"extractive semantic gold {self.type.value} requires value and evidence"
                )
            value_key = semantic_extractive_value_key(self.value)
            evidence_value_keys = {
                semantic_extractive_value_key(item.quoted_text)
                for item in self.evidence
            }
            if value_key not in evidence_value_keys:
                raise ValueError(
                    f"extractive semantic gold {self.type.value} value must match an evidence quote"
                )
        evidence_keys = [
            (
                item.element_order,
                item.text_view,
                item.start_char,
                item.end_char,
                item.quoted_text,
            )
            for item in self.evidence
        ]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("gold semantic evidence spans must be unique")
        return self


class GoldSemanticDocument(SchemaModel):
    schema_version: str = SEMANTIC_GOLD_SCHEMA_VERSION
    benchmark_version: str = SEMANTIC_GOLD_BENCHMARK_VERSION
    document_id: Identifier
    content_hash: ContentHash
    element_snapshot_hash: ContentHash
    split: BenchmarkSplit
    language: str = Field(min_length=2, max_length=64)
    elements: tuple[GoldSemanticElement, ...] = Field(min_length=1)
    evaluation_scopes: tuple[GoldSemanticEvaluationScope, ...] = Field(min_length=1)
    annotations: tuple[GoldSemanticAnnotation, ...] = Field(default_factory=tuple)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_gold(self) -> "GoldSemanticDocument":
        if self.schema_version != SEMANTIC_GOLD_SCHEMA_VERSION:
            raise ValueError(f"unsupported semantic gold schema_version {self.schema_version!r}")
        if self.benchmark_version != SEMANTIC_GOLD_BENCHMARK_VERSION:
            raise ValueError(
                f"unsupported semantic benchmark_version {self.benchmark_version!r}"
            )
        orders = [element.order for element in self.elements]
        if len(orders) != len(set(orders)):
            raise ValueError("semantic gold elements must have unique order values")
        if orders != sorted(orders):
            raise ValueError("semantic gold elements must follow source order")
        expected_hash = semantic_element_snapshot_hash(self.elements)
        if self.element_snapshot_hash != expected_hash:
            raise ValueError(
                "semantic gold element_snapshot_hash does not match its elements: "
                f"{self.element_snapshot_hash!r} != {expected_hash!r}"
            )
        elements_by_order = {element.order: element for element in self.elements}
        scopes_by_target: dict[str, GoldSemanticEvaluationScope] = {}
        for scope in self.evaluation_scopes:
            missing = set(scope.target.element_orders) - set(elements_by_order)
            if missing:
                raise ValueError(
                    "semantic evaluation scope references unknown element orders: "
                    f"{sorted(missing)}"
                )
            if scope.target.key in scopes_by_target:
                raise ValueError(
                    f"duplicate semantic evaluation scope {scope.target.key!r}"
                )
            scopes_by_target[scope.target.key] = scope

        signatures: set[tuple[object, ...]] = set()
        for annotation in self.annotations:
            missing = set(annotation.target.element_orders) - set(elements_by_order)
            if missing:
                raise ValueError(
                    f"semantic gold target references unknown element orders: {sorted(missing)}"
                )
            scope = scopes_by_target.get(annotation.target.key)
            if scope is None:
                raise ValueError(
                    f"semantic gold annotation target {annotation.target.key!r} "
                    "has no evaluation scope"
                )
            if annotation.type not in scope.evaluated_types:
                raise ValueError(
                    f"gold annotation type {annotation.type.value} is not evaluated "
                    f"for target {annotation.target.key!r}"
                )
            signature = (
                annotation.target.key,
                annotation.type.value,
                _normalize_value(annotation.value) if annotation.value is not None else None,
                tuple(
                    (item.element_order, item.start_char, item.end_char)
                    for item in annotation.evidence
                ),
            )
            if signature in signatures:
                raise ValueError(f"duplicate semantic gold annotation {signature}")
            signatures.add(signature)
            for evidence in annotation.evidence:
                element = elements_by_order.get(evidence.element_order)
                if element is None:
                    raise ValueError(
                        "semantic gold evidence references unknown element order "
                        f"{evidence.element_order}"
                    )
                if evidence.element_order not in annotation.target.element_orders:
                    raise ValueError(
                        "semantic gold evidence must remain inside its target element orders"
                    )
                source_text = element.text_for_view(evidence.text_view)
                if source_text is None:
                    raise ValueError(
                        "gold semantic evidence text_view is unavailable on its element"
                    )
                if evidence.end_char > len(source_text):
                    raise ValueError("semantic gold evidence range exceeds element text")
                if source_text[evidence.start_char : evidence.end_char] != evidence.quoted_text:
                    raise ValueError("semantic gold evidence quote does not match element text")
        return self

    @property
    def evaluated_types(self) -> tuple[SemanticAnnotationType, ...]:
        scoped_types = {
            annotation_type
            for scope in self.evaluation_scopes
            for annotation_type in scope.evaluated_types
        }
        return tuple(
            annotation_type
            for annotation_type in SemanticAnnotationType
            if annotation_type in scoped_types
        )

    @property
    def evaluated_target_kinds(self) -> tuple[SemanticTargetKind, ...]:
        scoped_kinds = {scope.target.kind for scope in self.evaluation_scopes}
        return tuple(
            target_kind
            for target_kind in SemanticTargetKind
            if target_kind in scoped_kinds
        )


class SemanticGoldDataset(SchemaModel):
    name: str = Field(min_length=1, max_length=256)
    schema_version: str = SEMANTIC_GOLD_SCHEMA_VERSION
    benchmark_version: str = SEMANTIC_GOLD_BENCHMARK_VERSION
    cases: tuple[GoldSemanticDocument, ...] = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cases(self) -> "SemanticGoldDataset":
        if self.schema_version != SEMANTIC_GOLD_SCHEMA_VERSION:
            raise ValueError("semantic dataset schema_version is unsupported")
        if self.benchmark_version != SEMANTIC_GOLD_BENCHMARK_VERSION:
            raise ValueError("semantic dataset benchmark_version is unsupported")
        ids = [case.document_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("semantic gold dataset document_ids must be unique")
        return self


class SemanticDifferenceKind(str):
    MISSING = "MISSING"
    EXTRA = "EXTRA"


class SemanticRoleDifference(SchemaModel):
    kind: str = Field(pattern=r"^(MISSING|EXTRA)$")
    target: str
    type: SemanticAnnotationType


class SemanticGroundingScore(SchemaModel):
    predicted_count: int = Field(ge=0)
    evidence_attached_count: int = Field(ge=0)
    evidence_attached_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_aligned_count: int = Field(ge=0)
    evidence_alignment_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    semantic_support_count: int = Field(ge=0)
    semantic_support_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    # Backward-compatible aliases.  They now mean semantic support, not merely
    # the existence of an attached span.
    supported_count: int = Field(ge=0)
    unsupported_count: int = Field(ge=0)
    supported_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    unsupported_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_grounding_counts(self) -> "SemanticGroundingScore":
        for name, count in (
            ("evidence_attached_count", self.evidence_attached_count),
            ("evidence_aligned_count", self.evidence_aligned_count),
            ("semantic_support_count", self.semantic_support_count),
            ("supported_count", self.supported_count),
        ):
            if count > self.predicted_count:
                raise ValueError(f"{name} cannot exceed predicted_count")
        if self.supported_count != self.semantic_support_count:
            raise ValueError("supported_count must equal semantic_support_count")
        return self


class SemanticCalibrationBin(SchemaModel):
    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    count: int = Field(ge=0)
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


class SemanticCalibrationMetrics(SchemaModel):
    count: int = Field(ge=0)
    brier_score: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_calibration_error: float | None = Field(default=None, ge=0.0, le=1.0)
    bins: tuple[SemanticCalibrationBin, ...]


class SemanticCapabilityEvaluation(SchemaModel):
    language: str = Field(min_length=2, max_length=64)
    annotation_type: SemanticAnnotationType
    payload_mode: SemanticPayloadMode | None = None
    target_kind: SemanticTargetKind
    provider_name: str = Field(default="SYSTEM_FUSED", min_length=1, max_length=128)
    provider_version: str | None = Field(default=None, max_length=128)
    capability_name: str | None = Field(default=None, max_length=128)
    role: PRFScore
    value_exact: PRFScore
    value_normalized: PRFScore
    typed_span_exact: PRFScore
    typed_span_overlap: PRFScore
    grounding: SemanticGroundingScore
    calibration: SemanticCalibrationMetrics

    @model_validator(mode="before")
    @classmethod
    def default_payload_mode(cls, value: object) -> object:
        if not isinstance(value, dict) or value.get("payload_mode") is not None:
            return value
        payload = dict(value)
        payload["payload_mode"] = semantic_payload_mode_for_type(
            SemanticAnnotationType(payload["annotation_type"])
        )
        return payload

    @property
    def key(self) -> str:
        return (
            f"{self.provider_name}|{self.capability_name or 'SYSTEM_FUSED'}|"
            f"{self.language}|{self.annotation_type.value}|{self.target_kind.value}"
        )


class SemanticEvaluationReport(SchemaModel):
    version: str = SEMANTIC_ROLE_EVALUATOR_VERSION
    document_id: Identifier
    content_hash: ContentHash
    split: BenchmarkSplit
    language: str = Field(min_length=2, max_length=64)
    gold_annotation_count: int = Field(ge=0)
    predicted_annotation_count: int = Field(ge=0)
    unscorable_prediction_count: int = Field(ge=0)
    overall: PRFScore
    value_exact: PRFScore
    value_normalized: PRFScore
    span_exact: PRFScore
    span_overlap: PRFScore
    typed_span_exact: PRFScore
    typed_span_overlap: PRFScore
    ontology: PRFScore
    grounding: SemanticGroundingScore
    calibration: SemanticCalibrationMetrics
    by_type: tuple[LabelPRF, ...]
    by_target: tuple[LabelPRF, ...]
    by_target_kind: tuple[LabelPRF, ...]
    capability_slices: tuple[SemanticCapabilityEvaluation, ...]
    macro_type_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_target_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_target_kind_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    differences: tuple[SemanticRoleDifference, ...] = Field(default_factory=tuple)


class SemanticBenchmarkEvaluationReport(SchemaModel):
    version: str = SEMANTIC_ROLE_EVALUATOR_VERSION
    dataset_name: str = Field(min_length=1, max_length=256)
    benchmark_version: str = SEMANTIC_GOLD_BENCHMARK_VERSION
    split: BenchmarkSplit
    dataset_hash: ContentHash
    case_reports: tuple[SemanticEvaluationReport, ...] = Field(min_length=1)
    pooled: PRFScore
    value_exact: PRFScore
    value_normalized: PRFScore
    span_exact: PRFScore
    span_overlap: PRFScore
    typed_span_exact: PRFScore
    typed_span_overlap: PRFScore
    ontology: PRFScore
    grounding: SemanticGroundingScore
    calibration: SemanticCalibrationMetrics
    by_type: tuple[LabelPRF, ...]
    by_target: tuple[LabelPRF, ...]
    by_target_kind: tuple[LabelPRF, ...]
    by_language: tuple[LabelPRF, ...]
    capability_slices: tuple[SemanticCapabilityEvaluation, ...]
    macro_type_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_target_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_target_kind_f1: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_case_reports(self) -> "SemanticBenchmarkEvaluationReport":
        document_ids = [report.document_id for report in self.case_reports]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("semantic benchmark case report document_ids must be unique")
        if any(report.split != self.split for report in self.case_reports):
            raise ValueError("semantic benchmark case reports must match the declared split")
        return self


class SemanticRoleEvaluator:
    version = SEMANTIC_ROLE_EVALUATOR_VERSION

    def __init__(self, *, calibration_bins: int = 10) -> None:
        if calibration_bins < 2 or calibration_bins > 100:
            raise ValueError("calibration_bins must be in [2, 100]")
        self._calibration_bins = calibration_bins

    def evaluate(
        self,
        gold: GoldSemanticDocument,
        predicted: CanonicalDocument,
    ) -> SemanticEvaluationReport:
        self._validate_source(gold, predicted)
        element_orders = {element.id: element.order for element in predicted.elements}
        logical_orders = {
            unit.id: tuple(element_orders[element_id] for element_id in unit.element_ids)
            for unit in predicted.logical_units
        }
        evaluated_types = set(gold.evaluated_types)
        scopes_by_target = {
            scope.target.key: set(scope.evaluated_types)
            for scope in gold.evaluation_scopes
        }

        gold_records = tuple(gold.annotations)
        predicted_records: list[tuple[GoldSemanticTarget, SemanticAnnotation]] = []
        unscorable = 0
        for annotation in predicted.semantic_annotations:
            if annotation.type not in evaluated_types:
                continue
            target = self._predicted_target(annotation.target_id, element_orders, logical_orders)
            if target is None:
                unscorable += 1
                continue
            scoped_types = scopes_by_target.get(target.key)
            if scoped_types is None or annotation.type not in scoped_types:
                continue
            predicted_records.append((target, annotation))

        gold_roles = {
            (annotation.target.key, annotation.type.value) for annotation in gold_records
        }
        predicted_roles = {
            (target.key, annotation.type.value)
            for target, annotation in predicted_records
        }
        overall = prf_from_sets(gold_roles, predicted_roles)

        value_exact = prf_from_sets(
            self._gold_value_set(gold_records, normalized=False),
            self._predicted_value_set(predicted_records, normalized=False),
        )
        value_normalized = prf_from_sets(
            self._gold_value_set(gold_records, normalized=True),
            self._predicted_value_set(predicted_records, normalized=True),
        )
        gold_spans = self._gold_spans(gold_records, typed=False)
        predicted_spans = self._predicted_spans(
            predicted_records, element_orders, typed=False
        )
        gold_typed_spans = self._gold_spans(gold_records, typed=True)
        predicted_typed_spans = self._predicted_spans(
            predicted_records, element_orders, typed=True
        )
        span_exact = prf_from_sets(gold_spans, predicted_spans)
        typed_span_exact = prf_from_sets(gold_typed_spans, predicted_typed_spans)
        span_overlap = self._overlap_prf(gold_spans, predicted_spans, typed=False)
        typed_span_overlap = self._overlap_prf(
            gold_typed_spans, predicted_typed_spans, typed=True
        )
        ontology = prf_from_sets(
            self._gold_ontology_set(gold_records),
            self._predicted_ontology_set(predicted_records),
        )
        grounding = _grounding_score(gold_records, predicted_records, element_orders)
        calibration = self._calibration(gold_records, predicted_records)

        by_type = tuple(
            LabelPRF(
                label=annotation_type.value,
                score=prf_from_sets(
                    {item for item in gold_roles if item[1] == annotation_type.value},
                    {item for item in predicted_roles if item[1] == annotation_type.value},
                ),
            )
            for annotation_type in gold.evaluated_types
        )
        target_keys = sorted(scopes_by_target)
        by_target = tuple(
            LabelPRF(
                label=target,
                score=prf_from_sets(
                    {item[1] for item in gold_roles if item[0] == target},
                    {item[1] for item in predicted_roles if item[0] == target},
                ),
            )
            for target in target_keys
        )
        by_target_kind = tuple(
            LabelPRF(
                label=target_kind.value,
                score=prf_from_sets(
                    {item for item in gold_roles if item[0].startswith(target_kind.value + ":")},
                    {item for item in predicted_roles if item[0].startswith(target_kind.value + ":")},
                ),
            )
            for target_kind in gold.evaluated_target_kinds
        )
        differences = tuple(
            [
                SemanticRoleDifference(
                    kind=SemanticDifferenceKind.MISSING,
                    target=target,
                    type=SemanticAnnotationType(annotation_type),
                )
                for target, annotation_type in sorted(gold_roles - predicted_roles)
            ]
            + [
                SemanticRoleDifference(
                    kind=SemanticDifferenceKind.EXTRA,
                    target=target,
                    type=SemanticAnnotationType(annotation_type),
                )
                for target, annotation_type in sorted(predicted_roles - gold_roles)
            ]
        )
        capability_slices = self._capability_slices(
            gold,
            gold_records,
            tuple(predicted_records),
            element_orders,
        )
        return SemanticEvaluationReport(
            document_id=gold.document_id,
            content_hash=gold.content_hash,
            split=gold.split,
            language=gold.language,
            gold_annotation_count=len(gold_records),
            predicted_annotation_count=len(predicted_records),
            unscorable_prediction_count=unscorable,
            overall=overall,
            value_exact=value_exact,
            value_normalized=value_normalized,
            span_exact=span_exact,
            span_overlap=span_overlap,
            typed_span_exact=typed_span_exact,
            typed_span_overlap=typed_span_overlap,
            ontology=ontology,
            grounding=grounding,
            calibration=calibration,
            by_type=by_type,
            by_target=by_target,
            by_target_kind=by_target_kind,
            capability_slices=capability_slices,
            macro_type_f1=macro_f1(item.score for item in by_type),
            macro_target_f1=macro_f1(item.score for item in by_target),
            macro_target_kind_f1=macro_f1(item.score for item in by_target_kind),
            differences=differences,
        )

    def _capability_slices(
        self,
        gold: GoldSemanticDocument,
        gold_records: tuple[GoldSemanticAnnotation, ...],
        predicted_records: tuple[tuple[GoldSemanticTarget, SemanticAnnotation], ...],
        element_orders: dict[str, int],
    ) -> tuple[SemanticCapabilityEvaluation, ...]:
        output: list[SemanticCapabilityEvaluation] = []
        evaluated_pairs = tuple(
            (annotation_type, target_kind)
            for annotation_type in gold.evaluated_types
            for target_kind in gold.evaluated_target_kinds
            if any(
                scope.target.kind == target_kind
                and annotation_type in scope.evaluated_types
                for scope in gold.evaluation_scopes
            )
        )
        for annotation_type, target_kind in evaluated_pairs:
                selected_gold = tuple(
                    item
                    for item in gold_records
                    if item.type == annotation_type and item.target.kind == target_kind
                )
                candidates = tuple(
                    item
                    for item in predicted_records
                    if item[1].type == annotation_type and item[0].kind == target_kind
                )
                groups: dict[
                    tuple[str, str | None, str | None, SemanticPayloadMode],
                    list[tuple[GoldSemanticTarget, SemanticAnnotation]],
                ] = defaultdict(list)
                for target, annotation in candidates:
                    groups[
                        (
                            str(annotation.metadata.get("semantic_provider", "SYSTEM_FUSED")),
                            annotation.metadata.get("semantic_provider_version")
                            if isinstance(
                                annotation.metadata.get("semantic_provider_version"), str
                            )
                            else None,
                            annotation.metadata.get("semantic_capability")
                            if isinstance(annotation.metadata.get("semantic_capability"), str)
                            else None,
                            annotation.payload_mode or semantic_payload_mode_for_type(annotation.type),
                        )
                    ].append((target, annotation))
                if not groups:
                    groups[("SYSTEM_FUSED", None, None, semantic_payload_mode_for_type(annotation_type))] = []
                for (provider_name, provider_version, capability_name, payload_mode), selected_predicted_list in groups.items():
                    selected_predicted = tuple(selected_predicted_list)
                    gold_roles = {
                        (item.target.key, item.type.value) for item in selected_gold
                    }
                    predicted_roles = {
                        (target.key, item.type.value) for target, item in selected_predicted
                    }
                    gold_typed_spans = self._gold_spans(selected_gold, typed=True)
                    predicted_typed_spans = self._predicted_spans(
                        selected_predicted, element_orders, typed=True
                    )
                    output.append(
                        SemanticCapabilityEvaluation(
                            language=gold.language,
                            annotation_type=annotation_type,
                            payload_mode=payload_mode,
                            target_kind=target_kind,
                            provider_name=provider_name,
                            provider_version=provider_version,
                            capability_name=capability_name,
                            role=prf_from_sets(gold_roles, predicted_roles),
                            value_exact=prf_from_sets(
                                self._gold_value_set(selected_gold, normalized=False),
                                self._predicted_value_set(selected_predicted, normalized=False),
                            ),
                            value_normalized=prf_from_sets(
                                self._gold_value_set(selected_gold, normalized=True),
                                self._predicted_value_set(selected_predicted, normalized=True),
                            ),
                            typed_span_exact=prf_from_sets(
                                gold_typed_spans, predicted_typed_spans
                            ),
                            typed_span_overlap=self._overlap_prf(
                                gold_typed_spans, predicted_typed_spans, typed=True
                            ),
                            grounding=_grounding_score(
                                selected_gold,
                                selected_predicted,
                                element_orders,
                            ),
                            calibration=self._calibration(
                                selected_gold,
                                list(selected_predicted),
                            ),
                        )
                    )
        return tuple(output)

    def _calibration(
        self,
        gold_records: tuple[GoldSemanticAnnotation, ...],
        predicted_records: list[tuple[GoldSemanticTarget, SemanticAnnotation]],
    ) -> SemanticCalibrationMetrics:
        values: list[tuple[float, int]] = []
        for target, annotation in sorted(
            predicted_records,
            key=lambda item: (-item[1].confidence, item[0].key, item[1].type.value),
        ):
            # Calibration is task-aware: an extractor is only correct when
            # target, type, value and typed span all agree. Generative values
            # have no calibrated correctness contract yet and are excluded.
            if annotation.payload_mode == SemanticPayloadMode.GENERATIVE:
                continue
            outcome = int(_semantic_prediction_correct(gold_records, target, annotation))
            values.append((annotation.confidence, outcome))
        return _calibration_metrics(values, bin_count=self._calibration_bins)

    @staticmethod
    def _gold_value_set(
        records: tuple[GoldSemanticAnnotation, ...],
        *,
        normalized: bool,
    ) -> set[tuple[str, str, str]]:
        return {
            (
                item.target.key,
                item.type.value,
                _normalize_value(item.value) if normalized else item.value,
            )
            for item in records
            if item.value is not None
        }

    @staticmethod
    def _predicted_value_set(
        records: tuple[tuple[GoldSemanticTarget, SemanticAnnotation], ...]
        | list[tuple[GoldSemanticTarget, SemanticAnnotation]],
        *,
        normalized: bool,
    ) -> set[tuple[str, str, str]]:
        return {
            (
                target.key,
                item.type.value,
                _normalize_value(item.value) if normalized else item.value,
            )
            for target, item in records
        }

    @staticmethod
    def _gold_spans(
        records: tuple[GoldSemanticAnnotation, ...],
        *,
        typed: bool,
    ) -> set[tuple[object, ...]]:
        return {
            (
                item.type.value,
                evidence.element_order,
                evidence.text_view.value,
                evidence.start_char,
                evidence.end_char,
            )
            if typed
            else (
                evidence.element_order,
                evidence.text_view.value,
                evidence.start_char,
                evidence.end_char,
            )
            for item in records
            for evidence in item.evidence
        }

    @staticmethod
    def _predicted_spans(
        records: tuple[tuple[GoldSemanticTarget, SemanticAnnotation], ...]
        | list[tuple[GoldSemanticTarget, SemanticAnnotation]],
        element_orders: dict[str, int],
        *,
        typed: bool,
    ) -> set[tuple[object, ...]]:
        return {
            (
                item.type.value,
                element_orders[evidence.element_id],
                evidence.text_view.value,
                evidence.start_char,
                evidence.end_char,
            )
            if typed
            else (
                element_orders[evidence.element_id],
                evidence.text_view.value,
                evidence.start_char,
                evidence.end_char,
            )
            for _, item in records
            for evidence in item.evidence
        }

    @staticmethod
    def _overlap_prf(
        gold: set[tuple[object, ...]],
        predicted: set[tuple[object, ...]],
        *,
        typed: bool,
    ) -> PRFScore:
        remaining = set(predicted)
        matched = 0
        for gold_span in sorted(gold, key=str):
            best: tuple[object, ...] | None = None
            best_overlap = 0
            for predicted_span in remaining:
                if typed:
                    if (
                        gold_span[0] != predicted_span[0]
                        or gold_span[1] != predicted_span[1]
                        or gold_span[2] != predicted_span[2]
                    ):
                        continue
                    gold_start, gold_end = int(gold_span[3]), int(gold_span[4])
                    predicted_start, predicted_end = (
                        int(predicted_span[3]),
                        int(predicted_span[4]),
                    )
                else:
                    if (
                        gold_span[0] != predicted_span[0]
                        or gold_span[1] != predicted_span[1]
                    ):
                        continue
                    gold_start, gold_end = int(gold_span[2]), int(gold_span[3])
                    predicted_start, predicted_end = (
                        int(predicted_span[2]),
                        int(predicted_span[3]),
                    )
                overlap = min(gold_end, predicted_end) - max(gold_start, predicted_start)
                if overlap > best_overlap:
                    best = predicted_span
                    best_overlap = overlap
            if best is not None:
                remaining.remove(best)
                matched += 1
        return prf_counts(matched, len(predicted) - matched, len(gold) - matched)

    @staticmethod
    def _gold_ontology_set(
        records: tuple[GoldSemanticAnnotation, ...],
    ) -> set[tuple[str, str, str]]:
        return {
            (item.target.key, item.type.value, item.ontology.key)
            for item in records
            if item.ontology is not None
        }

    @staticmethod
    def _predicted_ontology_set(
        records: list[tuple[GoldSemanticTarget, SemanticAnnotation]],
    ) -> set[tuple[str, str, str]]:
        output: set[tuple[str, str, str]] = set()
        for target, item in records:
            namespace = item.metadata.get("semantic_ontology_namespace")
            label = item.metadata.get("semantic_ontology_label")
            if isinstance(namespace, str) and isinstance(label, str):
                output.add((target.key, item.type.value, f"{namespace}:{label}"))
        return output

    @staticmethod
    def _validate_source(
        gold: GoldSemanticDocument,
        predicted: CanonicalDocument,
    ) -> None:
        if predicted.document_id != gold.document_id:
            raise SemanticEvaluationError(
                f"predicted document_id {predicted.document_id!r} does not match gold "
                f"{gold.document_id!r}"
            )
        if predicted.content_hash != gold.content_hash:
            raise SemanticEvaluationError(
                "predicted content_hash does not match semantic gold source revision"
            )
        predicted_by_order = {element.order: element for element in predicted.elements}
        gold_orders = {element.order for element in gold.elements}
        if set(predicted_by_order) != gold_orders:
            raise SemanticEvaluationError(
                "predicted element orders do not exactly match semantic gold source"
            )
        for expected in gold.elements:
            actual = predicted_by_order[expected.order]
            view_mismatch = (
                actual.raw_text != expected.raw_text
                or actual.normalized_text != expected.normalized_text
            )
            if view_mismatch or actual.type != expected.type:
                raise SemanticEvaluationError(
                    f"predicted element at order {expected.order} disagrees with semantic gold"
                )

    @staticmethod
    def _predicted_target(
        target_id: str,
        element_orders: dict[str, int],
        logical_orders: dict[str, tuple[int, ...]],
    ) -> GoldSemanticTarget | None:
        if target_id in element_orders:
            return GoldSemanticTarget(
                kind=SemanticTargetKind.ELEMENT,
                element_orders=(element_orders[target_id],),
            )
        if target_id in logical_orders:
            return GoldSemanticTarget(
                kind=SemanticTargetKind.LOGICAL_UNIT,
                element_orders=logical_orders[target_id],
            )
        return None


def _normalize_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _grounding_score(
    gold_records: tuple[GoldSemanticAnnotation, ...],
    predicted_records: tuple[tuple[GoldSemanticTarget, SemanticAnnotation], ...]
    | list[tuple[GoldSemanticTarget, SemanticAnnotation]],
    element_orders: dict[str, int],
) -> SemanticGroundingScore:
    predicted_count = len(predicted_records)
    attached_count = sum(bool(annotation.evidence) for _, annotation in predicted_records)
    aligned_count = sum(
        _evidence_aligned(gold_records, target, annotation, element_orders)
        for target, annotation in predicted_records
    )
    supported_count = sum(
        _semantic_prediction_correct(gold_records, target, annotation)
        for target, annotation in predicted_records
    )
    unsupported_count = predicted_count - supported_count
    return SemanticGroundingScore(
        predicted_count=predicted_count,
        evidence_attached_count=attached_count,
        evidence_attached_ratio=(
            attached_count / predicted_count if predicted_count else None
        ),
        evidence_aligned_count=aligned_count,
        evidence_alignment_ratio=(
            aligned_count / predicted_count if predicted_count else None
        ),
        semantic_support_count=supported_count,
        semantic_support_ratio=(
            supported_count / predicted_count if predicted_count else None
        ),
        supported_count=supported_count,
        unsupported_count=unsupported_count,
        supported_ratio=(supported_count / predicted_count if predicted_count else None),
        unsupported_rate=(unsupported_count / predicted_count if predicted_count else None),
    )


def _evidence_aligned(
    gold_records: tuple[GoldSemanticAnnotation, ...],
    target: GoldSemanticTarget,
    annotation: SemanticAnnotation,
    element_orders: dict[str, int],
) -> bool:
    gold_spans = {
        (span.element_order, span.start_char, span.end_char, span.text_view)
        for item in gold_records
        if item.target.key == target.key and item.type == annotation.type
        for span in item.evidence
    }
    return any(
        (element_orders.get(span.element_id), span.start_char, span.end_char, span.text_view)
        in gold_spans
        for span in annotation.evidence
    )


def _semantic_prediction_correct(
    gold_records: tuple[GoldSemanticAnnotation, ...],
    target: GoldSemanticTarget,
    annotation: SemanticAnnotation,
) -> bool:
    matches = tuple(
        item
        for item in gold_records
        if item.target.key == target.key and item.type == annotation.type
    )
    if not matches:
        return False
    if annotation.payload_mode == SemanticPayloadMode.LABEL_ONLY:
        return True
    if annotation.payload_mode == SemanticPayloadMode.GENERATIVE:
        return False
    predicted_value = _normalize_value(annotation.value)
    predicted_spans = {
        (span.start_char, span.end_char, span.text_view)
        for span in annotation.evidence
    }
    for item in matches:
        if item.value is None or _normalize_value(item.value) != predicted_value:
            continue
        gold_spans = {
            (span.start_char, span.end_char, span.text_view)
            for span in item.evidence
        }
        if predicted_spans & gold_spans:
            if item.ontology is None:
                return True
            namespace = annotation.metadata.get("semantic_ontology_namespace")
            label = annotation.metadata.get("semantic_ontology_label")
            if f"{namespace}:{label}" == item.ontology.key:
                return True
    return False


def _calibration_metrics(
    values: list[tuple[float, int]],
    *,
    bin_count: int,
) -> SemanticCalibrationMetrics:
    bins: list[SemanticCalibrationBin] = []
    weighted_error = 0.0
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        selected = [
            (confidence, outcome)
            for confidence, outcome in values
            if confidence >= lower
            and (confidence < upper or (index == bin_count - 1 and confidence <= upper))
        ]
        mean_confidence = (
            sum(confidence for confidence, _ in selected) / len(selected)
            if selected
            else None
        )
        accuracy = (
            sum(outcome for _, outcome in selected) / len(selected)
            if selected
            else None
        )
        if selected and mean_confidence is not None and accuracy is not None:
            weighted_error += len(selected) * abs(mean_confidence - accuracy)
        bins.append(
            SemanticCalibrationBin(
                lower=lower,
                upper=upper,
                count=len(selected),
                mean_confidence=mean_confidence,
                accuracy=accuracy,
            )
        )
    brier = (
        sum((confidence - outcome) ** 2 for confidence, outcome in values) / len(values)
        if values
        else None
    )
    return SemanticCalibrationMetrics(
        count=len(values),
        brier_score=brier,
        expected_calibration_error=weighted_error / len(values) if values else None,
        bins=tuple(bins),
    )


def semantic_element_snapshot_hash(
    elements: tuple[GoldSemanticElement, ...],
) -> str:
    payload = [element.model_dump(mode="json") for element in elements]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def semantic_gold_dataset_hash(
    dataset: SemanticGoldDataset,
    *,
    split: BenchmarkSplit,
) -> ContentHash:
    selected_cases = tuple(case for case in dataset.cases if case.split == split)
    if not selected_cases:
        raise SemanticEvaluationError(
            f"semantic gold dataset has no cases for split {split.value!r}"
        )
    payload = {
        "name": dataset.name,
        "schema_version": dataset.schema_version,
        "benchmark_version": dataset.benchmark_version,
        "split": split.value,
        "cases": [case.model_dump(mode="json") for case in selected_cases],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def semantic_evaluation_report_hash(report: SemanticEvaluationReport) -> str:
    encoded = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def aggregate_semantic_reports(
    dataset: SemanticGoldDataset,
    reports: tuple[SemanticEvaluationReport, ...],
    *,
    split: BenchmarkSplit,
) -> SemanticBenchmarkEvaluationReport:
    report_by_id = {report.document_id: report for report in reports}
    selected_cases = tuple(case for case in dataset.cases if case.split == split)
    if not selected_cases:
        raise SemanticEvaluationError(
            f"semantic gold dataset has no cases for split {split.value!r}"
        )
    if any(report.split != split for report in reports):
        raise SemanticEvaluationError(
            "semantic benchmark reports cannot mix cases from another split"
        )
    expected_ids = [case.document_id for case in selected_cases]
    if len(report_by_id) != len(reports) or set(report_by_id) != set(expected_ids):
        raise SemanticEvaluationError(
            "semantic benchmark reports must match dataset cases exactly"
        )
    ordered_reports = tuple(report_by_id[document_id] for document_id in expected_ids)

    pooled = _pool_prf(report.overall for report in ordered_reports)
    value_exact = _pool_prf(report.value_exact for report in ordered_reports)
    value_normalized = _pool_prf(report.value_normalized for report in ordered_reports)
    span_exact = _pool_prf(report.span_exact for report in ordered_reports)
    span_overlap = _pool_prf(report.span_overlap for report in ordered_reports)
    typed_span_exact = _pool_prf(report.typed_span_exact for report in ordered_reports)
    typed_span_overlap = _pool_prf(
        report.typed_span_overlap for report in ordered_reports
    )
    ontology = _pool_prf(report.ontology for report in ordered_reports)
    grounding = _pool_grounding_scores(tuple(report.grounding for report in ordered_reports))
    calibration = _pool_calibration_metrics(
        tuple(report.calibration for report in ordered_reports)
    )

    type_labels = tuple(
        dict.fromkeys(
            annotation_type.value
            for case in selected_cases
            for annotation_type in case.evaluated_types
        )
    )
    type_scores = tuple(
        LabelPRF(
            label=label,
            score=_pool_prf(
                item.score
                for report in ordered_reports
                for item in report.by_type
                if item.label == label
            ),
        )
        for label in type_labels
    )
    target_scores = tuple(
        LabelPRF(label=f"{report.document_id}/{item.label}", score=item.score)
        for report in ordered_reports
        for item in report.by_target
    )
    target_kind_labels = tuple(
        dict.fromkeys(
            target_kind.value
            for case in selected_cases
            for target_kind in case.evaluated_target_kinds
        )
    )
    target_kind_scores = tuple(
        LabelPRF(
            label=label,
            score=_pool_prf(
                item.score
                for report in ordered_reports
                for item in report.by_target_kind
                if item.label == label
            ),
        )
        for label in target_kind_labels
    )
    language_scores = tuple(
        LabelPRF(
            label=language,
            score=_pool_prf(
                report.overall for report in ordered_reports if report.language == language
            ),
        )
        for language in dict.fromkeys(report.language for report in ordered_reports)
    )
    capability_slices = _aggregate_capability_slices(ordered_reports)
    return SemanticBenchmarkEvaluationReport(
        dataset_name=dataset.name,
        benchmark_version=dataset.benchmark_version,
        split=split,
        dataset_hash=semantic_gold_dataset_hash(dataset, split=split),
        case_reports=ordered_reports,
        pooled=pooled,
        value_exact=value_exact,
        value_normalized=value_normalized,
        span_exact=span_exact,
        span_overlap=span_overlap,
        typed_span_exact=typed_span_exact,
        typed_span_overlap=typed_span_overlap,
        ontology=ontology,
        grounding=grounding,
        calibration=calibration,
        by_type=type_scores,
        by_target=target_scores,
        by_target_kind=target_kind_scores,
        by_language=language_scores,
        capability_slices=capability_slices,
        macro_type_f1=macro_f1(item.score for item in type_scores),
        macro_target_f1=macro_f1(item.score for item in target_scores),
        macro_target_kind_f1=macro_f1(item.score for item in target_kind_scores),
    )


def _aggregate_capability_slices(
    reports: tuple[SemanticEvaluationReport, ...],
) -> tuple[SemanticCapabilityEvaluation, ...]:
    grouped: dict[str, list[SemanticCapabilityEvaluation]] = defaultdict(list)
    for report in reports:
        for item in report.capability_slices:
            grouped[item.key].append(item)
    output: list[SemanticCapabilityEvaluation] = []
    for key in sorted(grouped):
        items = grouped[key]
        first = items[0]
        output.append(
            SemanticCapabilityEvaluation(
                language=first.language,
                annotation_type=first.annotation_type,
                payload_mode=first.payload_mode,
                target_kind=first.target_kind,
                provider_name=first.provider_name,
                provider_version=first.provider_version,
                capability_name=first.capability_name,
                role=_pool_prf(item.role for item in items),
                value_exact=_pool_prf(item.value_exact for item in items),
                value_normalized=_pool_prf(item.value_normalized for item in items),
                typed_span_exact=_pool_prf(item.typed_span_exact for item in items),
                typed_span_overlap=_pool_prf(item.typed_span_overlap for item in items),
                grounding=_pool_grounding_scores(
                    tuple(item.grounding for item in items)
                ),
                calibration=_pool_calibration_metrics(
                    tuple(item.calibration for item in items)
                ),
            )
        )
    return tuple(output)


def _pool_prf(scores: object) -> PRFScore:
    values = tuple(scores)  # type: ignore[arg-type]
    return prf_counts(
        sum(score.true_positive for score in values),
        sum(score.false_positive for score in values),
        sum(score.false_negative for score in values),
    )


def _pool_grounding_scores(
    scores: tuple[SemanticGroundingScore, ...],
) -> SemanticGroundingScore:
    predicted = sum(item.predicted_count for item in scores)
    attached = sum(item.evidence_attached_count for item in scores)
    aligned = sum(item.evidence_aligned_count for item in scores)
    supported = sum(item.semantic_support_count for item in scores)
    return SemanticGroundingScore(
        predicted_count=predicted,
        evidence_attached_count=attached,
        evidence_attached_ratio=attached / predicted if predicted else None,
        evidence_aligned_count=aligned,
        evidence_alignment_ratio=aligned / predicted if predicted else None,
        semantic_support_count=supported,
        semantic_support_ratio=supported / predicted if predicted else None,
        supported_count=supported,
        unsupported_count=predicted - supported,
        supported_ratio=supported / predicted if predicted else None,
        unsupported_rate=(predicted - supported) / predicted if predicted else None,
    )


def _pool_calibration_bins(
    reports: tuple[SemanticEvaluationReport, ...],
) -> tuple[SemanticCalibrationBin, ...]:
    return _pool_calibration_metrics(
        tuple(report.calibration for report in reports)
    ).bins


def _pool_calibration_metrics(
    metrics: tuple[SemanticCalibrationMetrics, ...],
) -> SemanticCalibrationMetrics:
    if not metrics:
        return SemanticCalibrationMetrics(count=0, bins=())
    bin_count = len(metrics[0].bins)
    if any(len(item.bins) != bin_count for item in metrics):
        raise SemanticEvaluationError("semantic calibration bin layouts do not match")
    count = sum(item.count for item in metrics)
    pooled_bins = _pool_calibration_metric_bins(metrics)
    pooled_ece = (
        sum(
            item.count
            * abs((item.mean_confidence or 0.0) - (item.accuracy or 0.0))
            for item in pooled_bins
            if item.count
            and item.mean_confidence is not None
            and item.accuracy is not None
        )
        / count
        if count
        else None
    )
    return SemanticCalibrationMetrics(
        count=count,
        brier_score=(
            sum((item.brier_score or 0.0) * item.count for item in metrics) / count
            if count
            else None
        ),
        expected_calibration_error=(
            pooled_ece
        ),
        bins=pooled_bins,
    )


def _pool_calibration_metric_bins(
    metrics: tuple[SemanticCalibrationMetrics, ...],
) -> tuple[SemanticCalibrationBin, ...]:
    if not metrics:
        return ()
    bin_count = len(metrics[0].bins)
    output: list[SemanticCalibrationBin] = []
    for index in range(bin_count):
        bins = tuple(item.bins[index] for item in metrics)
        count = sum(item.count for item in bins)
        output.append(
            SemanticCalibrationBin(
                lower=bins[0].lower,
                upper=bins[0].upper,
                count=count,
                mean_confidence=(
                    sum((item.mean_confidence or 0.0) * item.count for item in bins) / count
                    if count
                    else None
                ),
                accuracy=(
                    sum((item.accuracy or 0.0) * item.count for item in bins) / count
                    if count
                    else None
                ),
            )
        )
    return tuple(output)


def semantic_benchmark_report_hash(
    report: SemanticBenchmarkEvaluationReport,
) -> str:
    encoded = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_semantic_gold_dataset(path: str | Path) -> SemanticGoldDataset:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticEvaluationError(
            f"cannot load semantic gold dataset {source}: {exc}"
        ) from exc
    try:
        return SemanticGoldDataset.model_validate(payload)
    except ValueError as exc:
        raise SemanticEvaluationError(
            f"invalid semantic gold dataset {source}: {exc}"
        ) from exc
