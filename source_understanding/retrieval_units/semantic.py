from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    Confidence,
    ContentHash,
    Identifier,
    JsonObject,
    SchemaModel,
)
from source_understanding.schemas.document import (
    CanonicalDocument,
    SemanticAnnotation,
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticPayloadMode,
)
from source_understanding.schemas.retrieval_unit import AnnotationRef, RetrievalUnit
from source_understanding.semantics.provider import (
    EXTRACTIVE_SEMANTIC_ANNOTATION_TYPES,
    SemanticProviderCapabilities,
    SemanticTargetKind,
)
from source_understanding.semantics.fingerprint import (
    SEMANTIC_CONFIGURATION_FINGERPRINT_VERSION,
    semantic_configuration_hash,
    semantic_provider_capabilities_hash,
)


SEMANTIC_RETRIEVAL_ENRICHER_VERSION = "3"


class SemanticRetrievalEnrichmentError(ValueError):
    """Semantic annotations cannot be projected safely into RetrievalUnits."""


_DEFAULT_ANNOTATION_TYPES = tuple(
    annotation_type
    for annotation_type in SemanticAnnotationType
    if annotation_type != SemanticAnnotationType.CUSTOM
)


class SemanticRetrievalPolicy(SchemaModel):
    """Bounded semantic projection policy; thresholds remain evaluation policy."""

    version: str = Field(default=SEMANTIC_RETRIEVAL_ENRICHER_VERSION, min_length=1, max_length=128)
    enabled: bool = True
    min_confidence: Confidence = 0.75
    max_annotations_per_unit: int = Field(default=6, ge=1, le=64)
    max_semantic_tokens: int | None = Field(default=96, ge=1)
    max_rendered_value_chars: int = Field(default=384, ge=32, le=4096)
    allowed_types: tuple[SemanticAnnotationType, ...] = _DEFAULT_ANNOTATION_TYPES
    allowed_confidence_methods: tuple[SemanticConfidenceMethod, ...] = (
        SemanticConfidenceMethod.RULE_PRIOR,
        SemanticConfidenceMethod.CALIBRATED_PROBABILITY,
        SemanticConfidenceMethod.EMPIRICAL_PROVIDER_SCORE,
    )
    include_context_annotations: bool = True
    include_region_annotations: bool = False
    include_subdocument_annotations: bool = False
    respect_existing_max_tokens: bool = True
    semantic_header: str = Field(default="Semantic context:", min_length=1, max_length=256)
    semantic_line_separator: str = "\n"
    semantic_block_separator: str = "\n"

    @model_validator(mode="after")
    def validate_policy(self) -> "SemanticRetrievalPolicy":
        if len(self.allowed_types) != len(set(self.allowed_types)):
            raise ValueError("allowed_types must be unique")
        if len(self.allowed_confidence_methods) != len(
            set(self.allowed_confidence_methods)
        ):
            raise ValueError("allowed_confidence_methods must be unique")
        for name in ("semantic_line_separator", "semantic_block_separator"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        return self


class SemanticQualityGateStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SemanticCapabilityQualityDecision(SchemaModel):
    """One benchmark decision for an exact provider capability slice."""

    provider_name: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=128)
    capability_name: str = Field(min_length=1, max_length=128)
    annotation_type: SemanticAnnotationType
    payload_mode: SemanticPayloadMode | None = None
    target_kind: SemanticTargetKind
    language: str = Field(min_length=2, max_length=64)
    role_support: int = Field(ge=0)
    role_f1: Confidence | None = None
    value_support: int = Field(ge=0)
    value_normalized_f1: Confidence | None = None
    typed_span_support: int = Field(ge=0)
    typed_span_exact_f1: Confidence | None = None
    typed_span_overlap_f1: Confidence | None = None
    grounding_predicted_count: int = Field(ge=0)
    grounding_supported_ratio: Confidence | None = None
    grounding_unsupported_rate: Confidence | None = None
    calibration_count: int = Field(ge=0)
    brier_score: Confidence | None = None
    expected_calibration_error: Confidence | None = None
    status: SemanticQualityGateStatus
    reasons: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def default_payload_mode(cls, value: object) -> object:
        if not isinstance(value, dict) or value.get("payload_mode") is not None:
            return value
        from source_understanding.schemas.document import semantic_payload_mode_for_type

        payload = dict(value)
        payload["payload_mode"] = semantic_payload_mode_for_type(
            SemanticAnnotationType(payload["annotation_type"])
        )
        return payload

    @model_validator(mode="after")
    def validate_decision(self) -> "SemanticCapabilityQualityDecision":
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("semantic quality decision reasons must be unique")
        if self.status == SemanticQualityGateStatus.APPROVED and self.reasons:
            raise ValueError("approved semantic quality decisions cannot carry rejection reasons")
        if self.status == SemanticQualityGateStatus.REJECTED and not self.reasons:
            raise ValueError("rejected semantic quality decisions require a reason")
        if (
            self.grounding_predicted_count == 0
            and (
                self.grounding_supported_ratio is not None
                or self.grounding_unsupported_rate is not None
            )
        ):
            raise ValueError("grounding ratios require at least one prediction")
        return self

    @property
    def key(self) -> tuple[str, str, SemanticAnnotationType, SemanticTargetKind, str]:
        return (
            self.provider_name,
            self.capability_name,
            self.annotation_type,
            self.target_kind,
            self.language.casefold(),
        )


