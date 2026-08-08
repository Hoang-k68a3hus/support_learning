from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
import re
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


SEMANTIC_PROVIDER_PROTOCOL_VERSION = "2"


class SemanticTargetKind(StrEnum):
    LOGICAL_UNIT = "LOGICAL_UNIT"
    ELEMENT = "ELEMENT"


class SemanticOntologyLabel(SchemaModel):
    """Provider-owned fine-grained label under a stable namespace.

    Core schemas keep coarse annotation types stable. Specialized providers can
    refine them with namespaced labels such as ``ner:PERSON`` or
    ``temporal:EVENT`` without expanding the global enum.
    """

    namespace: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    label: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    version: str | None = Field(default=None, min_length=1, max_length=128)

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.label}"


class SemanticCapability(SchemaModel):
    """One independently routable semantic capability advertised by a provider."""

    name: str = Field(min_length=1, max_length=128)
    target_kinds: tuple[SemanticTargetKind, ...] = Field(min_length=1)
    annotation_types: tuple[SemanticAnnotationType, ...] = Field(min_length=1)
    ontology_namespaces: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_capability(self) -> "SemanticCapability":
        if len(self.target_kinds) != len(set(self.target_kinds)):
            raise ValueError("semantic capability target_kinds must be unique")
        if len(self.annotation_types) != len(set(self.annotation_types)):
            raise ValueError("semantic capability annotation_types must be unique")
        if len(self.ontology_namespaces) != len(set(self.ontology_namespaces)):
            raise ValueError("semantic capability ontology_namespaces must be unique")
        for namespace in self.ontology_namespaces:
            if not namespace or namespace.strip() != namespace:
                raise ValueError("ontology namespaces must be non-blank and trimmed")
            if len(namespace) > 128:
                raise ValueError("ontology namespace must be <= 128 chars")
            if re.fullmatch(r"[A-Za-z0-9_.-]+", namespace) is None:
                raise ValueError(
                    "ontology namespace must match [A-Za-z0-9_.-]+"
                )
        return self


class SemanticProviderCapabilities(SchemaModel):
    """Capability declaration used for routing and provider-output validation."""

    protocol_version: str = SEMANTIC_PROVIDER_PROTOCOL_VERSION
    capabilities: tuple[SemanticCapability, ...] = Field(min_length=1)
    deterministic: bool | None = None

    @model_validator(mode="after")
    def validate_capabilities(self) -> "SemanticProviderCapabilities":
        if self.protocol_version != SEMANTIC_PROVIDER_PROTOCOL_VERSION:
            raise ValueError(
                "unsupported semantic provider protocol_version: "
                f"{self.protocol_version!r} != {SEMANTIC_PROVIDER_PROTOCOL_VERSION!r}"
            )
        names = [capability.name for capability in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("semantic capability names must be unique")
        return self

    def supports_target_kind(self, target_kind: SemanticTargetKind) -> bool:
        return any(target_kind in capability.target_kinds for capability in self.capabilities)

    def supports_candidate(
        self,
        target_kind: SemanticTargetKind,
        annotation_type: SemanticAnnotationType,
        ontology: SemanticOntologyLabel | None,
    ) -> bool:
        for capability in self.capabilities:
            if target_kind not in capability.target_kinds:
                continue
            if annotation_type not in capability.annotation_types:
                continue
            if ontology is None:
                return True
            if ontology.namespace in capability.ontology_namespaces:
                return True
        return False


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
    ontology: SemanticOntologyLabel | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_candidate(self) -> "SemanticCandidate":
        if self.source == StructureSource.EXPLICIT:
            raise ValueError(
                "semantic providers cannot promote inferred output to EXPLICIT source fact"
            )
        if not self.value.strip():
            raise ValueError("semantic candidate value must not be blank")
        if self.type == SemanticAnnotationType.CUSTOM and self.ontology is None:
            raise ValueError("CUSTOM semantic candidates require a namespaced ontology label")
        return self


@runtime_checkable
class SemanticProvider(Protocol):
    """Synchronous capability-declared provider for optional semantic understanding."""

    name: str
    version: str
    capabilities: SemanticProviderCapabilities

    def annotate(
        self,
        requests: tuple[SemanticRequest, ...],
    ) -> Iterable[SemanticCandidate]: ...
