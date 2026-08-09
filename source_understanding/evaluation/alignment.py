from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import Identifier, JsonObject, SchemaModel
from source_understanding.schemas.document import CanonicalDocument
from source_understanding.schemas.element import Element
from source_understanding.source_attributes import (
    SOURCE_ZONE_ATTRIBUTE,
    source_anchor,
)

from .schemas import GoldDocumentStructure, GoldElement


class AlignmentStatus(StrEnum):
    MATCHED = "MATCHED"
    GOLD_UNMATCHED = "GOLD_UNMATCHED"
    PRED_UNMATCHED = "PRED_UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"


class AlignmentMethod(StrEnum):
    EXPLICIT_SOURCE_ANCHOR = "EXPLICIT_SOURCE_ANCHOR"
    EXACT_SOURCE_TEXT = "EXACT_SOURCE_TEXT"
    NORMALIZED_TEXT = "NORMALIZED_TEXT"
    SOURCE_KIND_OCCURRENCE = "SOURCE_KIND_OCCURRENCE"
    NONE = "NONE"


class ElementMatch(SchemaModel):
    status: AlignmentStatus
    gold_id: Identifier | None = None
    predicted_id: Identifier | None = None
    method: AlignmentMethod = AlignmentMethod.NONE
    candidate_predicted_ids: tuple[Identifier, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_shape(self) -> "ElementMatch":
        if len(self.candidate_predicted_ids) != len(set(self.candidate_predicted_ids)):
            raise ValueError("candidate_predicted_ids must be unique")
        if self.status == AlignmentStatus.MATCHED:
            if self.gold_id is None or self.predicted_id is None:
                raise ValueError("MATCHED alignment requires gold_id and predicted_id")
            if self.candidate_predicted_ids:
                raise ValueError("MATCHED alignment cannot carry ambiguous candidates")
        elif self.status == AlignmentStatus.GOLD_UNMATCHED:
            if self.gold_id is None or self.predicted_id is not None:
                raise ValueError("GOLD_UNMATCHED requires only gold_id")
        elif self.status == AlignmentStatus.PRED_UNMATCHED:
            if self.predicted_id is None or self.gold_id is not None:
                raise ValueError("PRED_UNMATCHED requires only predicted_id")
        elif self.status == AlignmentStatus.AMBIGUOUS:
            if self.gold_id is None or self.predicted_id is not None:
                raise ValueError("AMBIGUOUS requires gold_id and no predicted_id")
            if len(self.candidate_predicted_ids) < 2:
                raise ValueError("AMBIGUOUS alignment requires at least two candidates")
        return self


class ElementAlignmentResult(SchemaModel):
    matches: tuple[ElementMatch, ...]
    gold_to_predicted: JsonObject = Field(default_factory=dict)
    predicted_to_gold: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_maps(self) -> "ElementAlignmentResult":
        gold_map = dict(self.gold_to_predicted)
        pred_map = dict(self.predicted_to_gold)
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in (*gold_map.items(), *pred_map.items())
        ):
            raise ValueError("alignment maps must contain only string ids")
        if len(set(gold_map.values())) != len(gold_map):
            raise ValueError("gold_to_predicted must be one-to-one")
        if len(set(pred_map.values())) != len(pred_map):
            raise ValueError("predicted_to_gold must be one-to-one")
        if {value: key for key, value in gold_map.items()} != pred_map:
            raise ValueError("alignment maps must be exact inverses")
        matched_pairs = {
            (item.gold_id, item.predicted_id)
            for item in self.matches
            if item.status == AlignmentStatus.MATCHED
        }
        if matched_pairs != set(gold_map.items()):
            raise ValueError("MATCHED records must agree with alignment maps")
        return self

    @property
    def matched_count(self) -> int:
        return len(self.gold_to_predicted)

    @property
    def gold_unmatched_ids(self) -> tuple[str, ...]:
        return tuple(
            item.gold_id
            for item in self.matches
            if item.status in {AlignmentStatus.GOLD_UNMATCHED, AlignmentStatus.AMBIGUOUS}
            and item.gold_id is not None
        )

    @property
    def predicted_unmatched_ids(self) -> tuple[str, ...]:
        return tuple(
            item.predicted_id
            for item in self.matches
            if item.status == AlignmentStatus.PRED_UNMATCHED
            and item.predicted_id is not None
        )


