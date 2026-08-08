from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnitType
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryDecision,
    BoundaryIntegrityGuard,
    BoundaryPolicy,
    BoundaryReason,
    BoundarySet,
)
from source_understanding.structure.grouping import (
    GroupingError,
    GroupingPolicy,
    LogicalGroupBuilder,
)
from source_understanding.structure.signals import (
    StructureSignal,
    StructureSignalKind,
    StructureSignalSet,
)


def element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str = "text",
    *,
    source: StructureSource = StructureSource.EXPLICIT,
) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        provenance=Provenance(source=source, extractor="test"),
    )


def signal_set(
    elements: tuple[Element, ...],
    extra: tuple[StructureSignal, ...] = (),
) -> StructureSignalSet:
    type_signals = tuple(
        StructureSignal(
            id=f"type_{item.id}",
            kind=StructureSignalKind.ELEMENT_TYPE,
            element_ids=(item.id,),
            source=item.provenance.source,
            text_value=item.type.value,
        )
        for item in elements
    )
    return StructureSignalSet(
        element_count=len(elements),
        signals=type_signals + extra,
    )


def boundary_set(
    elements: tuple[Element, ...],
    *,
    overrides: dict[int, dict[str, object]] | None = None,
) -> BoundarySet:
    overrides = overrides or {}
    boundaries = []
    for index in range(len(elements) - 1):
        data = {
            "id": f"b{index}",
            "left_element_id": elements[index].id,
            "right_element_id": elements[index + 1].id,
            "classification": BoundaryClass.NONE,
            "score": 0.0,
        }
        data.update(overrides.get(index, {}))
        boundaries.append(BoundaryDecision(**data))
    return BoundarySet(
        element_count=len(elements),
        signal_version="1",
        policy=BoundaryPolicy(),
        boundaries=tuple(boundaries),
    )


