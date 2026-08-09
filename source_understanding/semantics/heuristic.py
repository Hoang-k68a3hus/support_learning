from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from source_understanding.schemas.context import Confidence, SchemaModel, StructureSource
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticEvidenceSpan,
)

from .provider import (
    SemanticCandidate,
    SemanticCapability,
    SemanticProviderCapabilities,
    SemanticRequest,
    SemanticTargetKind,
)


HEURISTIC_SEMANTIC_PROVIDER_VERSION = "4"
HEURISTIC_SEMANTIC_POLICY_VERSION = "1"


class LanguageRoutingMode(StrEnum):
    ALL_ENABLED = "ALL_ENABLED"
    REQUEST_PRIMARY = "REQUEST_PRIMARY"


class SemanticMarkerRule(SchemaModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    annotation_type: SemanticAnnotationType
    languages: tuple[str, ...] = Field(min_length=1)
    markers: tuple[str, ...] = Field(min_length=1)
    confidence: Confidence

    @field_validator("languages", mode="before")
    @classmethod
    def normalize_languages(cls, value: object) -> object:
        if isinstance(value, str) or not isinstance(value, Iterable):
            raise ValueError("semantic marker rule languages must be a sequence")
        return tuple(str(language).strip().casefold() for language in value)

    @field_validator("markers", mode="before")
    @classmethod
    def normalize_markers(cls, value: object) -> object:
        if isinstance(value, str) or not isinstance(value, Iterable):
            raise ValueError("semantic marker rule markers must be a sequence")
        markers = tuple(value)
        if any(not isinstance(marker, str) for marker in markers):
            raise ValueError("semantic marker rules must contain only strings")
        return tuple(marker.strip() for marker in markers)

    @model_validator(mode="after")
    def validate_rule(self) -> "SemanticMarkerRule":
        if self.annotation_type == SemanticAnnotationType.CUSTOM:
            raise ValueError("heuristic marker rules cannot emit CUSTOM annotations")
        if any(re.fullmatch(r"[a-z]{2,8}", language) is None for language in self.languages):
            raise ValueError("rule languages must be lowercase primary language subtags")
        if len(self.languages) != len(set(self.languages)):
            raise ValueError("rule languages must be unique")
        if any(not marker or len(marker) > 256 for marker in self.markers):
            raise ValueError("rule markers must be non-blank and <= 256 chars")
        folded = [marker.casefold() for marker in self.markers]
        if len(folded) != len(set(folded)):
            raise ValueError("rule markers must be unique case-insensitively")
        return self


class HeuristicSemanticPolicy(SchemaModel):
    version: str = HEURISTIC_SEMANTIC_POLICY_VERSION
    rules: tuple[SemanticMarkerRule, ...] = Field(
        default_factory=lambda: _default_rules()
    )
    enabled_languages: tuple[str, ...] = ("en", "vi")
    language_routing: LanguageRoutingMode = LanguageRoutingMode.ALL_ENABLED
    fallback_to_all_enabled_on_unknown_language: bool = False
    include_topic_group_labels: bool = True
    max_value_chars: int = Field(default=1024, ge=32, le=8192)

    @field_validator("enabled_languages", mode="before")
    @classmethod
    def normalize_enabled_languages(cls, value: object) -> object:
        if isinstance(value, str) or not isinstance(value, Iterable):
            raise ValueError("enabled_languages must be a sequence")
        return tuple(str(language).strip().casefold() for language in value)

    @model_validator(mode="after")
    def validate_policy(self) -> "HeuristicSemanticPolicy":
        if not self.rules:
            raise ValueError("heuristic semantic policy requires at least one rule")
        if not self.enabled_languages:
            raise ValueError("enabled_languages must not be empty")
        if len(self.enabled_languages) != len(set(self.enabled_languages)):
            raise ValueError("enabled_languages must be unique")
        if any(
            re.fullmatch(r"[a-z]{2,8}", language) is None
            for language in self.enabled_languages
        ):
            raise ValueError(
                "enabled_languages must contain lowercase primary language subtags"
            )
        rule_ids = [rule.id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("semantic marker rule ids must be unique")
        enabled = set(self.enabled_languages)
        if not any(enabled.intersection(rule.languages) for rule in self.rules):
            raise ValueError("no semantic marker rule supports an enabled language")
        owners: dict[tuple[str, str], str] = {}
        for rule in self.rules:
            for language in rule.languages:
                if language not in enabled:
                    continue
                for marker in rule.markers:
                    key = (language, marker.casefold())
                    previous = owners.get(key)
                    if previous is not None:
                        raise ValueError(
                            f"semantic marker {marker!r} for {language!r} is ambiguous "
                            f"between rules {previous!r} and {rule.id!r}"
                        )
                    owners[key] = rule.id
        return self


def _default_rules() -> tuple[SemanticMarkerRule, ...]:
    rules: list[SemanticMarkerRule] = []

    def add(
        rule_id: str,
        annotation_type: SemanticAnnotationType,
        english: tuple[str, ...],
        vietnamese: tuple[str, ...],
        confidence: float,
    ) -> None:
        rules.extend(
            (
                SemanticMarkerRule(
                    id=f"{rule_id}-en",
                    annotation_type=annotation_type,
                    languages=("en",),
                    markers=english,
                    confidence=confidence,
                ),
                SemanticMarkerRule(
                    id=f"{rule_id}-vi",
                    annotation_type=annotation_type,
                    languages=("vi",),
                    markers=vietnamese,
                    confidence=confidence,
                ),
            )
        )

    add(
        "definition",
        SemanticAnnotationType.DEFINITION,
        ("definition:",),
        ("định nghĩa:", "khái niệm:"),
        0.94,
    )
    add(
        "example",
        SemanticAnnotationType.EXAMPLE,
        ("example:", "for example:"),
        ("ví dụ:", "chẳng hạn:"),
        0.93,
    )
    add("warning", SemanticAnnotationType.WARNING, ("warning:",), ("cảnh báo:",), 0.96)
    add("note", SemanticAnnotationType.NOTE, ("note:",), ("ghi chú:", "lưu ý:"), 0.91)
    add("exercise", SemanticAnnotationType.EXERCISE, ("exercise:",), ("bài tập:",), 0.95)
    add("summary", SemanticAnnotationType.SUMMARY, ("summary:",), ("tóm tắt:",), 0.95)
    add(
        "procedure",
        SemanticAnnotationType.PROCEDURE,
        ("procedure:", "steps:"),
        ("quy trình:", "các bước:"),
        0.92,
    )
    add(
        "key-point",
        SemanticAnnotationType.KEY_POINT,
        ("key point:", "key points:"),
        ("điểm chính:", "ý chính:"),
        0.93,
    )
    add(
        "learning-objective",
        SemanticAnnotationType.LEARNING_OBJECTIVE,
        ("learning objective:", "learning objectives:"),
        ("mục tiêu học tập:",),
        0.96,
    )
    add("theorem", SemanticAnnotationType.THEOREM, ("theorem:",), ("định lý:",), 0.97)
    add("proof", SemanticAnnotationType.PROOF, ("proof:",), ("chứng minh:",), 0.97)
    return tuple(rules)


class HeuristicSemanticProvider:
    """High-precision multilingual baseline using explicit leading markers only."""

    name = "heuristic-semantic"
    version = HEURISTIC_SEMANTIC_PROVIDER_VERSION

    def __init__(
        self,
        *,
        max_value_chars: int | None = None,
        languages: Sequence[str] | None = None,
        policy: HeuristicSemanticPolicy | None = None,
    ) -> None:
        if policy is not None and (max_value_chars is not None or languages is not None):
            raise ValueError(
                "provide heuristic policy or legacy max_value_chars/languages, not both"
            )
        if policy is None:
            values: dict[str, object] = {}
            if max_value_chars is not None:
                values["max_value_chars"] = max_value_chars
            if languages is not None:
                values["enabled_languages"] = tuple(languages)
            policy = HeuristicSemanticPolicy(**values)
        self._policy = policy
        enabled = set(policy.enabled_languages)
        annotation_types = tuple(
            dict.fromkeys(
                rule.annotation_type
                for rule in policy.rules
                if enabled.intersection(rule.languages)
            )
        )
        capabilities: list[SemanticCapability] = [
            SemanticCapability(
                name="explicit-semantic-roles",
                target_kinds=(SemanticTargetKind.ELEMENT,),
                annotation_types=annotation_types,
            )
        ]
        if policy.include_topic_group_labels:
            capabilities.append(
                SemanticCapability(
                    name="topic-group-label",
                    target_kinds=(SemanticTargetKind.LOGICAL_UNIT,),
                    annotation_types=(SemanticAnnotationType.TOPIC,),
                )
            )
        self.capabilities = SemanticProviderCapabilities(
            capabilities=tuple(capabilities),
            deterministic=True,
        )
        self.configuration = policy.model_dump(mode="json")

    def annotate(
        self,
        requests: tuple[SemanticRequest, ...],
    ) -> Iterable[SemanticCandidate]:
        candidates: list[SemanticCandidate] = []
        for request in requests:
            candidates.extend(self._annotate_request(request))
        return tuple(candidates)

    def _annotate_request(self, request: SemanticRequest) -> tuple[SemanticCandidate, ...]:
        output: list[SemanticCandidate] = []

        if request.target_kind == SemanticTargetKind.ELEMENT:
            segment = request.target_segments[0]
            text = segment.text
            request_languages = self._request_languages(request.language)
            for rule in self._policy.rules:
                matched_languages = tuple(
                    language
                    for language in rule.languages
                    if language in request_languages
                )
                if not matched_languages:
                    continue
                match = self._match_leading_marker(text, rule.markers)
                if match is None:
                    continue
                marker, payload, evidence_start, evidence_end = match
                value = payload if payload else text
                limited_value, limit_metadata = self._limit(value)
                output.append(
                    SemanticCandidate(
                        target_id=request.target_id,
                        type=rule.annotation_type,
                        value=limited_value,
                        confidence=rule.confidence,
                        confidence_method=SemanticConfidenceMethod.RULE_PRIOR,
                        source=StructureSource.INFERRED,
                        capability_name="explicit-semantic-roles",
                        evidence=(
                            SemanticEvidenceSpan(
                                element_id=segment.element_id,
                                start_char=segment.element_start + evidence_start,
                                end_char=segment.element_start + evidence_end,
                                quoted_text=text[evidence_start:evidence_end],
                                text_view=segment.text_view,
                            ),
                        ),
                        metadata={
                            "heuristic": "leading_semantic_marker",
                            "heuristic_policy_version": self._policy.version,
                            "rule_id": rule.id,
                            "marker": marker,
                            "rule_languages": list(matched_languages),
                            **limit_metadata,
                        },
                    )
                )
                break

        if (
            self._policy.include_topic_group_labels
            and request.target_kind == SemanticTargetKind.LOGICAL_UNIT
            and request.logical_unit_type == "TOPIC_GROUP"
            and request.unit_label is not None
            and request.unit_label.strip()
        ):
            limited_value, limit_metadata = self._limit(request.unit_label.strip())
            output.append(
                SemanticCandidate(
                    target_id=request.target_id,
                    type=SemanticAnnotationType.TOPIC,
                    value=limited_value,
                    confidence=0.90,
                    confidence_method=SemanticConfidenceMethod.RULE_PRIOR,
                    source=StructureSource.DERIVED,
                    capability_name="topic-group-label",
                    metadata={
                        "heuristic": "topic_group_label",
                        "heuristic_policy_version": self._policy.version,
                        **limit_metadata,
                    },
                )
            )

        return tuple(output)

    def _request_languages(self, language: str | None) -> frozenset[str]:
        enabled = frozenset(self._policy.enabled_languages)
        if self._policy.language_routing == LanguageRoutingMode.ALL_ENABLED:
            return enabled
        primary = None
        if language is not None and language.strip():
            primary = re.split(r"[-_]", language.strip().casefold(), maxsplit=1)[0]
        if primary in enabled:
            return frozenset((primary,))
        if self._policy.fallback_to_all_enabled_on_unknown_language:
            return enabled
        return frozenset()

    @staticmethod
    def _match_leading_marker(
        text: str,
        markers: tuple[str, ...],
    ) -> tuple[str, str, int, int] | None:
        content_start = len(text) - len(text.lstrip())
        content_end = len(text.rstrip())
        content = text[content_start:content_end]
        folded = content.casefold()
        for marker in markers:
            marker_folded = marker.casefold()
            if not folded.startswith(marker_folded):
                continue
            evidence_start = content_start + len(marker)
            evidence_end = content_end
            strip_chars = " \t\r\n-–—"
            while evidence_start < evidence_end and text[evidence_start] in strip_chars:
                evidence_start += 1
            while evidence_end > evidence_start and text[evidence_end - 1] in strip_chars:
                evidence_end -= 1
            if evidence_start == evidence_end:
                evidence_start = content_start
                evidence_end = content_end
            return (
                marker,
                text[evidence_start:evidence_end],
                evidence_start,
                evidence_end,
            )
        return None

    def _limit(self, value: str) -> tuple[str, dict[str, object]]:
        original = value.strip()
        compacted = re.sub(r"[ \t]+", " ", original)
        metadata: dict[str, object] = {}
        if compacted != original:
            metadata["value_whitespace_compacted"] = True
        if len(compacted) <= self._policy.max_value_chars:
            return compacted, metadata
        metadata.update(
            {
                "value_truncated": True,
                "original_char_count": len(compacted),
                "max_value_chars": self._policy.max_value_chars,
            }
        )
        return compacted[: self._policy.max_value_chars].rstrip(), metadata
