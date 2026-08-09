from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from itertools import combinations

from source_understanding.schemas.document import CanonicalDocument

from .alignment import ElementAlignmentResult
from .metrics import AccuracyScore, LabelPRF, PRFScore, accuracy_score, prf_counts, prf_from_sets
from .report import EvaluationError, EvaluationErrorType
from .schemas import GoldDocumentStructure


class StructureScorer:
    """Score hierarchy, integrity units, regions, relations, and diagnostics."""

    def hierarchy_parents(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> PRFScore:
        gold_nodes = {item.id: item for item in gold.context_nodes}
        gold_edges = {
            (
                f"g:{item.anchor_element_id}",
                f"g:{gold_nodes[item.parent_id].anchor_element_id}",
            )
            for item in gold.context_nodes
            if item.parent_id is not None
        }

        predicted_node_tokens: dict[str, str] = {}
        for node in predicted.context_nodes:
            anchor_id = node.attributes.get("anchor_element_id")
            gold_element_id = (
                alignment.predicted_to_gold.get(anchor_id)
                if isinstance(anchor_id, str)
                else None
            )
            predicted_node_tokens[node.id] = (
                f"g:{gold_element_id}"
                if gold_element_id is not None
                else f"pctx:{node.id}"
            )

        predicted_edges = {
            (
                predicted_node_tokens[node.id],
                predicted_node_tokens[node.parent_id],
            )
            for node in predicted.context_nodes
            if node.parent_id is not None and node.parent_id in predicted_node_tokens
        }

        score = prf_from_sets(gold_edges, predicted_edges)
        missing = gold_edges - predicted_edges
        extra = predicted_edges - gold_edges
        predicted_by_child = {child: parent for child, parent in predicted_edges}
        missing_children = {item[0] for item in missing}
        for child, parent in sorted(missing):
            actual = predicted_by_child.get(child)
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.HIERARCHY_WRONG_PARENT,
                    message=(
                        f"missing gold hierarchy edge {child}->{parent}; "
                        f"predicted parent is {actual!r}"
                    ),
                    metadata={
                        "child": child,
                        "gold_parent": parent,
                        "predicted_parent": actual,
                    },
                )
            )
        for child, parent in sorted(extra):
            if child in missing_children:
                continue
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.HIERARCHY_WRONG_PARENT,
                    message=f"extra predicted hierarchy edge {child}->{parent}",
                    metadata={"child": child, "predicted_parent": parent},
                )
            )
        return score

    def logical_units(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> tuple[PRFScore, PRFScore]:
        evaluated_types = set(gold.evaluated_logical_unit_types)
        if not evaluated_types:
            empty = prf_counts(0, 0, 0)
            return empty, empty

        gold_pair_set: set[tuple[str, str]] = set()
        for unit in gold.logical_units:
            if unit.type not in evaluated_types:
                continue
            members = [f"g:{item}" for item in unit.element_ids]
            gold_pair_set.update(tuple(sorted(pair)) for pair in combinations(members, 2))

        predicted_pair_set: set[tuple[str, str]] = set()
        for unit in predicted.logical_units:
            if unit.type not in evaluated_types:
                continue
            members = [self.pred_element_token(item, alignment) for item in unit.element_ids]
            predicted_pair_set.update(
                tuple(sorted(pair)) for pair in combinations(members, 2)
            )

        pairwise = prf_from_sets(gold_pair_set, predicted_pair_set)
        for pair in sorted(gold_pair_set - predicted_pair_set):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.LOGICAL_UNIT_OVER_SPLIT,
                    message=f"gold same-unit pair {pair} was split",
                    metadata={"pair": list(pair)},
                )
            )
        for pair in sorted(predicted_pair_set - gold_pair_set):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.LOGICAL_UNIT_OVER_MERGE,
                    message=f"predicted same-unit pair {pair} is not gold",
                    metadata={"pair": list(pair)},
                )
            )

        exact_gold_units = [
            unit
            for unit in gold.logical_units
            if unit.type in evaluated_types and unit.exact_match
        ]
        exact_types = {unit.type for unit in exact_gold_units}
        gold_signatures = {
            (unit.type.value, tuple(f"g:{item}" for item in unit.element_ids))
            for unit in exact_gold_units
        }
        predicted_signatures = {
            (
                unit.type.value,
                tuple(self.pred_element_token(item, alignment) for item in unit.element_ids),
            )
            for unit in predicted.logical_units
            if unit.type in exact_types
        }
        exact = prf_from_sets(gold_signatures, predicted_signatures)
        for signature in sorted(gold_signatures - predicted_signatures):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.INTEGRITY_BLOCK_BROKEN,
                    message=(
                        "gold integrity block was not exactly reconstructed: "
                        f"{signature[0]}"
                    ),
                    metadata={"signature": [signature[0], list(signature[1])]},
                )
            )
        return pairwise, exact

    def regions(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> tuple[PRFScore, AccuracyScore]:
        if not gold.regions:
            return prf_counts(0, 0, 0), accuracy_score(0, 0)

        gold_region_by_element: dict[str, str] = {}
        gold_category_by_element: dict[str, str | None] = {}
        for region in gold.regions:
            for element_id in region.element_ids:
                gold_region_by_element[element_id] = region.id
                gold_category_by_element[element_id] = (
                    region.category.value if region.category is not None else None
                )

        predicted_region_by_element: dict[str, str] = {}
        predicted_category_by_element: dict[str, str | None] = {}
        for region in predicted.regions:
            category = region.metadata.get("routing_category")
            resolved_category = category if isinstance(category, str) else None
            for element_id in region.element_ids:
                predicted_region_by_element[element_id] = region.id
                predicted_category_by_element[element_id] = resolved_category

        ordered_gold_ids = [item.id for item in gold.elements if item.required]
        gold_boundaries: set[int] = set()
        predicted_boundaries: set[int] = set()
        comparable_adjacencies: set[int] = set()

        for index, (left, right) in enumerate(
            zip(ordered_gold_ids, ordered_gold_ids[1:], strict=False)
        ):
            left_pred = alignment.gold_to_predicted.get(left)
            right_pred = alignment.gold_to_predicted.get(right)
            if left_pred is None or right_pred is None:
                continue
            comparable_adjacencies.add(index)
            if gold_region_by_element[left] != gold_region_by_element[right]:
                gold_boundaries.add(index)
            left_region = predicted_region_by_element.get(left_pred)
            right_region = predicted_region_by_element.get(right_pred)
            if (
                left_region is not None
                and right_region is not None
                and left_region != right_region
            ):
                predicted_boundaries.add(index)

        score = prf_from_sets(
            gold_boundaries & comparable_adjacencies,
            predicted_boundaries & comparable_adjacencies,
        )
        for index in sorted(gold_boundaries - predicted_boundaries):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.REGION_BOUNDARY_MISSING,
                    message=f"missing region boundary after gold adjacency index {index}",
                    metadata={"adjacency_index": index},
                )
            )
        for index in sorted(predicted_boundaries - gold_boundaries):
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.REGION_BOUNDARY_EXTRA,
                    message=f"extra region boundary after gold adjacency index {index}",
                    metadata={"adjacency_index": index},
                )
            )

        category_correct = 0
        category_total = 0
        for gold_element in gold.elements:
            if not gold_element.required:
                continue
            expected = gold_category_by_element.get(gold_element.id)
            if expected is None:
                continue
            predicted_id = alignment.gold_to_predicted.get(gold_element.id)
            if predicted_id is None:
                continue
            actual = predicted_category_by_element.get(predicted_id)
            category_total += 1
            if actual == expected:
                category_correct += 1
            else:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.REGION_WRONG_CATEGORY,
                        message=(
                            f"gold element {gold_element.id!r} expected region category "
                            f"{expected!r}, predicted {actual!r}"
                        ),
                        gold_ids=(gold_element.id,),
                        predicted_ids=(predicted_id,),
                        metadata={
                            "gold_category": expected,
                            "predicted_category": actual,
                        },
                    )
                )
        return score, accuracy_score(category_correct, category_total)

    def relations(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> tuple[PRFScore, tuple[LabelPRF, ...]]:
        evaluated_types = set(gold.evaluated_relation_types)
        if not evaluated_types:
            return prf_counts(0, 0, 0), ()

        endpoint_map = self._predicted_endpoint_map(gold, predicted, alignment)
        gold_triples = {
            (item.type.value, item.source_id, item.target_id)
            for item in gold.relations
            if item.type in evaluated_types
        }
        predicted_triples = {
            (
                relation.type.value,
                endpoint_map.get(relation.source_id, f"__pred__:{relation.source_id}"),
                endpoint_map.get(relation.target_id, f"__pred__:{relation.target_id}"),
            )
            for relation in predicted.relations
            if relation.type in evaluated_types
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

    def diagnostics(
        self,
        gold: GoldDocumentStructure,
        adapter_diagnostics: Sequence[object],
        errors: list[EvaluationError],
    ) -> tuple[AccuracyScore, int]:
        counts = Counter(
            code
            for item in adapter_diagnostics
            if isinstance((code := getattr(item, "code", None)), str)
        )
        met = 0
        for expected in gold.expected_diagnostics:
            actual_count = counts.get(expected.code, 0)
            completeness_matches = True
            if expected.affects_structural_completeness is not None:
                completeness_matches = any(
                    getattr(item, "code", None) == expected.code
                    and getattr(item, "affects_structural_completeness", None)
                    == expected.affects_structural_completeness
                    for item in adapter_diagnostics
                )
            if actual_count >= expected.min_count and completeness_matches:
                met += 1
            else:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.EXPECTED_DIAGNOSTIC_MISSING,
                        message=(
                            f"expected diagnostic {expected.code!r} at least "
                            f"{expected.min_count} time(s), observed {actual_count}"
                        ),
                        metadata={
                            "code": expected.code,
                            "expected_min_count": expected.min_count,
                            "observed_count": actual_count,
                        },
                    )
                )

        expected_codes = {item.code for item in gold.expected_diagnostics}
        unexpected_structural = [
            item
            for item in adapter_diagnostics
            if bool(getattr(item, "affects_structural_completeness", False))
            and getattr(item, "code", None) not in expected_codes
        ]
        for item in unexpected_structural:
            code = getattr(item, "code", "UNKNOWN")
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.UNEXPECTED_STRUCTURAL_DIAGNOSTIC,
                    message=f"unexpected structural adapter diagnostic {code!r}",
                    metadata={"code": code},
                )
            )
        return (
            accuracy_score(met, len(gold.expected_diagnostics)),
            len(unexpected_structural),
        )

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
                tuple(self.pred_element_token(item, alignment) for item in unit.element_ids),
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
                self.pred_element_token(item, alignment) for item in region.element_ids
            )
            gold_region_id = gold_region_by_members.get(signature)
            if gold_region_id is not None:
                mapping[region.id] = gold_region_id

        return mapping

    @staticmethod
    def pred_element_token(
        predicted_element_id: str,
        alignment: ElementAlignmentResult,
    ) -> str:
        gold_id = alignment.predicted_to_gold.get(predicted_element_id)
        return f"g:{gold_id}" if gold_id is not None else f"p:{predicted_element_id}"
