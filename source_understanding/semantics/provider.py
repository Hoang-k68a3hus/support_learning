from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    Confidence,
    Identifier,
    JsonObject,
    SchemaModel,
    StructureSource,
)
from source_understanding.schemas.document import SemanticAnnotationType


SEMANTIC_PROVIDER_PROTOCOL_VERSION = "1"


class SemanticTargetKind(StrEnum):
    LOGICAL_UNIT = "LOGICAL_UNIT"
    ELEMENT = "ELEMENT"


class SemanticRequest(SchemaModel):
    """Source-grounded text view passed to a semantic provider.

    A request never changes canonical source state. Providers may infer semantic
    labels from this view, but those labels remain semantic enrichment.
    """

    target_id: Identifier
    target_kind: SemanticTargetKind
    text: str = Field(min_length=1, max_length=32768)
    language: str | None = Field(default=None, min_length=2, max_length=64)
    element_ids: tuple[Identifier, ...] = Field(min_length=1)
    logical_unit_type: str | None = Field(default=None, max_length=128)
    unit_label: str | None = Field(default=None, max_length=2048)
    context_labels: tuple[str, ...] = Field(default_factory=tuple)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_request(self) -> "SemanticRequest":
        if not self.text.strip():
            raise ValueError("semantic request text must not be blank")
        if len(self.element_ids) != len(set(self.element_ids)):
            raise ValueError("semantic request element_ids must be unique")
        return self


class SemanticCandidate(SchemaModel):
    """Provider output before canonical SemanticAnnotation construction."""

    target_id: Identifier
    type: SemanticAnnotationType
    value: str = Field(min_length=1, max_length=8192)
    confidence: Confidence
    source: StructureSource = StructureSource.INFERRED
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_candidate(self) -> "SemanticCandidate":
        if self.source == StructureSource.EXPLICIT:
            raise ValueError(
                "semantic providers cannot promote inferred output to EXPLICIT source fact"
            )
        if not self.value.strip():
            raise ValueError("semantic candidate value must not be blank")
        return self


@runtime_checkable
class SemanticProvider(Protocol):
    """Synchronous provider contract for optional semantic understanding."""

    name: str
    version: str

    def annotate(
        self,
        requests: tuple[SemanticRequest, ...],
    ) -> Iterable[SemanticCandidate]: ...