class SemanticRetrievalQualityGate(SchemaModel):
    """Held-out attestation with decisions at capability/type/language granularity."""

    evaluator_version: str = Field(min_length=1, max_length=128)
    benchmark_name: str = Field(min_length=1, max_length=256)
    benchmark_version: str = Field(min_length=1, max_length=128)
    benchmark_split: str = Field(pattern=r"^test$")
    dataset_hash: ContentHash
    report_hash: ContentHash
    semantic_version: str = Field(min_length=1, max_length=128)
    configuration_fingerprint_version: str = Field(min_length=1, max_length=128)
    provider_versions: JsonObject
    provider_capability_hashes: JsonObject
    provider_configuration_hashes: JsonObject
    provider_annotator_policy_hashes: JsonObject
    minimum_role_f1: Confidence
    minimum_grounding_supported_ratio: Confidence
    maximum_grounding_unsupported_rate: Confidence
    minimum_extractive_value_f1: Confidence
    minimum_extractive_span_f1: Confidence
    decisions: tuple[SemanticCapabilityQualityDecision, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_gate(self) -> "SemanticRetrievalQualityGate":
        if (
            self.configuration_fingerprint_version
            != SEMANTIC_CONFIGURATION_FINGERPRINT_VERSION
        ):
            raise ValueError(
                "quality gate configuration fingerprint version is unsupported"
            )
        if not self.provider_versions:
            raise ValueError("quality gate requires at least one evaluated provider")
        for name, version in self.provider_versions.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(version, str)
                or not version.strip()
            ):
                raise ValueError(
                    "quality gate provider_versions must map names to versions"
                )
        provider_names = set(self.provider_versions)
        for field_name in (
            "provider_capability_hashes",
            "provider_configuration_hashes",
            "provider_annotator_policy_hashes",
        ):
            values = getattr(self, field_name)
            if set(values) != provider_names:
                raise ValueError(
                    f"quality gate {field_name} keys must exactly match provider_versions"
                )
            for name, value in values.items():
                if (
                    not isinstance(value, str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                ):
                    raise ValueError(
                        f"quality gate {field_name}[{name!r}] must be a SHA-256 hash"
                    )
        keys = [decision.key for decision in self.decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("semantic quality gate decision identities must be unique")
        for decision in self.decisions:
            if self.provider_versions.get(decision.provider_name) != decision.provider_version:
                raise ValueError(
                    f"semantic quality decision provider version does not match gate: "
                    f"{decision.provider_name!r}"
                )
            expected_reasons: list[str] = []
            if decision.role_support == 0:
                expected_reasons.append("NO_GOLD_SUPPORT")
            if decision.role_f1 is None or decision.role_f1 < self.minimum_role_f1:
                expected_reasons.append("ROLE_F1_BELOW_THRESHOLD")
            if (
                decision.grounding_supported_ratio is None
                or decision.grounding_supported_ratio
                < self.minimum_grounding_supported_ratio
            ):
                expected_reasons.append("GROUNDING_SUPPORTED_RATIO_BELOW_THRESHOLD")
            if (
                decision.grounding_unsupported_rate is None
                or decision.grounding_unsupported_rate
                > self.maximum_grounding_unsupported_rate
            ):
                expected_reasons.append("GROUNDING_UNSUPPORTED_RATE_ABOVE_THRESHOLD")
            if decision.annotation_type in EXTRACTIVE_SEMANTIC_ANNOTATION_TYPES:
                if (
                    decision.value_normalized_f1 is None
                    or decision.value_normalized_f1
                    < self.minimum_extractive_value_f1
                ):
                    expected_reasons.append("EXTRACTIVE_VALUE_F1_BELOW_THRESHOLD")
                if (
                    decision.typed_span_exact_f1 is None
                    or decision.typed_span_exact_f1
                    < self.minimum_extractive_span_f1
                ):
                    expected_reasons.append("EXTRACTIVE_SPAN_F1_BELOW_THRESHOLD")
                if decision.payload_mode != SemanticPayloadMode.EXTRACTIVE:
                    expected_reasons.append("EXTRACTIVE_PAYLOAD_MODE_REQUIRED")
            if decision.payload_mode == SemanticPayloadMode.GENERATIVE:
                expected_reasons.append("GENERATIVE_FAITHFULNESS_NOT_EVALUATED")
            if decision.annotation_type == SemanticAnnotationType.CUSTOM:
                expected_reasons.append(
                    "CUSTOM_ONTOLOGY_APPROVAL_REQUIRES_ONTOLOGY_SLICE"
                )
            expected_status = (
                SemanticQualityGateStatus.REJECTED
                if expected_reasons
                else SemanticQualityGateStatus.APPROVED
            )
            if decision.status != expected_status or decision.reasons != tuple(
                expected_reasons
            ):
                raise ValueError(
                    "semantic quality decision status/reasons do not match gate thresholds: "
                    f"{decision.key}"
                )
        if not any(
            decision.status == SemanticQualityGateStatus.APPROVED
            for decision in self.decisions
        ):
            raise ValueError("semantic quality gate has no approved capability slice")
        return self

    def decision_for(
        self,
        *,
        provider_name: str,
        capability_name: str,
        annotation_type: SemanticAnnotationType,
        target_kind: SemanticTargetKind,
        language: str,
    ) -> SemanticCapabilityQualityDecision | None:
        key = (
            provider_name,
            capability_name,
            annotation_type,
            target_kind,
            language.casefold(),
        )
        return next((item for item in self.decisions if item.key == key), None)


def quality_gate_from_semantic_benchmark(
    report: object,
    *,
    semantic_version: str,
    provider_versions: dict[str, str],
    provider_capabilities: dict[str, object],
    provider_configurations: dict[str, object],
    provider_annotator_policies: dict[str, object],
    minimum_role_f1: float,
    minimum_grounding_supported_ratio: float = 1.0,
    maximum_grounding_unsupported_rate: float = 0.0,
    minimum_extractive_value_f1: float = 0.9,
    minimum_extractive_span_f1: float = 0.9,
) -> SemanticRetrievalQualityGate:
    """Build exact capability decisions from a held-out semantic benchmark."""

    from source_understanding.evaluation.semantic import (
        SemanticBenchmarkEvaluationReport,
        semantic_benchmark_report_hash,
    )
    from source_understanding.evaluation.schemas import BenchmarkSplit

    validated = SemanticBenchmarkEvaluationReport.model_validate(report)
    if validated.split != BenchmarkSplit.TEST:
        raise SemanticRetrievalEnrichmentError(
            "semantic retrieval quality gates require a held-out TEST report"
        )
    provider_names = set(provider_versions)
    if set(provider_capabilities) != provider_names:
        raise SemanticRetrievalEnrichmentError(
            "provider_capabilities keys must exactly match provider_versions"
        )
    if set(provider_configurations) != provider_names:
        raise SemanticRetrievalEnrichmentError(
            "provider_configurations keys must exactly match provider_versions"
        )
    if set(provider_annotator_policies) != provider_names:
        raise SemanticRetrievalEnrichmentError(
            "provider_annotator_policies keys must exactly match provider_versions"
        )
    validated_capabilities = {
        name: SemanticProviderCapabilities.model_validate(provider_capabilities[name])
        for name in sorted(provider_names)
    }
    decisions: list[SemanticCapabilityQualityDecision] = []
    for item in validated.capability_slices:
        if item.role.support == 0 and item.role.false_positive == 0:
            continue
        provider_name = item.provider_name
        capability_name = item.capability_name
        if provider_name == "SYSTEM_FUSED" or capability_name is None:
            raise SemanticRetrievalEnrichmentError(
                "retrieval quality gates require provider/capability-attributed benchmark slices: "
                f"{item.key}"
            )
        declared = validated_capabilities.get(provider_name)
        matches = tuple(
            capability
            for capability in (declared.capabilities if declared is not None else ())
            if capability.name == capability_name
            and item.target_kind in capability.target_kinds
            and item.annotation_type in capability.annotation_types
        )
        if not matches:
            raise SemanticRetrievalEnrichmentError(
                "semantic benchmark slice has no matching declared provider capability: "
                f"{item.key}"
            )
        if len(matches) > 1:
            raise SemanticRetrievalEnrichmentError(
                "semantic benchmark slice maps to multiple declarations unexpectedly: "
                f"{item.key}"
            )
        capability = next(iter(matches))
        reasons: list[str] = []
        if item.role.support == 0:
            reasons.append("NO_GOLD_SUPPORT")
        if item.role.f1 is None or item.role.f1 < minimum_role_f1:
            reasons.append("ROLE_F1_BELOW_THRESHOLD")
        if (
            item.grounding.supported_ratio is None
            or item.grounding.supported_ratio < minimum_grounding_supported_ratio
        ):
            reasons.append("GROUNDING_SUPPORTED_RATIO_BELOW_THRESHOLD")
        if (
            item.grounding.unsupported_rate is None
            or item.grounding.unsupported_rate > maximum_grounding_unsupported_rate
        ):
            reasons.append("GROUNDING_UNSUPPORTED_RATE_ABOVE_THRESHOLD")
        if item.annotation_type in EXTRACTIVE_SEMANTIC_ANNOTATION_TYPES:
            if (
                item.value_normalized.f1 is None
                or item.value_normalized.f1 < minimum_extractive_value_f1
            ):
                reasons.append("EXTRACTIVE_VALUE_F1_BELOW_THRESHOLD")
            if (
                item.typed_span_exact.f1 is None
                or item.typed_span_exact.f1 < minimum_extractive_span_f1
            ):
                reasons.append("EXTRACTIVE_SPAN_F1_BELOW_THRESHOLD")
        if item.payload_mode == SemanticPayloadMode.GENERATIVE:
            reasons.append("GENERATIVE_FAITHFULNESS_NOT_EVALUATED")
        if item.annotation_type in EXTRACTIVE_SEMANTIC_ANNOTATION_TYPES and item.payload_mode != SemanticPayloadMode.EXTRACTIVE:
            reasons.append("EXTRACTIVE_PAYLOAD_MODE_REQUIRED")
        if item.annotation_type == SemanticAnnotationType.CUSTOM:
            reasons.append("CUSTOM_ONTOLOGY_APPROVAL_REQUIRES_ONTOLOGY_SLICE")
        decisions.append(
            SemanticCapabilityQualityDecision(
                provider_name=provider_name,
                provider_version=provider_versions[provider_name],
                capability_name=capability.name,
                annotation_type=item.annotation_type,
                payload_mode=item.payload_mode,
                target_kind=item.target_kind,
                language=item.language,
                role_support=item.role.support,
                role_f1=item.role.f1,
                value_support=item.value_normalized.support,
                value_normalized_f1=item.value_normalized.f1,
                typed_span_support=item.typed_span_exact.support,
                typed_span_exact_f1=item.typed_span_exact.f1,
                typed_span_overlap_f1=item.typed_span_overlap.f1,
                grounding_predicted_count=item.grounding.predicted_count,
                grounding_supported_ratio=item.grounding.supported_ratio,
                grounding_unsupported_rate=item.grounding.unsupported_rate,
                calibration_count=item.calibration.count,
                brier_score=item.calibration.brier_score,
                expected_calibration_error=item.calibration.expected_calibration_error,
                status=(
                    SemanticQualityGateStatus.REJECTED
                    if reasons
                    else SemanticQualityGateStatus.APPROVED
                ),
                reasons=tuple(reasons),
            )
        )
    if not decisions:
        raise SemanticRetrievalEnrichmentError(
            "semantic benchmark has no capability slice with gold or predicted support"
        )
    return SemanticRetrievalQualityGate(
        evaluator_version=validated.version,
        benchmark_name=validated.dataset_name,
        benchmark_version=validated.benchmark_version,
        benchmark_split=validated.split.value,
        dataset_hash=validated.dataset_hash,
        report_hash=semantic_benchmark_report_hash(validated),
        semantic_version=semantic_version,
        configuration_fingerprint_version=SEMANTIC_CONFIGURATION_FINGERPRINT_VERSION,
        provider_versions=cast(JsonObject, provider_versions),
        provider_capability_hashes={
            name: semantic_provider_capabilities_hash(validated_capabilities[name])
            for name in sorted(provider_names)
        },
        provider_configuration_hashes={
            name: semantic_configuration_hash(provider_configurations[name])
            for name in sorted(provider_names)
        },
        provider_annotator_policy_hashes={
            name: semantic_configuration_hash(provider_annotator_policies[name])
            for name in sorted(provider_names)
        },
        minimum_role_f1=minimum_role_f1,
        minimum_grounding_supported_ratio=minimum_grounding_supported_ratio,
        maximum_grounding_unsupported_rate=maximum_grounding_unsupported_rate,
        minimum_extractive_value_f1=minimum_extractive_value_f1,
        minimum_extractive_span_f1=minimum_extractive_span_f1,
        decisions=tuple(decisions),
    )


class SemanticRetrievalResult(SchemaModel):
    version: str = SEMANTIC_RETRIEVAL_ENRICHER_VERSION
    document_id: Identifier
    policy: SemanticRetrievalPolicy
    quality_gate: SemanticRetrievalQualityGate | None = None
    source_unit_count: int = Field(ge=0)
    enriched_unit_count: int = Field(ge=0)
    units: tuple[RetrievalUnit, ...] = Field(default_factory=tuple)
    referenced_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    rendered_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_low_confidence_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_untrusted_confidence_annotation_ids: tuple[Identifier, ...] = Field(
        default_factory=tuple
    )
    skipped_disallowed_type_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_unevaluated_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    skipped_budget_annotation_ids: tuple[Identifier, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_result(self) -> "SemanticRetrievalResult":
        unit_ids = [unit.id for unit in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("semantic retrieval output unit ids must be unique")
        if self.enriched_unit_count > self.source_unit_count:
            raise ValueError("enriched_unit_count cannot exceed source_unit_count")
        for name in (
            "referenced_annotation_ids",
            "rendered_annotation_ids",
            "skipped_low_confidence_annotation_ids",
            "skipped_untrusted_confidence_annotation_ids",
            "skipped_disallowed_type_annotation_ids",
            "skipped_unevaluated_annotation_ids",
            "skipped_budget_annotation_ids",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        return self


@dataclass(frozen=True, slots=True)
class _Candidate:
    annotation: SemanticAnnotation
    scope: str
    scope_rank: int
    document_order: int


class SemanticRetrievalEnricher:
    """Attach and optionally render relevant semantic annotations for retrieval.

    The canonical source remains authoritative. Semantic text is retrieval-only:
    display text and source anchors are preserved byte-for-byte/model-for-model.
    """

    version: str = SEMANTIC_RETRIEVAL_ENRICHER_VERSION

    def __init__(
        self,
        token_counter: Callable[[str], int],
        policy: SemanticRetrievalPolicy | None = None,
        *,
        quality_gate: SemanticRetrievalQualityGate | None = None,
    ) -> None:
        if not callable(token_counter):
            raise TypeError("token_counter must be callable")
        self._token_counter = token_counter
        self._policy = policy if policy is not None else SemanticRetrievalPolicy()
        self._quality_gate = quality_gate

    def enrich(
        self,
        document: CanonicalDocument,
        units: Iterable[RetrievalUnit],
    ) -> SemanticRetrievalResult:
        source_units = tuple(units)
        for unit in source_units:
            self._validate_base_unit(document, unit)

        if not self._policy.enabled:
            return SemanticRetrievalResult(
                document_id=document.document_id,
                policy=self._policy,
                source_unit_count=len(source_units),
                enriched_unit_count=0,
                units=source_units,
            )

        quality_gate = self._validate_quality_gate(document)

        annotation_order = {
            annotation.id: index
            for index, annotation in enumerate(document.semantic_annotations)
        }
        type_rank = {
            annotation_type: index
            for index, annotation_type in enumerate(self._policy.allowed_types)
        }
        region_members = {
            region.id: frozenset(region.element_ids)
            for region in document.regions
        }

        output: list[RetrievalUnit] = []
        referenced: list[str] = []
        rendered: list[str] = []
        skipped_low_confidence: list[str] = []
        skipped_untrusted_confidence: list[str] = []
        skipped_disallowed: list[str] = []
        skipped_unevaluated: list[str] = []
        skipped_budget: list[str] = []
        enriched_count = 0

        for unit in source_units:
            (
                candidates,
                low_ids,
                untrusted_ids,
                disallowed_ids,
                unevaluated_ids,
            ) = self._candidates_for_unit(
                document,
                unit,
                annotation_order,
                type_rank,
                region_members,
            )
            skipped_low_confidence.extend(low_ids)
            skipped_untrusted_confidence.extend(untrusted_ids)
            skipped_disallowed.extend(disallowed_ids)
            skipped_unevaluated.extend(unevaluated_ids)

            selected = self._select_candidates(candidates)
            if not selected:
                output.append(unit)
                continue

            enriched, rendered_ids, budget_ids = self._enrich_unit(
                document,
                unit,
                selected,
            )
            output.append(enriched)
            enriched_count += 1
            referenced.extend(candidate.annotation.id for candidate in selected)
            rendered.extend(rendered_ids)
            skipped_budget.extend(budget_ids)

        return SemanticRetrievalResult(
            document_id=document.document_id,
            policy=self._policy,
            quality_gate=quality_gate,
            source_unit_count=len(source_units),
            enriched_unit_count=enriched_count,
            units=tuple(output),
            referenced_annotation_ids=self._unique(referenced),
            rendered_annotation_ids=self._unique(rendered),
            skipped_low_confidence_annotation_ids=self._unique(skipped_low_confidence),
            skipped_untrusted_confidence_annotation_ids=self._unique(
                skipped_untrusted_confidence
            ),
            skipped_disallowed_type_annotation_ids=self._unique(skipped_disallowed),
            skipped_unevaluated_annotation_ids=self._unique(skipped_unevaluated),
            skipped_budget_annotation_ids=self._unique(skipped_budget),
        )

    def _validate_base_unit(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
    ) -> None:
        try:
            unit.validate_against_document(document)
        except ValueError as exc:
            raise SemanticRetrievalEnrichmentError(
                f"base retrieval unit {unit.id!r} is invalid for canonical document: {exc}"
            ) from exc
        if unit.metadata.get("semantic_enricher_version") is not None:
            raise SemanticRetrievalEnrichmentError(
                f"retrieval unit {unit.id!r} is already semantic-enriched; "
                "rebuild base RetrievalUnits before re-enrichment"
            )

    def _candidates_for_unit(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
        annotation_order: dict[str, int],
        type_rank: dict[SemanticAnnotationType, int],
        region_members: dict[str, frozenset[str]],
    ) -> tuple[list[_Candidate], list[str], list[str], list[str], list[str]]:
        relevant: list[tuple[SemanticAnnotation, str, int]] = []
        element_ids = frozenset(unit.element_ids)
        logical_ids = frozenset(unit.logical_unit_ids)
        context_ids = frozenset(ref.id for ref in unit.context_path)

        for annotation in document.semantic_annotations:
            scope = self._annotation_scope(
                annotation.target_id,
                unit,
                element_ids,
                logical_ids,
                context_ids,
                region_members,
            )
            if scope is None:
                continue
            relevant.append((annotation, scope[0], scope[1]))

        low_confidence: list[str] = []
        untrusted_confidence: list[str] = []
        disallowed: list[str] = []
        unevaluated: list[str] = []
        candidates: list[_Candidate] = []
        for annotation, scope_name, scope_rank in relevant:
            if annotation.type not in type_rank:
                disallowed.append(annotation.id)
                continue
            if annotation.confidence_method not in self._policy.allowed_confidence_methods:
                untrusted_confidence.append(annotation.id)
                continue
            if not self._annotation_is_evaluated(annotation, scope_name):
                unevaluated.append(annotation.id)
                continue
            if annotation.confidence < self._policy.min_confidence:
                low_confidence.append(annotation.id)
                continue
            candidates.append(
                _Candidate(
                    annotation=annotation,
                    scope=scope_name,
                    scope_rank=scope_rank,
                    document_order=annotation_order[annotation.id],
                )
            )

        candidates.sort(
            key=lambda candidate: (
                candidate.scope_rank,
                -candidate.annotation.confidence,
                type_rank[candidate.annotation.type],
                candidate.document_order,
                candidate.annotation.id,
            )
        )
        return candidates, low_confidence, untrusted_confidence, disallowed, unevaluated

    def _annotation_scope(
        self,
        target_id: str,
        unit: RetrievalUnit,
        element_ids: frozenset[str],
        logical_ids: frozenset[str],
        context_ids: frozenset[str],
        region_members: dict[str, frozenset[str]],
    ) -> tuple[str, int] | None:
        if target_id in element_ids:
            return "ELEMENT", 0
        if target_id in logical_ids:
            return "LOGICAL_UNIT", 1
        if self._policy.include_context_annotations and target_id in context_ids:
            return "CONTEXT", 2
        if self._policy.include_region_annotations:
            members = region_members.get(target_id)
            if members is not None and element_ids.issubset(members):
                return "REGION", 3
        if (
            self._policy.include_subdocument_annotations
            and unit.subdocument_id is not None
            and target_id == unit.subdocument_id
        ):
            return "SUBDOCUMENT", 4
        return None

    def _select_candidates(self, candidates: list[_Candidate]) -> tuple[_Candidate, ...]:
        unique: list[_Candidate] = []
        seen_semantics: set[tuple[SemanticAnnotationType, str]] = set()
        for candidate in candidates:
            semantic_key = (
                candidate.annotation.type,
                self._compact_value(candidate.annotation.value).casefold(),
            )
            if semantic_key in seen_semantics:
                continue
            seen_semantics.add(semantic_key)
            unique.append(candidate)
            if len(unique) >= self._policy.max_annotations_per_unit:
                break
        return tuple(unique)

    def _enrich_unit(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
        selected: tuple[_Candidate, ...],
    ) -> tuple[RetrievalUnit, tuple[str, ...], tuple[str, ...]]:
        rendered_candidates: list[_Candidate] = []
        budget_skipped: list[str] = []
        retrieval_text = unit.retrieval_text
        token_count = unit.token_count
        existing_max_tokens = self._existing_max_tokens(unit)

        for candidate in selected:
            proposed_candidates = (*rendered_candidates, candidate)
            semantic_block = self._semantic_block(proposed_candidates)
            if (
                self._policy.max_semantic_tokens is not None
                and self._count_tokens(semantic_block) > self._policy.max_semantic_tokens
            ):
                budget_skipped.append(candidate.annotation.id)
                continue

            proposed_text = (
                semantic_block
                + self._policy.semantic_block_separator
                + unit.retrieval_text
            )
            proposed_count = self._count_tokens(proposed_text)
            if existing_max_tokens is not None and proposed_count > existing_max_tokens:
                budget_skipped.append(candidate.annotation.id)
                continue

            rendered_candidates.append(candidate)
            retrieval_text = proposed_text
            token_count = proposed_count

        refs = self._merge_annotation_refs(unit, selected)
        rendered_ids = tuple(
            candidate.annotation.id for candidate in rendered_candidates
        )
        selected_ids = tuple(candidate.annotation.id for candidate in selected)
        target_scopes = {
            candidate.annotation.id: candidate.scope for candidate in selected
        }
        quality_gate = self._require_quality_gate()

        metadata = dict(unit.metadata)
        metadata.update(
            {
                "semantic_enrichment_used": bool(rendered_ids),
                "semantic_enricher_version": self.version,
                "semantic_policy_version": self._policy.version,
                "semantic_min_confidence": self._policy.min_confidence,
                "semantic_annotation_count": len(selected_ids),
                "semantic_annotation_ids": list(selected_ids),
                "semantic_rendered_annotation_ids": list(rendered_ids),
                "semantic_skipped_budget_annotation_ids": list(budget_skipped),
                "semantic_annotation_target_scopes": target_scopes,
                "semantic_quality_benchmark": quality_gate.benchmark_name,
                "semantic_quality_benchmark_version": quality_gate.benchmark_version,
                "semantic_quality_report_hash": quality_gate.report_hash,
                "semantic_context_is_source_fact": False,
                "base_retrieval_unit_id": unit.id,
            }
        )

        enriched_id = self._unit_id(
            document,
            unit,
            selected_ids,
            rendered_ids,
            retrieval_text,
        )
        version = f"{unit.version}+sem{self.version}"
        payload = unit.model_dump(mode="python")
        payload.update(
            {
                "id": enriched_id,
                "retrieval_text": retrieval_text,
                "semantic_annotations": refs,
                "token_count": token_count,
                "version": version,
                "metadata": metadata,
            }
        )
        enriched = RetrievalUnit(**payload)
        try:
            enriched.validate_against_document(document)
        except ValueError as exc:
            raise SemanticRetrievalEnrichmentError(
                f"semantic retrieval unit {enriched.id!r} failed canonical validation: {exc}"
            ) from exc
        return enriched, rendered_ids, tuple(budget_skipped)

    def _merge_annotation_refs(
        self,
        unit: RetrievalUnit,
        selected: tuple[_Candidate, ...],
    ) -> tuple[AnnotationRef, ...]:
        refs = list(unit.semantic_annotations)
        existing_ids = {ref.id for ref in refs}
        for candidate in selected:
            annotation = candidate.annotation
            if annotation.id in existing_ids:
                continue
            refs.append(
                AnnotationRef(
                    id=annotation.id,
                    type=annotation.type.value,
                value=(
                    annotation.value
                    if annotation.payload_mode != SemanticPayloadMode.GENERATIVE
                    and len(annotation.value) <= 2048
                    else None
                ),
                    source=annotation.source,
                    confidence=annotation.confidence,
                )
            )
            existing_ids.add(annotation.id)
        return tuple(refs)

    def _semantic_block(self, candidates: tuple[_Candidate, ...]) -> str:
        lines = [self._policy.semantic_header]
        lines.extend(self._render_annotation(candidate.annotation) for candidate in candidates)
        return self._policy.semantic_line_separator.join(lines)

    def _render_annotation(self, annotation: SemanticAnnotation) -> str:
        label = annotation.type.value.replace("_", " ").title()
        if annotation.payload_mode != SemanticPayloadMode.EXTRACTIVE:
            return label
        value = self._compact_value(annotation.value)
        max_chars = self._policy.max_rendered_value_chars
        if len(value) > max_chars:
            value = value[: max_chars - 1].rstrip() + "…"
        return f"{label}: {value}"

    @staticmethod
    def _compact_value(value: str) -> str:
        return " ".join(value.split())

    def _existing_max_tokens(self, unit: RetrievalUnit) -> int | None:
        if not self._policy.respect_existing_max_tokens:
            return None
        value = unit.metadata.get("max_tokens")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
        return value

    def _count_tokens(self, text: str) -> int:
        count = self._token_counter(text)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise SemanticRetrievalEnrichmentError(
                "token_counter must return a positive integer for non-blank retrieval text"
            )
        return count

    def _unit_id(
        self,
        document: CanonicalDocument,
        unit: RetrievalUnit,
        annotation_ids: tuple[str, ...],
        rendered_ids: tuple[str, ...],
        retrieval_text: str,
    ) -> str:
        payload = {
            "enricher_version": self.version,
            "policy": self._policy.model_dump(mode="json"),
            "quality_gate": self._require_quality_gate().model_dump(mode="json"),
            "document_id": document.document_id,
            "content_hash": document.content_hash,
            "source_revision": document.source_revision,
            "base_unit_id": unit.id,
            "annotation_ids": annotation_ids,
            "rendered_ids": rendered_ids,
            "retrieval_text": retrieval_text,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()[:32]
        return f"ru_{digest}"

    @staticmethod
    def _unique(values: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))

    def _require_quality_gate(self) -> SemanticRetrievalQualityGate:
        gate = self._quality_gate
        if gate is None:
            raise SemanticRetrievalEnrichmentError(
                "semantic retrieval enrichment requires an evaluation quality gate"
            )
        return gate

    @staticmethod
    def _require_manifest_mapping(
        manifest: dict[str, object],
        name: str,
    ) -> dict[str, object]:
        value = manifest.get(name)
        if not isinstance(value, dict):
            raise SemanticRetrievalEnrichmentError(
                f"canonical semantic manifest lacks {name} required by quality gate"
            )
        return cast(dict[str, object], value)

    def _validate_quality_gate(
        self,
        document: CanonicalDocument,
    ) -> SemanticRetrievalQualityGate:
        gate = self._require_quality_gate()
        if document.processing.semantic_version != gate.semantic_version:
            raise SemanticRetrievalEnrichmentError(
                "quality gate semantic_version does not match canonical document"
            )
        semantic_configuration_value = document.processing.configuration.get(
            "semantic_understanding"
        )
        if not isinstance(semantic_configuration_value, dict):
            raise SemanticRetrievalEnrichmentError(
                "canonical document lacks semantic provider manifest required by quality gate"
            )
        semantic_configuration = cast(
            dict[str, object],
            semantic_configuration_value,
        )
        providers = self._require_manifest_mapping(
            semantic_configuration,
            "providers",
        )
        fingerprint_version = semantic_configuration.get(
            "configuration_fingerprint_version"
        )
        if fingerprint_version != gate.configuration_fingerprint_version:
            raise SemanticRetrievalEnrichmentError(
                "quality gate configuration fingerprint version does not match "
                "canonical semantic manifest"
            )
        provider_configurations = self._require_manifest_mapping(
            semantic_configuration,
            "provider_configurations",
        )
        provider_capabilities = self._require_manifest_mapping(
            semantic_configuration,
            "provider_capabilities",
        )
        provider_capability_hashes = self._require_manifest_mapping(
            semantic_configuration,
            "provider_capability_hashes",
        )
        provider_configuration_hashes = self._require_manifest_mapping(
            semantic_configuration,
            "provider_configuration_hashes",
        )
        provider_annotator_policies = self._require_manifest_mapping(
            semantic_configuration,
            "provider_annotator_policies",
        )
        provider_annotator_policy_hashes = self._require_manifest_mapping(
            semantic_configuration,
            "provider_annotator_policy_hashes",
        )
        for provider_name, provider_version in gate.provider_versions.items():
            if providers.get(provider_name) != provider_version:
                raise SemanticRetrievalEnrichmentError(
                    f"quality gate provider {provider_name!r} version does not match "
                    "canonical semantic manifest"
                )
            configuration = provider_configurations.get(provider_name)
            capabilities = provider_capabilities.get(provider_name)
            policy = provider_annotator_policies.get(provider_name)
            if (
                not isinstance(capabilities, dict)
                or not isinstance(configuration, dict)
                or not isinstance(policy, dict)
            ):
                raise SemanticRetrievalEnrichmentError(
                    f"canonical semantic manifest lacks evaluated configuration for "
                    f"provider {provider_name!r}"
                )
            actual_configuration_hash = semantic_configuration_hash(configuration)
            actual_capability_hash = semantic_provider_capabilities_hash(capabilities)
            actual_policy_hash = semantic_configuration_hash(policy)
            if provider_capability_hashes.get(provider_name) != actual_capability_hash:
                raise SemanticRetrievalEnrichmentError(
                    f"canonical semantic manifest capability hash is inconsistent for "
                    f"provider {provider_name!r}"
                )
            if provider_configuration_hashes.get(provider_name) != actual_configuration_hash:
                raise SemanticRetrievalEnrichmentError(
                    f"canonical semantic manifest configuration hash is inconsistent for "
                    f"provider {provider_name!r}"
                )
            if provider_annotator_policy_hashes.get(provider_name) != actual_policy_hash:
                raise SemanticRetrievalEnrichmentError(
                    f"canonical semantic manifest annotator policy hash is inconsistent for "
                    f"provider {provider_name!r}"
                )
            if gate.provider_configuration_hashes.get(provider_name) != actual_configuration_hash:
                raise SemanticRetrievalEnrichmentError(
                    f"quality gate provider {provider_name!r} configuration does not match "
                    "canonical semantic manifest"
                )
            if gate.provider_capability_hashes.get(provider_name) != actual_capability_hash:
                raise SemanticRetrievalEnrichmentError(
                    f"quality gate provider {provider_name!r} capability declaration does not "
                    "match canonical semantic manifest"
                )
            if gate.provider_annotator_policy_hashes.get(provider_name) != actual_policy_hash:
                raise SemanticRetrievalEnrichmentError(
                    f"quality gate provider {provider_name!r} annotator policy does not match "
                    "canonical semantic manifest"
                )
        return gate

    def _annotation_is_evaluated(
        self,
        annotation: SemanticAnnotation,
        scope: str,
    ) -> bool:
        gate = self._quality_gate
        if gate is None:
            return False
        target_kind = {
            "ELEMENT": SemanticTargetKind.ELEMENT,
            "LOGICAL_UNIT": SemanticTargetKind.LOGICAL_UNIT,
        }.get(scope)
        if target_kind is None:
            return False
        provider_name = annotation.metadata.get("semantic_provider")
        provider_version = annotation.metadata.get("semantic_provider_version")
        provider_configuration_hash = annotation.metadata.get(
            "semantic_provider_configuration_hash"
        )
        annotator_policy_hash = annotation.metadata.get(
            "semantic_annotator_policy_hash"
        )
        capability_name = annotation.metadata.get("semantic_capability")
        language = annotation.metadata.get("semantic_request_language")
        if not isinstance(capability_name, str) or not isinstance(language, str):
            return False
        decision = gate.decision_for(
            provider_name=provider_name if isinstance(provider_name, str) else "",
            capability_name=capability_name,
            annotation_type=annotation.type,
            target_kind=target_kind,
            language=language,
        )
        return (
            isinstance(provider_name, str)
            and isinstance(provider_version, str)
            and gate.provider_versions.get(provider_name) == provider_version
            and gate.provider_configuration_hashes.get(provider_name)
            == provider_configuration_hash
            and gate.provider_annotator_policy_hashes.get(provider_name)
            == annotator_policy_hash
            and decision is not None
            and decision.status == SemanticQualityGateStatus.APPROVED
        )
