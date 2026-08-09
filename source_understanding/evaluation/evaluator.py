from __future__ import annotations

from collections.abc import Sequence

from source_understanding.schemas.document import CanonicalDocument
from source_understanding.schemas.element import Element
from source_understanding.source_attributes import SOURCE_ZONE_ATTRIBUTE

from .alignment import AlignmentStatus, ElementAligner, ElementAlignmentResult
from .element_scoring import ElementScorer
from .metrics import prf_counts
from .relation_scoring import RelationScorer
from .report import (
    DocumentEvaluationMetrics,
    DocumentEvaluationReport,
    EvaluationError,
    EvaluationErrorType,
)
from .schemas import GoldDocumentStructure
from .structure_scoring import StructureScorer


class DocumentStructureEvaluator:
    """Evaluate one canonical structural parse against implementation-independent gold."""

    def __init__(
        self,
        aligner: ElementAligner | None = None,
        *,
        element_scorer: ElementScorer | None = None,
        structure_scorer: StructureScorer | None = None,
        relation_scorer: RelationScorer | None = None,
    ) -> None:
        self._aligner = aligner if aligner is not None else ElementAligner()
        self._element_scorer = (
            element_scorer if element_scorer is not None else ElementScorer()
        )
        self._structure_scorer = (
            structure_scorer if structure_scorer is not None else StructureScorer()
        )
        self._relation_scorer = (
            relation_scorer if relation_scorer is not None else RelationScorer()
        )

    def evaluate(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        *,
        adapter_diagnostics: Sequence[object] = (),
        structural_ready: bool | None = None,
    ) -> DocumentEvaluationReport:
        self._validate_identity(gold, predicted)
        alignment = self._aligner.align(gold, predicted)
        required_gold = {item.id for item in gold.elements if item.required}
        optional_gold = {item.id for item in gold.elements if not item.required}
        matched_optional_pred = {
            predicted_id
            for gold_id, predicted_id in alignment.gold_to_predicted.items()
            if gold_id in optional_gold
        }
        errors = self._alignment_errors(alignment, required_gold, predicted)

        matched_required = {
            gold_id: predicted_id
            for gold_id, predicted_id in alignment.gold_to_predicted.items()
            if gold_id in required_gold
        }
        element_detection = prf_counts(
            tp=len(matched_required),
            fp=len(alignment.predicted_unmatched_ids),
            fn=len(required_gold - set(matched_required)),
        )

        (
            element_type_accuracy,
            element_type_scores,
            element_type_macro_f1,
        ) = self._element_scorer.score_types(
            gold,
            predicted,
            alignment,
            matched_optional_pred,
            errors,
        )
        heading_detection = self._element_scorer.heading_detection(
            gold,
            predicted,
            alignment,
            matched_optional_pred,
            errors,
        )
        heading_level_accuracy = self._element_scorer.heading_levels(
            gold,
            predicted,
            alignment,
            errors,
        )

        hierarchy_parent_edges = self._structure_scorer.hierarchy_parents(
            gold, predicted, alignment, errors
        )
        logical_unit_pairwise, integrity_exact_match = (
            self._structure_scorer.logical_units(
                gold, predicted, alignment, errors
            )
        )
        region_boundary, region_category_accuracy = self._structure_scorer.regions(
            gold, predicted, alignment, errors
        )
        structural_relations, relation_per_label = self._relation_scorer.score(
            gold, predicted, alignment, errors
        )

        (
            source_text_exact,
            text_preservation_ratio,
            source_text_gold_char_count,
            source_text_preserved_char_count,
        ) = self._element_scorer.text_preservation(
            gold, predicted, alignment, errors
        )
        (
            expected_diagnostic_recall,
            unexpected_structural_diagnostic_count,
        ) = self._structure_scorer.diagnostics(
            gold, adapter_diagnostics, errors
        )

        structure_mode_matches = self._structure_mode_check(gold, predicted, errors)
        structural_ready_matches = self._structural_ready_check(
            gold, structural_ready, errors
        )

        metrics = DocumentEvaluationMetrics(
            gold_element_count=len(required_gold),
            predicted_element_count=len(predicted.elements),
            aligned_element_count=len(matched_required),
            element_detection=element_detection,
            element_type_accuracy=element_type_accuracy,
            element_type_macro_f1=element_type_macro_f1,
            element_type_per_label=element_type_scores,
            heading_detection=heading_detection,
            heading_level_accuracy=heading_level_accuracy,
            hierarchy_parent_edges=hierarchy_parent_edges,
            logical_unit_pairwise=logical_unit_pairwise,
            integrity_exact_match=integrity_exact_match,
            region_boundary=region_boundary,
            region_category_accuracy=region_category_accuracy,
            structural_relations=structural_relations,
            relation_per_label=relation_per_label,
            source_text_exact=source_text_exact,
            source_text_gold_char_count=source_text_gold_char_count,
            source_text_preserved_char_count=source_text_preserved_char_count,
            source_text_preservation_ratio=text_preservation_ratio,
            expected_diagnostic_recall=expected_diagnostic_recall,
            unexpected_structural_diagnostic_count=unexpected_structural_diagnostic_count,
            predicted_structure_mode=predicted.structure.mode.value,
            expected_structure_mode=(
                gold.expected_structure_mode.value
                if gold.expected_structure_mode is not None
                else None
            ),
            structure_mode_matches=structure_mode_matches,
            predicted_structural_ready=structural_ready,
            expected_structural_ready=gold.expected_structural_ready,
            structural_ready_matches=structural_ready_matches,
        )

        return DocumentEvaluationReport(
            document_id=gold.document_id,
            metrics=metrics,
            alignment=alignment,
            errors=tuple(errors),
            diagnostics={
                "evaluation_scope": "document_structure_benchmark",
                "evaluation_is_model_accuracy": False,
                "alignment_is_conservative": True,
                "relation_scope_is_gold_endpoint_namespace": True,
                "optional_gold_element_count": len(optional_gold),
                "evaluated_logical_unit_types": [
                    item.value for item in gold.evaluated_logical_unit_types
                ],
                "evaluated_relation_types": [
                    item.value for item in gold.evaluated_relation_types
                ],
            },
        )

    @staticmethod
    def _validate_identity(
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
    ) -> None:
        if predicted.document_id != gold.document_id:
            raise ValueError(
                f"predicted document_id {predicted.document_id!r} does not match "
                f"gold {gold.document_id!r}"
            )
        if predicted.content_hash != gold.source.sha256:
            raise ValueError(
                f"predicted content_hash {predicted.content_hash!r} does not match "
                f"gold source hash {gold.source.sha256!r}"
            )

    @staticmethod
    def _alignment_errors(
        alignment: ElementAlignmentResult,
        required_gold: set[str],
        predicted: CanonicalDocument,
    ) -> list[EvaluationError]:
        errors: list[EvaluationError] = []
        predicted_by_id = {item.id: item for item in predicted.elements}
        for match in alignment.matches:
            if (
                match.status == AlignmentStatus.GOLD_UNMATCHED
                and match.gold_id in required_gold
            ):
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.ADAPTER_MISSING_ELEMENT,
                        message=f"required gold element {match.gold_id!r} was not aligned",
                        gold_ids=(match.gold_id,),
                    )
                )
            elif match.status == AlignmentStatus.PRED_UNMATCHED:
                item = predicted_by_id.get(match.predicted_id)
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.ADAPTER_EXTRA_ELEMENT,
                        message=(
                            f"predicted element {match.predicted_id!r} has no gold alignment"
                        ),
                        predicted_ids=(match.predicted_id,),
                        metadata=(
                            DocumentStructureEvaluator._element_debug_metadata(item)
                            if item is not None
                            else {}
                        ),
                    )
                )
            elif match.status == AlignmentStatus.AMBIGUOUS:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.ALIGNMENT_AMBIGUOUS,
                        message=(
                            f"gold element {match.gold_id!r} has ambiguous "
                            "prediction candidates"
                        ),
                        gold_ids=(match.gold_id,),
                        predicted_ids=match.candidate_predicted_ids,
                    )
                )
        return errors

    @staticmethod
    def _element_debug_metadata(element: Element) -> dict[str, object]:
        attributes = element.attributes
        safe_attribute_keys = (
            "opc_part",
            SOURCE_ZONE_ATTRIBUTE,
            "separator_kind",
            "note_kind",
            "native_integrity_kind",
            "row_index",
            "cell_index",
            "alt_chunk_relationship_id",
            "paragraph_style_id",
        )
        selected = {
            key: attributes[key]
            for key in safe_attribute_keys
            if key in attributes
        }
        return {
            "type": element.type.value,
            "raw_text": element.raw_text,
            "normalized_text": element.normalized_text,
            "order": element.order,
            "attributes": selected,
        }

    @staticmethod
    def _structure_mode_check(
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        errors: list[EvaluationError],
    ) -> bool | None:
        if gold.expected_structure_mode is None:
            return None
        matches = predicted.structure.mode == gold.expected_structure_mode
        if not matches:
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.STRUCTURE_MODE_MISMATCH,
                    message=(
                        f"expected document structure mode "
                        f"{gold.expected_structure_mode.value}, predicted "
                        f"{predicted.structure.mode.value}"
                    ),
                    metadata={
                        "expected_structure_mode": gold.expected_structure_mode.value,
                        "predicted_structure_mode": predicted.structure.mode.value,
                    },
                )
            )
        return matches

    @staticmethod
    def _structural_ready_check(
        gold: GoldDocumentStructure,
        structural_ready: bool | None,
        errors: list[EvaluationError],
    ) -> bool | None:
        if gold.expected_structural_ready is None or structural_ready is None:
            return None
        matches = gold.expected_structural_ready == structural_ready
        if not matches:
            errors.append(
                EvaluationError(
                    type=EvaluationErrorType.STRUCTURAL_READY_MISMATCH,
                    message=(
                        f"expected structural_ready={gold.expected_structural_ready}, "
                        f"predicted {structural_ready}"
                    ),
                    metadata={
                        "expected": gold.expected_structural_ready,
                        "predicted": structural_ready,
                    },
                )
            )
        return matches
