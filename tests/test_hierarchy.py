from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.element import (
    Element,
    ElementConfidence,
    ElementType,
    Provenance,
)
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryDecision,
    BoundaryPolicy,
    BoundaryReason,
    BoundarySet,
)
from source_understanding.structure.hierarchy import HierarchyBuilder, HierarchyError
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
    type_confidence: float | None = None,
) -> Element:
    return Element(
        id=element_id,
        order=order,
        type=element_type,
        raw_text=text,
        confidence=ElementConfidence(type=type_confidence),
        provenance=Provenance(source=source, extractor="test"),
    )


def signal_set(
    elements: tuple[Element, ...],
    extra: tuple[StructureSignal, ...] = (),
) -> StructureSignalSet:
    base = tuple(
        StructureSignal(
            id=f"type_{item.id}",
            kind=StructureSignalKind.ELEMENT_TYPE,
            element_ids=(item.id,),
            source=item.provenance.source,
            confidence=item.confidence.type,
            text_value=item.type.value,
        )
        for item in elements
    )
    return StructureSignalSet(
        element_count=len(elements),
        signals=base + extra,
    )


def boundary_set(
    elements: tuple[Element, ...],
    classes: tuple[BoundaryClass, ...] | None = None,
    *,
    explicit_starts: tuple[str, ...] = (),
) -> BoundarySet:
    resolved = classes or (BoundaryClass.SOFT,) * max(0, len(elements) - 1)
    boundaries = tuple(
        BoundaryDecision(
            id=f"b_{index}",
            left_element_id=elements[index].id,
            right_element_id=elements[index + 1].id,
            classification=classification,
            score=0.0,
            reasons=(BoundaryReason.EXPLICIT_STRUCTURE_START,)
            if elements[index + 1].id in explicit_starts
            else (),
        )
        for index, classification in enumerate(resolved)
    )
    return BoundarySet(
        element_count=len(elements),
        signal_version="1",
        policy=BoundaryPolicy(),
        boundaries=boundaries,
    )


class HierarchyBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = HierarchyBuilder()

    def test_no_headings_stays_unknown(self) -> None:
        elements = (
            element("p0", 0, ElementType.PARAGRAPH),
            element("p1", 1, ElementType.PARAGRAPH),
        )
        result = self.builder.build(elements, signal_set(elements), boundary_set(elements))
        self.assertEqual(result.structure.mode, StructureMode.UNKNOWN)
        self.assertEqual(result.context_nodes, ())
        self.assertEqual([item.context_node_ids for item in result.assignments], [(), ()])

    def test_single_explicit_heading_is_local_context(self) -> None:
        elements = (
            element("h", 0, ElementType.HEADING, "Introduction"),
            element("p", 1, ElementType.PARAGRAPH),
        )
        result = self.builder.build(elements, signal_set(elements), boundary_set(elements))
        node = result.context_nodes[0]
        self.assertEqual(result.structure.mode, StructureMode.LOCAL)
        self.assertEqual(node.level, 1)
        self.assertEqual(node.source, StructureSource.EXPLICIT)
        self.assertEqual(result.assignments[1].context_node_ids, (node.id,))

    def test_title_and_heading_form_hierarchy(self) -> None:
        elements = (
            element("title", 0, ElementType.TITLE, "Document"),
            element("heading", 1, ElementType.HEADING, "Section"),
        )
        result = self.builder.build(
            elements,
            signal_set(elements),
            boundary_set(
                elements,
                (BoundaryClass.HARD,),
                explicit_starts=("heading",),
            ),
        )
        self.assertEqual(result.structure.mode, StructureMode.HIERARCHICAL)
        self.assertEqual(result.context_nodes[0].level, 0)
        self.assertEqual(result.context_nodes[1].parent_id, result.context_nodes[0].id)

    def test_numeric_numbering_builds_levels_without_synthetic_nodes(self) -> None:
        elements = (
            element("h1", 0, ElementType.HEADING, "1 Root"),
            element("h2", 1, ElementType.HEADING, "1.1 Child"),
            element("h3", 2, ElementType.HEADING, "1.1.1 Leaf"),
            element("h4", 3, ElementType.HEADING, "1.2 Peer"),
        )
        numbering = tuple(
            StructureSignal(
                id=f"n_{item.id}",
                kind=StructureSignalKind.NUMBERING_MARKER,
                element_ids=(item.id,),
                source=StructureSource.INFERRED,
                text_value=marker,
            )
            for item, marker in zip(elements, ("1.", "1.1", "1.1.1", "1.2"))
        )
        result = self.builder.build(
            elements,
            signal_set(elements, numbering),
            boundary_set(
                elements,
                (BoundaryClass.HARD,) * 3,
                explicit_starts=("h2", "h3", "h4"),
            ),
        )
        nodes = result.context_nodes
        self.assertEqual([node.level for node in nodes], [1, 2, 3, 2])
        self.assertEqual(nodes[1].parent_id, nodes[0].id)
        self.assertEqual(nodes[2].parent_id, nodes[1].id)
        self.assertEqual(nodes[3].parent_id, nodes[0].id)

    def test_peer_headings_are_grouped_not_multilevel_hierarchy(self) -> None:
        elements = (
            element("h0", 0, ElementType.HEADING, "A"),
            element("h1", 1, ElementType.HEADING, "B"),
        )
        result = self.builder.build(
            elements,
            signal_set(elements),
            boundary_set(
                elements,
                (BoundaryClass.HARD,),
                explicit_starts=("h1",),
            ),
        )
        self.assertEqual(result.structure.mode, StructureMode.GROUPED)
        self.assertTrue(all(node.parent_id is None for node in result.context_nodes))

    def test_inferred_heading_accepts_soft_boundary_and_stays_inferred(self) -> None:
        elements = (
            element("p", 0, ElementType.PARAGRAPH),
            element(
                "h",
                1,
                ElementType.HEADING,
                "Candidate",
                source=StructureSource.INFERRED,
            ),
        )
        result = self.builder.build(elements, signal_set(elements), boundary_set(elements))
        self.assertEqual(result.context_nodes[0].source, StructureSource.INFERRED)

    def test_numbering_on_paragraph_does_not_promote_structure(self) -> None:
        elements = (element("p", 0, ElementType.PARAGRAPH, "1.2 Not a heading"),)
        marker = StructureSignal(
            id="numbering",
            kind=StructureSignalKind.NUMBERING_MARKER,
            element_ids=("p",),
            source=StructureSource.INFERRED,
            text_value="1.2",
        )
        result = self.builder.build(
            elements,
            signal_set(elements, (marker,)),
            boundary_set(elements),
        )
        self.assertEqual(result.context_nodes, ())
        self.assertEqual(result.structure.mode, StructureMode.UNKNOWN)

    def test_context_paths_start_only_after_anchor(self) -> None:
        elements = (
            element("p0", 0, ElementType.PARAGRAPH),
            element("h", 1, ElementType.HEADING, "Heading"),
            element("p1", 2, ElementType.PARAGRAPH),
        )
        result = self.builder.build(
            elements,
            signal_set(elements),
            boundary_set(
                elements,
                (BoundaryClass.HARD, BoundaryClass.SOFT),
                explicit_starts=("h",),
            ),
        )
        self.assertEqual(result.assignments[0].context_node_ids, ())
        self.assertEqual(
            result.assignments[2].context_node_ids,
            (result.context_nodes[0].id,),
        )

    def test_explicit_heading_requires_hard_explicit_boundary(self) -> None:
        elements = (
            element("p", 0, ElementType.PARAGRAPH),
            element("h", 1, ElementType.HEADING, "Heading"),
        )
        with self.assertRaises(HierarchyError):
            self.builder.build(elements, signal_set(elements), boundary_set(elements))

    def test_blank_heading_does_not_invent_label(self) -> None:
        elements = (element("h", 0, ElementType.HEADING, "   "),)
        result = self.builder.build(elements, signal_set(elements), boundary_set(elements))
        self.assertEqual(result.context_nodes, ())

    def test_long_label_is_bounded_but_source_remains_in_element(self) -> None:
        elements = (element("h", 0, ElementType.HEADING, "x" * 3000),)
        result = self.builder.build(elements, signal_set(elements), boundary_set(elements))
        node = result.context_nodes[0]
        self.assertEqual(len(node.label), 2048)
        self.assertTrue(node.attributes["label_truncated"])
        self.assertEqual(len(elements[0].raw_text), 3000)

    def test_rejects_missing_type_signal_and_wrong_boundary_order(self) -> None:
        elements = (
            element("p", 0, ElementType.PARAGRAPH),
            element("h", 1, ElementType.HEADING, "Heading"),
        )
        with self.assertRaises(HierarchyError):
            self.builder.build(
                elements,
                StructureSignalSet(element_count=2, signals=()),
                boundary_set(
                    elements,
                    (BoundaryClass.HARD,),
                    explicit_starts=("h",),
                ),
            )

        wrong_boundaries = BoundarySet(
            element_count=2,
            signal_version="1",
            policy=BoundaryPolicy(),
            boundaries=(
                BoundaryDecision(
                    id="wrong",
                    left_element_id="h",
                    right_element_id="p",
                    classification=BoundaryClass.HARD,
                    score=0.0,
                ),
            ),
        )
        with self.assertRaises(HierarchyError):
            self.builder.build(elements, signal_set(elements), wrong_boundaries)

    def test_same_input_is_deterministic(self) -> None:
        elements = (
            element("h", 0, ElementType.HEADING, "Introduction"),
            element("p", 1, ElementType.PARAGRAPH),
        )
        signals = signal_set(elements)
        boundaries = boundary_set(elements)
        self.assertEqual(
            self.builder.build(elements, signals, boundaries),
            self.builder.build(elements, signals, boundaries),
        )


if __name__ == "__main__":
    unittest.main()
