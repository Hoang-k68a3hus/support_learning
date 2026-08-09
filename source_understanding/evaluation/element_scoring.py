from __future__ import annotations

from difflib import SequenceMatcher

from source_understanding.schemas.document import CanonicalDocument
from source_understanding.schemas.element import ElementType
from source_understanding.source_attributes import source_heading_level

from .alignment import ElementAlignmentResult
from .metrics import AccuracyScore, LabelPRF, PRFScore, accuracy_score, macro_f1, prf_from_sets
from .report import EvaluationError, EvaluationErrorType
from .schemas import GoldDocumentStructure


class ElementScorer:
    """Score element typing, headings, and source-text preservation."""

    def score_types(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        matched_optional_pred: set[str],
        errors: list[EvaluationError],
    ) -> tuple[AccuracyScore, tuple[LabelPRF, ...], float | None]:
        gold_by_id = {item.id: item for item in gold.elements}
        predicted_by_id = {item.id: item for item in predicted.elements}
        required_gold = {item.id for item in gold.elements if item.required}
        matched_required = {
            gold_id: predicted_id
            for gold_id, predicted_id in alignment.gold_to_predicted.items()
            if gold_id in required_gold
        }

        correct = 0
        for gold_id, predicted_id in matched_required.items():
            expected = gold_by_id[gold_id].type
            actual = predicted_by_id[predicted_id].type
            if actual == expected:
                correct += 1
            else:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.ELEMENT_TYPE_MISMATCH,
                        message=(
                            f"gold element {gold_id!r} expected {expected.value}, "
                            f"predicted {actual.value}"
                        ),
                        gold_ids=(gold_id,),
                        predicted_ids=(predicted_id,),
                        metadata={
                            "gold_type": expected.value,
                            "predicted_type": actual.value,
                        },
                    )
                )

        per_label = self._type_scores(
            gold, predicted, alignment, matched_optional_pred
        )
        return (
            accuracy_score(correct, len(matched_required)),
            per_label,
            macro_f1(item.score for item in per_label),
        )

    def heading_detection(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        matched_optional_pred: set[str],
        errors: list[EvaluationError],
    ) -> PRFScore:
        score = self._label_detection_score(
            label=ElementType.HEADING,
            gold=gold,
            predicted=predicted,
            alignment=alignment,
            matched_optional_pred=matched_optional_pred,
        )
        gold_by_id = {item.id: item for item in gold.elements}
        predicted_by_id = {item.id: item for item in predicted.elements}
        for gold_element in gold.elements:
            if not gold_element.required or gold_element.type != ElementType.HEADING:
                continue
            predicted_id = alignment.gold_to_predicted.get(gold_element.id)
            if predicted_id is None:
                continue
            if predicted_by_id[predicted_id].type != ElementType.HEADING:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.HEADING_MISSED,
                        message=(
                            f"gold heading {gold_element.id!r} was aligned but not "
                            "typed HEADING"
                        ),
                        gold_ids=(gold_element.id,),
                        predicted_ids=(predicted_id,),
                    )
                )
        for predicted_element in predicted.elements:
            if predicted_element.id in matched_optional_pred:
                continue
            if predicted_element.type != ElementType.HEADING:
                continue
            gold_id = alignment.predicted_to_gold.get(predicted_element.id)
            if gold_id is None or gold_by_id[gold_id].type != ElementType.HEADING:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.HEADING_FALSE_POSITIVE,
                        message=f"predicted heading {predicted_element.id!r} is not gold",
                        gold_ids=(gold_id,) if gold_id is not None else (),
                        predicted_ids=(predicted_element.id,),
                    )
                )
        return score

    def heading_levels(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> AccuracyScore:
        predicted_by_id = {item.id: item for item in predicted.elements}
        context_by_anchor = self._context_by_anchor(predicted)
        correct = 0
        total = 0
        for gold_element in gold.elements:
            if (
                not gold_element.required
                or gold_element.type != ElementType.HEADING
                or gold_element.heading_level is None
            ):
                continue
            total += 1
            predicted_id = alignment.gold_to_predicted.get(gold_element.id)
            if predicted_id is None:
                continue
            predicted_element = predicted_by_id[predicted_id]
            node = context_by_anchor.get(predicted_id)
            predicted_level = getattr(node, "level", None)
            if predicted_level is None:
                try:
                    predicted_level = source_heading_level(predicted_element)
                except ValueError:
                    predicted_level = None
            if predicted_level == gold_element.heading_level:
                correct += 1
            else:
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.HEADING_LEVEL_MISMATCH,
                        message=(
                            f"gold heading {gold_element.id!r} expected level "
                            f"{gold_element.heading_level}, predicted {predicted_level}"
                        ),
                        gold_ids=(gold_element.id,),
                        predicted_ids=(predicted_id,),
                        metadata={
                            "gold_level": gold_element.heading_level,
                            "predicted_level": predicted_level,
                        },
                    )
                )
        return accuracy_score(correct, total)

    def text_preservation(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        errors: list[EvaluationError],
    ) -> tuple[AccuracyScore, float | None, int, int]:
        predicted_by_id = {item.id: item for item in predicted.elements}
        text_gold = [
            item for item in gold.elements if item.required and item.text is not None
        ]
        exact_count = 0
        total_chars = sum(len(item.text or "") for item in text_gold)
        preserved_chars = 0

        for item in text_gold:
            predicted_id = alignment.gold_to_predicted.get(item.id)
            if predicted_id is None:
                continue
            actual = predicted_by_id[predicted_id].raw_text
            if actual == item.text:
                exact_count += 1
                preserved_chars += len(item.text)
            else:
                if isinstance(actual, str):
                    preserved_chars += sum(
                        block.size
                        for block in SequenceMatcher(
                            None, item.text, actual, autojunk=False
                        ).get_matching_blocks()
                    )
                errors.append(
                    EvaluationError(
                        type=EvaluationErrorType.SOURCE_TEXT_LOSS,
                        message=f"source text mismatch for gold element {item.id!r}",
                        gold_ids=(item.id,),
                        predicted_ids=(predicted_id,),
                        metadata={
                            "gold_text": item.text,
                            "predicted_raw_text": actual,
                        },
                    )
                )

        return (
            accuracy_score(exact_count, len(text_gold)),
            preserved_chars / total_chars if total_chars else None,
            total_chars,
            preserved_chars,
        )

    def _type_scores(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        matched_optional_pred: set[str],
    ) -> tuple[LabelPRF, ...]:
        required_gold = {item.id for item in gold.elements if item.required}
        output: list[LabelPRF] = []
        for element_type in ElementType:
            gold_set = {
                f"g:{item.id}"
                for item in gold.elements
                if item.required and item.type == element_type
            }
            predicted_set: set[str] = set()
            for item in predicted.elements:
                if item.id in matched_optional_pred or item.type != element_type:
                    continue
                gold_id = alignment.predicted_to_gold.get(item.id)
                if gold_id is not None and gold_id in required_gold:
                    predicted_set.add(f"g:{gold_id}")
                elif gold_id is None:
                    predicted_set.add(f"p:{item.id}")
            score = prf_from_sets(gold_set, predicted_set)
            if score.support > 0 or score.false_positive > 0:
                output.append(LabelPRF(label=element_type.value, score=score))
        return tuple(output)

    @staticmethod
    def _label_detection_score(
        *,
        label: ElementType,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
        alignment: ElementAlignmentResult,
        matched_optional_pred: set[str],
    ) -> PRFScore:
        gold_set = {
            f"g:{item.id}"
            for item in gold.elements
            if item.required and item.type == label
        }
        required_gold = {item.id for item in gold.elements if item.required}
        predicted_set: set[str] = set()
        for item in predicted.elements:
            if item.id in matched_optional_pred or item.type != label:
                continue
            gold_id = alignment.predicted_to_gold.get(item.id)
            if gold_id is not None and gold_id in required_gold:
                predicted_set.add(f"g:{gold_id}")
            elif gold_id is None:
                predicted_set.add(f"p:{item.id}")
        return prf_from_sets(gold_set, predicted_set)

    @staticmethod
    def _context_by_anchor(predicted: CanonicalDocument) -> dict[str, object]:
        output: dict[str, object] = {}
        for node in predicted.context_nodes:
            anchor = node.attributes.get("anchor_element_id")
            if isinstance(anchor, str) and anchor not in output:
                output[anchor] = node
        return output
