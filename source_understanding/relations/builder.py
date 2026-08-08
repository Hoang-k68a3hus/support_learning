from __future__ import annotations

import hashlib
from collections.abc import Sequence

from pydantic import Field, model_validator

from source_understanding.schemas.context import Confidence, Identifier, SchemaModel, StructureSource
from source_understanding.schemas.document import SubDocument
from source_understanding.schemas.element import Element
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.schemas.relation import Relation, RelationLayer, RelationType


RELATION_BUILDER_VERSION = "1"


class RelationBuildError(ValueError):
    """Structural relations cannot be built from inconsistent canonical objects."""


class RelationBuildPolicy(SchemaModel):
    version: str = RELATION_BUILDER_VERSION
    include_element_next: bool = True
    include_element_membership: bool = True
    include_question_answer: bool = True
    include_subdocument_membership: bool = True
    deterministic_confidence: Confidence = 1.0


class RelationBuildResult(SchemaModel):
    version: str = RELATION_BUILDER_VERSION
    element_count: int = Field(ge=1)
    logical_unit_count: int = Field(ge=0)
    subdocument_count: int = Field(ge=0)
    policy: RelationBuildPolicy
    relations: tuple[Relation, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_relations(self) -> "RelationBuildResult":
        ids = [relation.id for relation in self.relations]
        if len(ids) != len(set(ids)):
            raise ValueError("relation builder produced duplicate relation ids")
        triples = [
            (relation.type, relation.source_id, relation.target_id)
            for relation in self.relations
        ]
        if len(triples) != len(set(triples)):
            raise ValueError("relation builder produced duplicate relation triples")
        return self


class StructuralRelationBuilder:
    """Build only structural relations directly supported by canonical structure."""

    version: str = RELATION_BUILDER_VERSION

    def __init__(self, policy: RelationBuildPolicy | None = None) -> None:
        self._policy = policy if policy is not None else RelationBuildPolicy()

    def build(
        self,
        elements: Sequence[Element],
        logical_units: Sequence[LogicalUnit],
        subdocuments: Sequence[SubDocument] = (),
    ) -> RelationBuildResult:
        element_snapshot = tuple(elements)
        unit_snapshot = tuple(logical_units)
        subdoc_snapshot = tuple(subdocuments)
        self._validate_inputs(element_snapshot, unit_snapshot, subdoc_snapshot)

        relations: list[Relation] = []

        if self._policy.include_element_next:
            for left, right in zip(element_snapshot, element_snapshot[1:]):
                relations.append(
                    self._make_relation(
                        RelationType.NEXT,
                        left.id,
                        right.id,
                        source=StructureSource.DERIVED,
                        confidence=self._policy.deterministic_confidence,
                        metadata={
                            "basis": "canonical_element_order",
                            "from_order": left.order,
                            "to_order": right.order,
                        },
                    )
                )

        if self._policy.include_element_membership:
            for unit in unit_snapshot:
                for element_id in unit.element_ids:
                    relations.append(
                        self._make_relation(
                            RelationType.PART_OF,
                            element_id,
                            unit.id,
                            source=StructureSource.DERIVED,
                            confidence=self._policy.deterministic_confidence,
                            metadata={
                                "membership": "logical_unit",
                                "logical_unit_type": unit.type.value,
                            },
                        )
                    )

        if self._policy.include_question_answer:
            for unit in unit_snapshot:
                if unit.type != LogicalUnitType.QA_PAIR:
                    continue
                if len(unit.element_ids) != 2:
                    raise RelationBuildError(
                        f"QA_PAIR logical unit {unit.id!r} must contain exactly two elements"
                    )
                question_id, answer_id = unit.element_ids
                relations.append(
                    self._make_relation(
                        RelationType.QUESTION_ANSWER,
                        question_id,
                        answer_id,
                        source=unit.source,
                        confidence=unit.confidence,
                        metadata={"logical_unit_id": unit.id},
                    )
                )

        if self._policy.include_subdocument_membership and subdoc_snapshot:
            for unit in unit_snapshot:
                containing = [
                    subdoc
                    for subdoc in subdoc_snapshot
                    if set(unit.element_ids).issubset(subdoc.element_ids)
                ]
                intersecting = [
                    subdoc
                    for subdoc in subdoc_snapshot
                    if set(unit.element_ids).intersection(subdoc.element_ids)
                ]
                if intersecting and len(containing) != 1:
                    raise RelationBuildError(
                        f"logical unit {unit.id!r} crosses or ambiguously intersects "
                        "subdocument boundaries"
                    )
                if not containing:
                    continue
                subdoc = containing[0]
                relations.append(
                    self._make_relation(
                        RelationType.PART_OF,
                        unit.id,
                        subdoc.id,
                        source=StructureSource.DERIVED,
                        confidence=min(unit.confidence, subdoc.confidence),
                        metadata={"membership": "subdocument"},
                    )
                )

        return RelationBuildResult(
            element_count=len(element_snapshot),
            logical_unit_count=len(unit_snapshot),
            subdocument_count=len(subdoc_snapshot),
            policy=self._policy,
            relations=tuple(relations),
        )

    @staticmethod
    def _relation_id(
        relation_type: RelationType,
        source_id: str,
        target_id: str,
    ) -> str:
        identity = f"{relation_type.value}|{source_id}|{target_id}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return f"rel_{digest}"

    def _make_relation(
        self,
        relation_type: RelationType,
        source_id: str,
        target_id: str,
        *,
        source: StructureSource,
        confidence: float,
        metadata: dict[str, object],
    ) -> Relation:
        return Relation(
            id=self._relation_id(relation_type, source_id, target_id),
            layer=RelationLayer.STRUCTURAL,
            type=relation_type,
            source_id=source_id,
            target_id=target_id,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )

    @staticmethod
    def _validate_inputs(
        elements: tuple[Element, ...],
        logical_units: tuple[LogicalUnit, ...],
        subdocuments: tuple[SubDocument, ...],
    ) -> None:
        if not elements:
            raise RelationBuildError("cannot build structural relations for an empty source")

        element_ids = [element.id for element in elements]
        if len(element_ids) != len(set(element_ids)):
            raise RelationBuildError("elements must have unique ids")
        orders = [element.order for element in elements]
        if len(orders) != len(set(orders)):
            raise RelationBuildError("elements must have unique order values")
        if orders != sorted(orders):
            raise RelationBuildError("elements must follow canonical source order")

        unit_ids = [unit.id for unit in logical_units]
        subdoc_ids = [subdoc.id for subdoc in subdocuments]
        namespaces = (set(element_ids), set(unit_ids), set(subdoc_ids))
        if len(unit_ids) != len(namespaces[1]):
            raise RelationBuildError("logical units must have unique ids")
        if len(subdoc_ids) != len(namespaces[2]):
            raise RelationBuildError("subdocuments must have unique ids")
        if namespaces[0] & namespaces[1] or namespaces[0] & namespaces[2] or namespaces[1] & namespaces[2]:
            raise RelationBuildError("element/logical-unit/subdocument ids must not collide")

        order_by_id = {element.id: index for index, element in enumerate(elements)}
        valid_elements = set(element_ids)
        for unit in logical_units:
            missing = set(unit.element_ids) - valid_elements
            if missing:
                raise RelationBuildError(
                    f"logical unit {unit.id!r} references unknown elements: {sorted(missing)}"
                )
            positions = [order_by_id[element_id] for element_id in unit.element_ids]
            if positions != sorted(positions):
                raise RelationBuildError(
                    f"logical unit {unit.id!r} does not follow canonical element order"
                )

        seen_subdoc_elements: set[str] = set()
        for subdoc in subdocuments:
            missing = set(subdoc.element_ids) - valid_elements
            if missing:
                raise RelationBuildError(
                    f"subdocument {subdoc.id!r} references unknown elements: {sorted(missing)}"
                )
            positions = [order_by_id[element_id] for element_id in subdoc.element_ids]
            if positions != sorted(positions):
                raise RelationBuildError(
                    f"subdocument {subdoc.id!r} does not follow canonical element order"
                )
            overlap = seen_subdoc_elements.intersection(subdoc.element_ids)
            if overlap:
                raise RelationBuildError(
                    f"subdocuments overlap on elements: {sorted(overlap)}"
                )
            seen_subdoc_elements.update(subdoc.element_ids)
