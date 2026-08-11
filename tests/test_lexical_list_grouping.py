from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnitType
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryDecision,
    BoundaryPolicy,
    BoundarySet,
)
from source_understanding.structure.grouping import LogicalGroupBuilder
from source_understanding.structure.signals import (
    StructureSignal,
    StructureSignalKind,
    StructureSignalSet,
)


def element(
    element_id: str,
    order: int,
    text: str | None,
    *,
    element_type: ElementType = ElementType.PARAGRAPH,
) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def signals(elements: tuple[Element, ...], marker_ids: tuple[str, ...]) -> StructureSignalSet:
    output = [
        StructureSignal(
            id=f"type_{item.id}",
            kind=StructureSignalKind.ELEMENT_TYPE,
            element_ids=(item.id,),
            source=StructureSource.EXPLICIT,
            text_value=item.type.value,
        )
        for item in elements
    ]
    for item in elements:
        if item.id in marker_ids:
            marker = (item.text or "").strip().split(maxsplit=1)[0]
            output.append(
                StructureSignal(
                    id=f"marker_{item.id}",
                    kind=StructureSignalKind.NUMBERING_MARKER,
                    element_ids=(item.id,),
                    source=StructureSource.INFERRED,
                    text_value=marker,
                )
            )
    return StructureSignalSet(
        version="3",
        element_count=len(elements),
        signals=tuple(output),
    )


def boundaries(
    elements: tuple[Element, ...],
    *,
    hard_after: int | None = None,
) -> BoundarySet:
    decisions = []
    for index in range(len(elements) - 1):
        decisions.append(
            BoundaryDecision(
                id=f"b{index}",
                left_element_id=elements[index].id,
                right_element_id=elements[index + 1].id,
                classification=(
                    BoundaryClass.HARD if hard_after == index else BoundaryClass.NONE
                ),
                score=0.0,
            )
        )
    return BoundarySet(
        element_count=len(elements),
        signal_version="3",
        policy=BoundaryPolicy(),
        boundaries=tuple(decisions),
    )


def list_groups(result) -> list:
    return [
        unit for unit in result.logical_units if unit.type == LogicalUnitType.LIST_GROUP
    ]


class LexicalListGroupingTests(unittest.TestCase):
    def test_parenthesized_enumeration_groups_without_intro_clause(self) -> None:
        elements = (
            element("p1", 0, "(1) First party"),
            element("p2", 1, "(2) Second party"),
        )
        result = LogicalGroupBuilder().build(
            elements,
            signals(elements, ()),
            boundaries(elements),
        )
        groups = list_groups(result)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].element_ids, ("p1", "p2"))
        self.assertEqual(groups[0].source, StructureSource.INFERRED)
        self.assertEqual(groups[0].metadata["evidence_rule"], "parenthesized_enumeration")
        self.assertTrue(all(item.type == ElementType.PARAGRAPH for item in elements))

    def test_alpha_sequence_requires_native_list_intro_and_keeps_blank_bridge(self) -> None:
        elements = (
            element(
                "intro",
                0,
                "The contractor shall provide:",
                element_type=ElementType.LIST_ITEM,
            ),
            element("a", 1, "a) first"),
            element("b", 2, "b) second"),
            element("blank", 3, None),
            element("d", 4, "d) fourth"),
        )
        result = LogicalGroupBuilder().build(
            elements,
            signals(elements, ("a", "b", "d")),
            boundaries(elements),
        )
        groups = list_groups(result)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].element_ids, ("a", "b", "blank", "d"))
        self.assertEqual(
            groups[0].metadata["evidence_rule"],
            "introduced_native_list_subsequence",
        )
        self.assertEqual(groups[0].metadata["blank_bridge_count"], 1)
        self.assertTrue(
            all(item.type == ElementType.PARAGRAPH for item in elements[1:])
        )

    def test_plain_paragraph_colon_is_not_enough_to_promote_alpha_sequence(self) -> None:
        elements = (
            element("intro", 0, "The survey categories are:"),
            element("a", 1, "a) Primary"),
            element("b", 2, "b) Manufacturing"),
            element("c", 3, "c) Construction"),
        )
        result = LogicalGroupBuilder().build(
            elements,
            signals(elements, ("a", "b", "c")),
            boundaries(elements),
        )
        self.assertEqual(list_groups(result), [])

    def test_unintroduced_alpha_enumeration_is_not_promoted(self) -> None:
        elements = (
            element("intro", 0, "The survey covers all sectors."),
            element("a", 1, "a) Primary"),
            element("b", 2, "b) Manufacturing"),
            element("c", 3, "c) Construction"),
        )
        result = LogicalGroupBuilder().build(
            elements,
            signals(elements, ("a", "b", "c")),
            boundaries(elements),
        )
        self.assertEqual(list_groups(result), [])

    def test_single_marker_is_not_a_list_group(self) -> None:
        elements = (
            element(
                "intro",
                0,
                "Choose:",
                element_type=ElementType.LIST_ITEM,
            ),
            element("a", 1, "a) only"),
        )
        result = LogicalGroupBuilder().build(
            elements,
            signals(elements, ("a",)),
            boundaries(elements),
        )
        self.assertEqual(list_groups(result), [])

    def test_hard_boundary_prevents_lexical_group(self) -> None:
        elements = (
            element(
                "intro",
                0,
                "Choose:",
                element_type=ElementType.LIST_ITEM,
            ),
            element("a", 1, "a) first"),
            element("b", 2, "b) second"),
        )
        result = LogicalGroupBuilder().build(
            elements,
            signals(elements, ("a", "b")),
            boundaries(elements, hard_after=1),
        )
        self.assertEqual(list_groups(result), [])


if __name__ == "__main__":
    unittest.main()
