from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import SemanticAnnotationType

from .provider import (
    SemanticCandidate,
    SemanticCapability,
    SemanticProviderCapabilities,
    SemanticRequest,
    SemanticTargetKind,
)


HEURISTIC_SEMANTIC_PROVIDER_VERSION = "1"


@dataclass(frozen=True, slots=True)
class _MarkerRule:
    annotation_type: SemanticAnnotationType
    markers: tuple[str, ...]
    confidence: float


_DEFAULT_RULES = (
    _MarkerRule(
        SemanticAnnotationType.DEFINITION,
        ("definition:", "định nghĩa:", "khái niệm:"),
        0.94,
    ),
    _MarkerRule(
        SemanticAnnotationType.EXAMPLE,
        ("example:", "ví dụ:", "for example:", "chẳng hạn:"),
        0.93,
    ),
    _MarkerRule(
        SemanticAnnotationType.WARNING,
        ("warning:", "cảnh báo:"),
        0.96,
    ),
    _MarkerRule(
        SemanticAnnotationType.NOTE,
        ("note:", "ghi chú:", "lưu ý:"),
        0.91,
    ),
    _MarkerRule(
        SemanticAnnotationType.EXERCISE,
        ("exercise:", "bài tập:"),
        0.95,
    ),
    _MarkerRule(
        SemanticAnnotationType.SUMMARY,
        ("summary:", "tóm tắt:"),
        0.95,
    ),
    _MarkerRule(
        SemanticAnnotationType.PROCEDURE,
        ("procedure:", "quy trình:", "steps:", "các bước:"),
        0.92,
    ),
    _MarkerRule(
        SemanticAnnotationType.KEY_POINT,
        ("key point:", "key points:", "điểm chính:", "ý chính:"),
        0.93,
    ),
    _MarkerRule(
        SemanticAnnotationType.LEARNING_OBJECTIVE,
        (
            "learning objective:",
            "learning objectives:",
            "mục tiêu học tập:",
        ),
        0.96,
    ),
    _MarkerRule(
        SemanticAnnotationType.THEOREM,
        ("theorem:", "định lý:"),
        0.97,
    ),
    _MarkerRule(
        SemanticAnnotationType.PROOF,
        ("proof:", "chứng minh:"),
        0.97,
    ),
)


class HeuristicSemanticProvider:
    """High-precision, dependency-free semantic baseline.

    The baseline intentionally recognizes explicit lexical semantic cues only.
    It does not attempt broad topic/entity extraction, which belongs to a model
    provider. This keeps fallback behavior useful without hallucinating meaning.
    """

    name = "heuristic-semantic"
    version = HEURISTIC_SEMANTIC_PROVIDER_VERSION
    capabilities = SemanticProviderCapabilities(
        capabilities=(
            SemanticCapability(
                name="explicit-semantic-roles",
                target_kinds=(SemanticTargetKind.ELEMENT,),
                annotation_types=tuple(rule.annotation_type for rule in _DEFAULT_RULES),
            ),
            SemanticCapability(
                name="topic-group-label",
                target_kinds=(SemanticTargetKind.LOGICAL_UNIT,),
                annotation_types=(SemanticAnnotationType.TOPIC,),
            ),
        ),
        deterministic=True,
    )

    def __init__(self, *, max_value_chars: int = 1024) -> None:
        if max_value_chars < 32 or max_value_chars > 8192:
            raise ValueError("max_value_chars must be between 32 and 8192")
        self._max_value_chars = max_value_chars

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
        text = request.text.strip()

        if request.target_kind == SemanticTargetKind.ELEMENT:
            for rule in _DEFAULT_RULES:
                match = self._match_leading_marker(text, rule.markers)
                if match is None:
                    continue
                marker, payload = match
                value = payload if payload else text
                output.append(
                    SemanticCandidate(
                        target_id=request.target_id,
                        type=rule.annotation_type,
                        value=self._limit(value),
                        confidence=rule.confidence,
                        source=StructureSource.INFERRED,
                        metadata={
                            "heuristic": "leading_semantic_marker",
                            "marker": marker,
                        },
                    )
                )
                break

        if (
            request.target_kind == SemanticTargetKind.LOGICAL_UNIT
            and request.logical_unit_type == "TOPIC_GROUP"
            and request.unit_label is not None
            and request.unit_label.strip()
        ):
            output.append(
                SemanticCandidate(
                    target_id=request.target_id,
                    type=SemanticAnnotationType.TOPIC,
                    value=self._limit(request.unit_label.strip()),
                    confidence=0.90,
                    source=StructureSource.DERIVED,
                    metadata={"heuristic": "topic_group_label"},
                )
            )

        return tuple(output)

    @staticmethod
    def _match_leading_marker(
        text: str,
        markers: tuple[str, ...],
    ) -> tuple[str, str] | None:
        folded = text.casefold()
        for marker in markers:
            marker_folded = marker.casefold()
            if not folded.startswith(marker_folded):
                continue
            payload = text[len(marker) :].strip(" \t\r\n-–—")
            return marker, payload
        return None

    def _limit(self, value: str) -> str:
        value = re.sub(r"[ \t]+", " ", value.strip())
        if len(value) <= self._max_value_chars:
            return value
        return value[: self._max_value_chars].rstrip()