class GroupingTests(unittest.TestCase):
    def test_explicit_qa_pair_becomes_one_unit(self) -> None:
        elements = (
            element("q", 0, ElementType.QUESTION, "Question"),
            element("a", 1, ElementType.ANSWER, "Answer"),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {
                    "classification": BoundaryClass.NONE,
                    "integrity_guard": BoundaryIntegrityGuard.QA_PAIR,
                }
            },
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements), boundaries)
        self.assertEqual(len(result.logical_units), 1)
        unit = result.logical_units[0]
        self.assertEqual(unit.type, LogicalUnitType.QA_PAIR)
        self.assertEqual(unit.element_ids, ("q", "a"))
        self.assertEqual(unit.source, StructureSource.DERIVED)
        self.assertEqual(result.ungrouped_element_ids, ())

    def test_lexical_qa_pair_is_inferred_and_preserves_element_types(self) -> None:
        elements = (
            element("q", 0, ElementType.PARAGRAPH, "Q: x"),
            element("a", 1, ElementType.PARAGRAPH, "A: y"),
        )
        extra = (
            StructureSignal(
                id="qm",
                kind=StructureSignalKind.QUESTION_MARKER,
                element_ids=("q",),
                source=StructureSource.INFERRED,
                text_value="Q:",
            ),
            StructureSignal(
                id="am",
                kind=StructureSignalKind.ANSWER_MARKER,
                element_ids=("a",),
                source=StructureSource.INFERRED,
                text_value="A:",
            ),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {
                    "classification": BoundaryClass.NONE,
                    "integrity_guard": BoundaryIntegrityGuard.QA_PAIR,
                }
            },
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements, extra), boundaries)
        unit = result.logical_units[0]
        self.assertEqual(unit.type, LogicalUnitType.QA_PAIR)
        self.assertEqual(unit.source, StructureSource.INFERRED)
        self.assertEqual(elements[0].type, ElementType.PARAGRAPH)
        self.assertEqual(elements[1].type, ElementType.PARAGRAPH)

    def test_nonadjacent_question_answer_are_not_paired(self) -> None:
        elements = (
            element("q", 0, ElementType.QUESTION),
            element("middle", 1, ElementType.PARAGRAPH),
            element("a", 2, ElementType.ANSWER),
        )
        result = LogicalGroupBuilder().build(
            elements, signal_set(elements), boundary_set(elements)
        )
        self.assertNotIn(
            LogicalUnitType.QA_PAIR,
            [unit.type for unit in result.logical_units],
        )
        self.assertIn("q", result.ungrouped_element_ids)
        self.assertIn("a", result.ungrouped_element_ids)

    def test_dialogue_run_is_grouped_without_topic_inference(self) -> None:
        elements = (
            element("d0", 0, ElementType.DIALOGUE_TURN),
            element("d1", 1, ElementType.DIALOGUE_TURN),
            element("d2", 2, ElementType.DIALOGUE_TURN),
            element("p", 3, ElementType.PARAGRAPH),
        )
        result = LogicalGroupBuilder().build(
            elements, signal_set(elements), boundary_set(elements)
        )
        dialogue = next(
            unit
            for unit in result.logical_units
            if unit.type == LogicalUnitType.DIALOGUE_SEGMENT
        )
        self.assertEqual(dialogue.element_ids, ("d0", "d1", "d2"))

    def test_log_run_is_grouped(self) -> None:
        elements = (
            element("l0", 0, ElementType.LOG_ENTRY),
            element("l1", 1, ElementType.LOG_ENTRY),
        )
        result = LogicalGroupBuilder().build(
            elements, signal_set(elements), boundary_set(elements)
        )
        self.assertEqual(result.logical_units[0].type, LogicalUnitType.LOG_WINDOW)
        self.assertEqual(result.logical_units[0].element_ids, ("l0", "l1"))

    def test_hard_boundary_splits_dialogue_runs(self) -> None:
        elements = (
            element("d0", 0, ElementType.DIALOGUE_TURN),
            element("d1", 1, ElementType.DIALOGUE_TURN),
            element("d2", 2, ElementType.DIALOGUE_TURN),
            element("d3", 3, ElementType.DIALOGUE_TURN),
        )
        boundaries = boundary_set(
            elements,
            overrides={1: {"classification": BoundaryClass.HARD}},
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements), boundaries)
        dialogue_units = [
            unit
            for unit in result.logical_units
            if unit.type == LogicalUnitType.DIALOGUE_SEGMENT
        ]
        self.assertEqual(
            [unit.element_ids for unit in dialogue_units],
            [("d0", "d1"), ("d2", "d3")],
        )

    def test_atomic_integrity_elements_are_single_units(self) -> None:
        elements = (
            element("table", 0, ElementType.TABLE),
            element("code", 1, ElementType.CODE),
            element("list", 2, ElementType.LIST),
            element("kv", 3, ElementType.KEY_VALUE),
            element("formula", 4, ElementType.FORMULA),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {"classification": BoundaryClass.HARD},
                1: {"classification": BoundaryClass.HARD},
                2: {"classification": BoundaryClass.HARD},
                3: {"classification": BoundaryClass.HARD},
            },
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements), boundaries)
        self.assertEqual(
            [unit.type for unit in result.logical_units],
            [
                LogicalUnitType.TABLE_BLOCK,
                LogicalUnitType.CODE_BLOCK,
                LogicalUnitType.LIST_GROUP,
                LogicalUnitType.KEY_VALUE_GROUP,
                LogicalUnitType.TEXT_BLOCK,
            ],
        )

    def test_unresolved_sub_elements_remain_ungrouped(self) -> None:
        elements = (
            element("row", 0, ElementType.TABLE_ROW),
            element("cell", 1, ElementType.TABLE_CELL),
            element("item", 2, ElementType.LIST_ITEM),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {
                    "classification": BoundaryClass.UNKNOWN,
                    "reasons": (BoundaryReason.CONTENT_INTEGRITY_UNRESOLVED,),
                },
                1: {"classification": BoundaryClass.HARD},
            },
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements), boundaries)
        self.assertEqual(result.ungrouped_element_ids, ("row", "cell", "item"))

    def test_fallback_text_blocks_merge_soft_but_not_unknown(self) -> None:
        elements = (
            element("p0", 0, ElementType.PARAGRAPH),
            element("p1", 1, ElementType.PARAGRAPH),
            element("p2", 2, ElementType.PARAGRAPH),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {"classification": BoundaryClass.SOFT},
                1: {"classification": BoundaryClass.UNKNOWN},
            },
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements), boundaries)
        blocks = [
            unit.element_ids
            for unit in result.logical_units
            if unit.type == LogicalUnitType.TEXT_BLOCK
        ]
        self.assertEqual(blocks, [("p0", "p1"), ("p2",)])

    def test_headings_are_left_for_hierarchy_stage(self) -> None:
        elements = (
            element("h", 0, ElementType.HEADING),
            element("p", 1, ElementType.PARAGRAPH),
        )
        result = LogicalGroupBuilder().build(
            elements, signal_set(elements), boundary_set(elements)
        )
        self.assertIn("h", result.ungrouped_element_ids)
        self.assertEqual(result.logical_units[0].element_ids, ("p",))

    def test_repeated_explicit_titles_create_subdocuments(self) -> None:
        elements = (
            element("t0", 0, ElementType.TITLE, "Doc A"),
            element("p0", 1, ElementType.PARAGRAPH),
            element("sep", 2, ElementType.SEPARATOR, "---"),
            element("t1", 3, ElementType.TITLE, "Doc B"),
            element("p1", 4, ElementType.PARAGRAPH),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {"classification": BoundaryClass.SOFT},
                1: {"classification": BoundaryClass.HARD},
                2: {
                    "classification": BoundaryClass.HARD,
                    "reasons": (BoundaryReason.EXPLICIT_STRUCTURE_START,),
                },
                3: {"classification": BoundaryClass.SOFT},
            },
        )
        result = LogicalGroupBuilder().build(elements, signal_set(elements), boundaries)
        self.assertEqual(len(result.subdocuments), 2)
        self.assertEqual(result.subdocuments[0].element_ids, ("t0", "p0"))
        self.assertEqual(result.subdocuments[1].element_ids, ("t1", "p1"))
        self.assertEqual(result.subdocuments[0].source, StructureSource.INFERRED)

    def test_one_title_does_not_create_subdocument(self) -> None:
        elements = (
            element("t0", 0, ElementType.TITLE, "Only title"),
            element("p0", 1, ElementType.PARAGRAPH),
        )
        result = LogicalGroupBuilder().build(
            elements, signal_set(elements), boundary_set(elements)
        )
        self.assertEqual(result.subdocuments, ())

    def test_invalid_boundary_alignment_is_rejected(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.PARAGRAPH),
        )
        bad = BoundarySet(
            element_count=2,
            signal_version="1",
            policy=BoundaryPolicy(),
            boundaries=(
                BoundaryDecision(
                    id="b",
                    left_element_id="e1",
                    right_element_id="e0",
                    classification=BoundaryClass.NONE,
                    score=0.0,
                ),
            ),
        )
        with self.assertRaises(GroupingError):
            LogicalGroupBuilder().build(elements, signal_set(elements), bad)

    def test_policy_can_stop_merging_soft_boundaries(self) -> None:
        elements = (
            element("p0", 0, ElementType.PARAGRAPH),
            element("p1", 1, ElementType.PARAGRAPH),
        )
        boundaries = boundary_set(
            elements,
            overrides={0: {"classification": BoundaryClass.SOFT}},
        )
        result = LogicalGroupBuilder(
            GroupingPolicy(merge_soft_boundaries=False)
        ).build(elements, signal_set(elements), boundaries)
        self.assertEqual(
            [unit.element_ids for unit in result.logical_units],
            [("p0",), ("p1",)],
        )

    def test_same_input_is_deterministic(self) -> None:
        elements = (
            element("q", 0, ElementType.QUESTION),
            element("a", 1, ElementType.ANSWER),
            element("p", 2, ElementType.PARAGRAPH),
        )
        boundaries = boundary_set(
            elements,
            overrides={
                0: {
                    "classification": BoundaryClass.NONE,
                    "integrity_guard": BoundaryIntegrityGuard.QA_PAIR,
                },
                1: {"classification": BoundaryClass.HARD},
            },
        )
        builder = LogicalGroupBuilder()
        first = builder.build(elements, signal_set(elements), boundaries)
        second = builder.build(elements, signal_set(elements), boundaries)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
