from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    Confidence,
    ContentHash,
    SchemaModel,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticEvidenceSpan,
    SemanticPayloadMode,
    semantic_extractive_value_key,
    semantic_payload_mode_for_type,
)
from source_understanding.semantics.provider import SemanticOntologyLabel


ANNOTATION_DECISION_HASH_VERSION = "1"


class AnnotationDecisionState(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNDECIDED = "UNDECIDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AdjudicationConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CompetingLabelDecision(SchemaModel):
    annotation_type: SemanticAnnotationType
    confidence: AdjudicationConfidence
    rationale: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_rationale(self) -> "CompetingLabelDecision":
        if self.rationale is not None and not self.rationale.strip():
            raise ValueError("competing-label rationale must not be blank")
        return self


def _evidence_keys(
    evidence: tuple[SemanticEvidenceSpan, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.element_id,
            item.text_view,
            item.start_char,
            item.end_char,
            item.quoted_text,
        )
        for item in evidence
    )


def _validate_extractive_payload(
    *,
    annotation_type: SemanticAnnotationType,
    value: str | None,
    evidence: tuple[SemanticEvidenceSpan, ...],
    owner: str,
) -> None:
    if semantic_payload_mode_for_type(annotation_type) != SemanticPayloadMode.EXTRACTIVE:
        return
    if value is None or not value.strip():
        raise ValueError(f"positive extractive {owner} requires a value")
    if not evidence:
        raise ValueError(f"positive extractive {owner} requires source evidence")
    value_key = semantic_extractive_value_key(value)
    evidence_values = {
        semantic_extractive_value_key(item.quoted_text) for item in evidence
    }
    if value_key not in evidence_values:
        raise ValueError(f"extractive {owner} value must match an evidence quote")


class AnnotationDecision(SchemaModel):
    annotation_type: SemanticAnnotationType
    state: AnnotationDecisionState
    value: str | None = Field(default=None, min_length=1, max_length=8192)
    evidence: tuple[SemanticEvidenceSpan, ...] = Field(default_factory=tuple)
    ontology: SemanticOntologyLabel | None = None
    rule_keys: tuple[str, ...] = Field(default_factory=tuple)
    rationale: str | None = Field(default=None, min_length=1, max_length=8192)
    confidence: AdjudicationConfidence
    competing_labels: tuple[CompetingLabelDecision, ...] = Field(
        default_factory=tuple
    )
    negative_reason: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_decision(self) -> "AnnotationDecision":
        if self.value is not None and not self.value.strip():
            raise ValueError("annotation decision value must not be blank")
        if self.rationale is not None and not self.rationale.strip():
            raise ValueError("annotation decision rationale must not be blank")
        if self.negative_reason is not None and not self.negative_reason.strip():
            raise ValueError("annotation decision negative_reason must not be blank")
        if len(self.rule_keys) != len(set(self.rule_keys)):
            raise ValueError("annotation decision rule_keys must be unique")
        if any(not key.strip() or key.strip() != key for key in self.rule_keys):
            raise ValueError("annotation decision rule_keys must be non-blank and trimmed")
        evidence_keys = _evidence_keys(self.evidence)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("annotation decision evidence spans must be unique")
        competing_types = tuple(item.annotation_type for item in self.competing_labels)
        if len(competing_types) != len(set(competing_types)):
            raise ValueError("annotation decision competing labels must be unique")
        if self.annotation_type in competing_types:
            raise ValueError("annotation decision cannot compete with its own label")

        if self.state == AnnotationDecisionState.POSITIVE:
            if self.negative_reason is not None:
                raise ValueError("POSITIVE decisions cannot carry negative_reason")
            if (
                semantic_payload_mode_for_type(self.annotation_type)
                == SemanticPayloadMode.LABEL_ONLY
                and self.value is not None
                and self.rationale is None
            ):
                raise ValueError(
                    "positive LABEL_ONLY decisions with a value require a "
                    "task-specific rationale"
                )
            if (
                self.annotation_type == SemanticAnnotationType.CUSTOM
                and self.ontology is None
            ):
                raise ValueError("positive CUSTOM decisions require ontology")
            _validate_extractive_payload(
                annotation_type=self.annotation_type,
                value=self.value,
                evidence=self.evidence,
                owner="decision",
            )
        elif self.state == AnnotationDecisionState.NEGATIVE:
            if self.negative_reason is None:
                raise ValueError("NEGATIVE decisions require negative_reason")
            if self.value is not None or self.evidence or self.ontology is not None:
                raise ValueError(
                    "NEGATIVE decisions cannot carry positive value, evidence, or ontology"
                )
        elif self.state == AnnotationDecisionState.UNDECIDED:
            if self.rationale is None:
                raise ValueError("UNDECIDED decisions require an ambiguity rationale")
            if self.negative_reason is not None:
                raise ValueError("UNDECIDED decisions cannot carry negative_reason")
            if self.value is not None or self.evidence or self.ontology is not None:
                raise ValueError(
                    "UNDECIDED decisions cannot carry final value, evidence, or ontology; "
                    "use an AnnotationSuggestion for candidates"
                )
        else:
            if (
                self.value is not None
                or self.evidence
                or self.ontology is not None
                or self.negative_reason is not None
            ):
                raise ValueError(
                    "NOT_APPLICABLE decisions cannot carry annotation payload"
                )
        return self


class AnnotationSuggestion(SchemaModel):
    agent: str = Field(min_length=1, max_length=256)
    agent_version: str = Field(min_length=1, max_length=128)
    annotation_type: SemanticAnnotationType
    value: str | None = Field(default=None, min_length=1, max_length=8192)
    evidence: tuple[SemanticEvidenceSpan, ...] = Field(default_factory=tuple)
    ontology: SemanticOntologyLabel | None = None
    score: Confidence | None = None
    score_method: SemanticConfidenceMethod
    calibration_version: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_suggestion(self) -> "AnnotationSuggestion":
        if not self.agent.strip() or self.agent.strip() != self.agent:
            raise ValueError("annotation suggestion agent must be non-blank and trimmed")
        if not self.agent_version.strip() or self.agent_version.strip() != self.agent_version:
            raise ValueError(
                "annotation suggestion agent_version must be non-blank and trimmed"
            )
        evidence_keys = _evidence_keys(self.evidence)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("annotation suggestion evidence spans must be unique")
        if (
            self.annotation_type == SemanticAnnotationType.CUSTOM
            and self.ontology is None
        ):
            raise ValueError("CUSTOM suggestions require ontology")
        _validate_extractive_payload(
            annotation_type=self.annotation_type,
            value=self.value,
            evidence=self.evidence,
            owner="suggestion",
        )
        if self.score is None and self.score_method != SemanticConfidenceMethod.UNCALIBRATED:
            raise ValueError(
                "scored suggestion methods require a numeric score"
            )
        if (
            self.score_method == SemanticConfidenceMethod.CALIBRATED_PROBABILITY
            and self.calibration_version is None
        ):
            raise ValueError(
                "calibrated suggestions require calibration_version"
            )
        if (
            self.score_method != SemanticConfidenceMethod.CALIBRATED_PROBABILITY
            and self.calibration_version is not None
        ):
            raise ValueError(
                "calibration_version is only valid for calibrated suggestions"
            )
        return self


def annotation_decisions_hash(
    decisions: tuple[AnnotationDecision, ...],
) -> ContentHash:
    payload = {
        "hash_version": ANNOTATION_DECISION_HASH_VERSION,
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