class ElementAligner:
    """Conservative gold↔prediction alignment.

    Alignment is intentionally stricter than a fuzzy record linker. A benchmark
    should expose parser drift rather than hide it behind approximate matching.
    """

    def align(
        self,
        gold: GoldDocumentStructure,
        predicted: CanonicalDocument,
    ) -> ElementAlignmentResult:
        predicted_elements = tuple(predicted.elements)
        by_id = {item.id: item for item in predicted_elements}
        unmatched = set(by_id)
        matches: list[ElementMatch] = []
        gold_to_predicted: dict[str, str] = {}
        predicted_to_gold: dict[str, str] = {}

        source_kind_occurrence = self._source_kind_occurrences(predicted_elements)

        for gold_element in gold.elements:
            optional = not gold_element.required
            candidate_ids, method = self._candidates(
                gold_element,
                predicted_elements,
                unmatched,
                source_kind_occurrence,
                by_id,
            )
            if len(candidate_ids) == 1:
                predicted_id = candidate_ids[0]
                unmatched.remove(predicted_id)
                gold_to_predicted[gold_element.id] = predicted_id
                predicted_to_gold[predicted_id] = gold_element.id
                matches.append(
                    ElementMatch(
                        status=AlignmentStatus.MATCHED,
                        gold_id=gold_element.id,
                        predicted_id=predicted_id,
                        method=method,
                    )
                )
            elif len(candidate_ids) > 1:
                matches.append(
                    ElementMatch(
                        status=AlignmentStatus.AMBIGUOUS,
                        gold_id=gold_element.id,
                        method=method,
                        candidate_predicted_ids=tuple(candidate_ids),
                    )
                )
            elif not optional:
                matches.append(
                    ElementMatch(
                        status=AlignmentStatus.GOLD_UNMATCHED,
                        gold_id=gold_element.id,
                    )
                )

        for predicted_element in predicted_elements:
            if predicted_element.id in unmatched:
                matches.append(
                    ElementMatch(
                        status=AlignmentStatus.PRED_UNMATCHED,
                        predicted_id=predicted_element.id,
                    )
                )

        return ElementAlignmentResult(
            matches=tuple(matches),
            gold_to_predicted=gold_to_predicted,
            predicted_to_gold=predicted_to_gold,
        )

    def _candidates(
        self,
        gold_element: GoldElement,
        predicted_elements: tuple[Element, ...],
        unmatched: set[str],
        source_kind_occurrence: dict[str, tuple[str, int]],
        predicted_by_id: dict[str, Element],
    ) -> tuple[list[str], AlignmentMethod]:
        anchor = gold_element.anchor

        if anchor.source_anchor_kind is not None:
            candidates = [
                item.id
                for item in predicted_elements
                if item.id in unmatched
                and self._part(item) == anchor.opc_part
                and self._zone_matches(item, anchor.source_zone)
                and source_anchor(item)
                == (anchor.source_anchor_kind, anchor.source_anchor_id)
            ]
            if candidates:
                return candidates, AlignmentMethod.EXPLICIT_SOURCE_ANCHOR

        if gold_element.text is not None:
            exact = [
                item.id
                for item in predicted_elements
                if item.id in unmatched
                and self._part(item) == anchor.opc_part
                and self._zone_matches(item, anchor.source_zone)
                and item.raw_text == gold_element.text
            ]
            if exact:
                exact = self._narrow_by_source_kind(
                    exact, gold_element, source_kind_occurrence
                )
                return exact, AlignmentMethod.EXACT_SOURCE_TEXT

            normalized = [
                item.id
                for item in predicted_elements
                if item.id in unmatched
                and self._part(item) == anchor.opc_part
                and self._zone_matches(item, anchor.source_zone)
                and item.text == gold_element.text
            ]
            if normalized:
                normalized = self._narrow_by_source_kind(
                    normalized, gold_element, source_kind_occurrence
                )
                return normalized, AlignmentMethod.NORMALIZED_TEXT

        if anchor.source_kind is not None and anchor.occurrence is not None:
            candidates = [
                predicted_id
                for predicted_id, (kind, occurrence) in source_kind_occurrence.items()
                if predicted_id in unmatched
                and kind == anchor.source_kind
                and occurrence == anchor.occurrence
                and self._part(predicted_by_id[predicted_id]) == anchor.opc_part
                and self._zone_matches(predicted_by_id[predicted_id], anchor.source_zone)
            ]
            if candidates:
                return candidates, AlignmentMethod.SOURCE_KIND_OCCURRENCE

        return [], AlignmentMethod.NONE

    @staticmethod
    def _narrow_by_source_kind(
        candidate_ids: list[str],
        gold_element: GoldElement,
        source_kind_occurrence: dict[str, tuple[str, int]],
    ) -> list[str]:
        expected = gold_element.anchor.source_kind
        if expected is None or len(candidate_ids) <= 1:
            return candidate_ids
        narrowed = [
            candidate_id
            for candidate_id in candidate_ids
            if source_kind_occurrence[candidate_id][0] == expected
        ]
        return narrowed if narrowed else candidate_ids

    @staticmethod
    def _part(element: Element) -> str | None:
        value = element.attributes.get("opc_part")
        return value if isinstance(value, str) else None

    @staticmethod
    def _zone_matches(element: Element, expected: str | None) -> bool:
        if expected is None:
            return True
        value = element.attributes.get(SOURCE_ZONE_ATTRIBUTE)
        return isinstance(value, str) and value == expected

    def _source_kind_occurrences(
        self, elements: tuple[Element, ...]
    ) -> dict[str, tuple[str, int]]:
        counters: dict[tuple[str | None, str | None, str], int] = defaultdict(int)
        output: dict[str, tuple[str, int]] = {}
        for item in elements:
            kind = self._source_kind(item)
            key = (self._part(item), self._zone(item), kind)
            occurrence = counters[key]
            counters[key] += 1
            output[item.id] = (kind, occurrence)
        return output

    @staticmethod
    def _zone(element: Element) -> str | None:
        value = element.attributes.get(SOURCE_ZONE_ATTRIBUTE)
        return value if isinstance(value, str) else None

    @staticmethod
    def _source_kind(element: Element) -> str:
        note_kind = element.attributes.get("note_kind")
        if isinstance(note_kind, str) and note_kind:
            return f"note:{note_kind}"

        native_kind = element.attributes.get("native_integrity_kind")
        if native_kind == "table":
            if "cell_index" in element.attributes:
                return "table_cell"
            if "row_index" in element.attributes:
                return "table_row"
            return "table"

        if "alt_chunk_relationship_id" in element.attributes:
            return "alt_chunk"

        separator_kind = element.attributes.get("separator_kind")
        if isinstance(separator_kind, str) and separator_kind:
            return f"separator:{separator_kind}"

        anchor = source_anchor(element)
        if anchor is not None:
            return f"anchor:{anchor[0]}"

        return "text"
