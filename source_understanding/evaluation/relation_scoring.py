from __future__ import annotations

from enum import StrEnum

from source_understanding.schemas.document import CanonicalDocument

from .alignment import ElementAlignmentResult
from .metrics import LabelPRF, PRFScore, prf_counts, prf_from_sets
from .report import EvaluationError, EvaluationErrorType
from .schemas import GoldDocumentStructure


class RelationEndpointKind(StrEnum):
    ELEMENT = "ELEMENT"
    LOGICAL_UNIT = "LOGICAL_UNIT"
    CONTEXT_NODE = "CONTEXT_NODE"
    REGION = "REGION"


class RelationScorer:
    """Score only the relation namespaces that the gold case actually targets.

    Structural relation types can be overloaded across endpoint namespaces. For
    example, ``PART_OF`` is used both for Element->LogicalUnit membership and
    LogicalUnit->LogicalUnit native nesting. Comparing every predicted PART_OF
    edge against a benchmark case that targets only nested LogicalUnits creates
    false positives. V0.1 therefore derives the evaluated scope from positive
    gold triples: (relation type, source namespace, target namespace).

    A future benchmark that needs negative-only relation scopes should make those
    scopes explicit in the gold schema. V0.1 deliberately avoids pretending an
    unobserved scope is negative.
    """

    def score(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> tuple[PRFScore, tuple[LabelPRF, ...]]:
        evaluated_types = set(gold.evaluated_relation_types)
        if not evaluated_types:
            return prf_counts(0, 0, 0), ()

        gold_kind = self._gold_endpoint_kinds(gold)
        predicted_kind = self._predicted_endpoint_kinds(predicted)
        evaluated_scopes = {
            (
                relation.type.value,
                gold_kind[relation.source_id].value,
                gold_kind[relation.target_id].value,
            )
            for relation in gold.relations
            if relation.type in evaluated_types
        }

        endpoint_map = self._predicted_endpoint_map(gold, predicted, alignment)
        gold_triples = {
            (relation.type.value, relation.source_id, relation.target_id)
            for relation in gold.relations
            if relation.type in evaluated_types
        }
        predicted_triples = {
            (
                relation.type.value,
                endpoint_map.get(relation.source_id, f"__pred__:{relation.source_id}"),
                endpoint_map.get(relation.target_id, f"__pred__:{relation.target_id}"),
            )
            for relation in predicted.relations
            if relation.type in evaluated_types
            and relation.source_id in predicted_kind
            and relation.target_id in predicted_kind
            and (
                relation.type.value,
                predicted_kind[relation.source_id].value,
                predicted_kind[relation.target_id].value,
            )
            in evaluated_scopes
        }

        overall = prf_from_sets(gold_triples, predicted_triples)
        for triple in sorted(gold_triples - predicted_triples):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.RELATION_MISSING,
                    message=f"missing structural relation {triple}",
                    metadata={"relation": list(triple)},
                )
            )
        for triple in sorted(predicted_triples - gold_triples):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.RELATION_EXTRA,
                    message=f"extra structural relation {triple}",
                    metadata={"relation": list(triple)},
                )
            )

        per_label = tuple(
            LabelPRF(
                label=relation_type.value,
                score=prf_from_sets(
                    {item for item in gold_triples if item[0] == relation_type.value},
                    {
                        item
                        for item in predicted_triples
                        if item[0] == relation_type.value
                    },
                ),
            )
            for relation_type in sorted(evaluated_types, key=lambda item: item.value)
        )
        return overall, per_label

    @staticmethod
    def _gold_endpoint_kinds(
        gold: GoldDocumentStructure,
    ) -> dict[str, RelationEndpointKind]:
        output: dict[str, RelationEndpointKind] = {}
        output.update({item.id: RelationEndpointKind.ELEMENT for item in gold.elements})
        output.update(
            {item.id: RelationEndpointKind.LOGICAL_UNIT for item in gold.logical_units}
        )
        output.update(
            {item.id: RelationEndpointKind.CONTEXT_NODE for item in gold.context_nodes}
        )
        output.update({item.id: RelationEndpointKind.REGION for item in gold.regions})
        return output

    @staticmethod
    def _predicted_endpoint_kinds(
        predicted: CanonicalDocument,
    ) -> dict[str, RelationEndpointKind]:
        output: dict[str, RelationEndpointKind] = {}
        output.update({item.id: RelationEndpointKind.ELEMENT for item in predicted.elements})
        output.update(
            {
                item.id: RelationEndpointKind.LOGICAL_UNIT
                for item in predicted.logical_units
            }
        )
        output.update(
            {
                item.id: RelationEndpointKind.CONTEXT_NODE
                for item in predicted.context_nodes
            }
        )
        output.update({item.id: RelationEndpointKind.REGION for item in predicted.regions})
        return output

    def _predicted_endpoint_map(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {
            predicted_id: gold_id
            for predicted_id, gold_id in alignment.predicted_to_gold.items()
        }

        gold_units_by_signature = {
            (unit.type.value, tuple(f"g:{item}" for item in unit.element_ids)): unit.id
            for unit in gold.logical_units
        }
        for unit in predicted.logical_units:
            signature = (
                unit.type.value,
                tuple(self._pred_element_token(item, alignment) for item in unit.element_ids),
            )
            gold_unit_id = gold_units_by_signature.get(signature)
            if gold_unit_id is not None:
                mapping[unit.id] = gold_unit_id

        gold_context_by_anchor = {
            item.anchor_element_id: item.id for item in gold.context_nodes
        }
        for node in predicted.context_nodes:
            anchor_id = node.attributes.get("anchor_element_id")
            if not isinstance(anchor_id, str):
                continue
            gold_element_id = alignment.predicted_to_gold.get(anchor_id)
            if gold_element_id is None:
                continue
            gold_context_id = gold_context_by_anchor.get(gold_element_id)
            if gold_context_id is not None:
                mapping[node.id] = gold_context_id

        gold_region_by_members = {
            tuple(f"g:{item}" for item in region.element_ids): region.id
            for region in gold.regions
        }
        for region in predicted.regions:
            signature = tuple(
                self._pred_element_token(item, alignment) for item in region.element_ids
            )
            gold_region_id = gold_region_by_members.get(signature)
            if gold_region_id is not None:
                mapping[region.id] = gold_region_id

        return mapping

    @staticmethod
    def _pred_element_token(
        predicted_element_id: str,
        alignment: ElementAlignmentResult,
    ) -> str:
        gold_id = alignment.predicted_to_gold.get(predicted_element_id)
        return f"g:{gold_id}" if gold_id is not None else f"p:{predicted_element_id}"
