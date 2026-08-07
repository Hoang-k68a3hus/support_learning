from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .context import (
    Confidence,
    ContextNode,
    Identifier,
    SchemaModel,
    StructureMode,
    StructureSource,
)
from .element import Element, SourceLocation
from .logical_unit import LogicalUnit
from .relation import Relation


class SemanticAnnotationType(StrEnum):
    TOPIC = "TOPIC"
    CONCEPT = "CONCEPT"
    ENTITY = "ENTITY"
    KEYWORD = "KEYWORD"
    DEFINITION = "DEFINITION"
    EXAMPLE = "EXAMPLE"
    THEOREM = "THEOREM"
    PROOF = "PROOF"
    WARNING = "WARNING"
    NOTE = "NOTE"
    EXERCISE = "EXERCISE"
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    SUMMARY = "SUMMARY"
    PROCEDURE = "PROCEDURE"
    KEY_POINT = "KEY_POINT"
    LEARNING_OBJECTIVE = "LEARNING_OBJECTIVE"
    CUSTOM = "CUSTOM"


class DocumentMetadata(SchemaModel):
    title: str | None = Field(default=None, max_length=4096)
    language: str | None = Field(default=None, min_length=2, max_length=64)
    source_name: str | None = Field(default=None, max_length=4096)
    authors: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    attributes: dict[str, object] = Field(default_factory=dict)


class DocumentStructure(SchemaModel):
    mode: StructureMode = StructureMode.FLAT
    confidence: Confidence = 0.0
    signals: dict[str, Confidence] = Field(default_factory=dict)


class DocumentQuality(SchemaModel):
    text_quality: Confidence | None = None
    order_quality: Confidence | None = None
    structure_quality: Confidence | None = None
    duplicate_ratio: Confidence | None = None
    garbage_ratio: Confidence | None = None
    overall: Confidence | None = None
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class Asset(SchemaModel):
    id: Identifier
    type: str = Field(min_length=1, max_length=128)
    uri: str | None = Field(default=None, max_length=8192)
    location: SourceLocation | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SubDocument(SchemaModel):
    id: Identifier
    element_ids: list[Identifier] = Field(min_length=1)
    label: str | None = Field(default=None, max_length=2048)
    source_hint: str | None = Field(default=None, max_length=4096)
    confidence: Confidence = 1.0
    source: StructureSource = StructureSource.EXPLICIT
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_elements(self) -> SubDocument:
        if len(self.element_ids) != len(set(self.element_ids)):
            raise ValueError("subdocument element_ids must be unique")
        return self


class SemanticAnnotation(SchemaModel):
    id: Identifier
    target_id: Identifier
    type: SemanticAnnotationType
    value: str = Field(min_length=1, max_length=8192)
    source: StructureSource = StructureSource.INFERRED
    confidence: Confidence = 1.0
    model_version: str | None = Field(default=None, max_length=128)
    metadata: dict[str, object] = Field(default_factory=dict)


class CanonicalDocument(SchemaModel):
    """Loss-minimizing canonical representation of a source.

    Retrieval units intentionally do not live here. They are rebuildable,
    task-facing projections created from this canonical document.
    """

    schema_version: str = Field(default="1.0", min_length=1, max_length=64)
    document_id: Identifier
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    structure: DocumentStructure = Field(default_factory=DocumentStructure)
    elements: list[Element] = Field(default_factory=list)
    logical_units: list[LogicalUnit] = Field(default_factory=list)
    context_nodes: list[ContextNode] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    semantic_annotations: list[SemanticAnnotation] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    subdocuments: list[SubDocument] = Field(default_factory=list)
    quality: DocumentQuality = Field(default_factory=DocumentQuality)

    @model_validator(mode="after")
    def validate_integrity(self) -> CanonicalDocument:
        element_ids = self._unique_ids("elements", self.elements)
        logical_ids = self._unique_ids("logical_units", self.logical_units)
        context_ids = self._unique_ids("context_nodes", self.context_nodes)
        asset_ids = self._unique_ids("assets", self.assets)
        subdocument_ids = self._unique_ids("subdocuments", self.subdocuments)
        annotation_ids = self._unique_ids(
            "semantic_annotations", self.semantic_annotations
        )
        relation_ids = self._unique_ids("relations", self.relations)

        namespaces = {
            "elements": element_ids,
            "logical_units": logical_ids,
            "context_nodes": context_ids,
            "assets": asset_ids,
            "subdocuments": subdocument_ids,
            "semantic_annotations": annotation_ids,
            "relations": relation_ids,
        }
        names = list(namespaces)
        for index, left_name in enumerate(names):
            for right_name in names[index + 1 :]:
                collisions = namespaces[left_name] & namespaces[right_name]
                if collisions:
                    raise ValueError(
                        f"id collision between {left_name} and {right_name}: "
                        f"{sorted(collisions)}"
                    )

        for unit in self.logical_units:
            self._require_subset(
                f"logical unit {unit.id} element_ids", unit.element_ids, element_ids
            )
            self._require_subset(
                f"logical unit {unit.id} context_node_ids",
                unit.context_node_ids,
                context_ids,
            )

        for subdoc in self.subdocuments:
            self._require_subset(
                f"subdocument {subdoc.id} element_ids",
                subdoc.element_ids,
                element_ids,
            )

        all_relation_targets = element_ids | logical_ids | context_ids | subdocument_ids
        for relation in self.relations:
            if relation.source_id not in all_relation_targets:
                raise ValueError(
                    f"relation {relation.id} has unknown source_id {relation.source_id!r}"
                )
            if relation.target_id not in all_relation_targets:
                raise ValueError(
                    f"relation {relation.id} has unknown target_id {relation.target_id!r}"
                )

        annotation_targets = all_relation_targets | asset_ids
        for annotation in self.semantic_annotations:
            if annotation.target_id not in annotation_targets:
                raise ValueError(
                    f"semantic annotation {annotation.id} targets unknown id "
                    f"{annotation.target_id!r}"
                )

        self._validate_context_tree(context_ids)
        return self

    @staticmethod
    def _unique_ids(name: str, items: list[object]) -> set[str]:
        ids = [getattr(item, "id") for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{name} contains duplicate ids")
        return set(ids)

    @staticmethod
    def _require_subset(name: str, refs: list[str], valid: set[str]) -> None:
        missing = set(refs) - valid
        if missing:
            raise ValueError(f"{name} contains unknown ids: {sorted(missing)}")

    def _validate_context_tree(self, context_ids: set[str]) -> None:
        parents: dict[str, str | None] = {}
        for node in self.context_nodes:
            if node.parent_id is not None and node.parent_id not in context_ids:
                raise ValueError(
                    f"context node {node.id} has unknown parent_id {node.parent_id!r}"
                )
            parents[node.id] = node.parent_id

        for node_id in parents:
            seen: set[str] = set()
            current: str | None = node_id
            while current is not None:
                if current in seen:
                    raise ValueError(f"context hierarchy contains cycle at {current!r}")
                seen.add(current)
                current = parents.get(current)
