from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.element import (
    Element,
    ElementConfidence,
    ElementType,
    Provenance,
)
from source_understanding.source_attributes import HEADING_LEVEL_ATTRIBUTE
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryDecision,
    BoundaryPolicy,
    BoundaryReason,
    BoundarySet,
)
from source_understanding.structure.hierarchy import HierarchyBuilder
from source_understanding.structure.signals import StructureSignalExtractor


def _element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str,
    *,
    heading_level: int | None = None,
) -> Element:
    attributes: dict[str, object] = {}
    if heading_level is not None:
        attributes[HEADING_LEVEL_ATTRIBUTE] = heading_level
    return Element(
        id=element_id,
        order=order,
        type=element_type,
        raw_text=text,
        attributes=attributes,
        confidence=ElementConfidence(),
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def _boundaries(
    elements: tuple[Element, ...],
    *,
    heading_ids: tuple[str, ...],
) -> BoundarySet:
    starts = set(heading_ids)
    decisions = []
    for index, (left, right) in enumerate(zip(elements, elements[1:])):
        explicit_start = right.id in starts
        decisions.append(
            BoundaryDecision(
                id=f"b{index}",
                left_element_id=left.id,
                right_element_id=right.id,
                classification=(
                    BoundaryClass.HARD if explicit_start else BoundaryClass.SOFT
                ),
                score=1.0 if explicit_start else 0.0,
                reasons=(
                    (BoundaryReason.EXPLICIT_STRUCTURE_START,)
                    if explicit_start
                    else ()
                ),
            )
        )
    return BoundarySet(
        element_count=len(elements),
        signal_version="3",
        policy=BoundaryPolicy(),
        boundaries=tuple(decisions),
    )


class HierarchyCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = HierarchyBuilder()

    def test_leading_heading_before_navigation_block_becomes_document_root(self):
        elements = (
            _element("title", 0, ElementType.HEADING, "Policy", heading_level=1),
            _element("toc1", 1, ElementType.PARAGRAPH, "\tIntroduction\t2"),
            _element("toc2", 2, ElementType.PARAGRAPH, "\tScope\t3"),
            _element("toc3", 3, ElementType.PARAGRAPH, "\tReview\t4"),
            _element("h1", 4, ElementType.HEADING, "Introduction", heading_level=1),
            _element("p", 5, ElementType.PARAGRAPH, "Body"),
            _element("h2", 6, ElementType.HEADING, "Scope", heading_level=1),
        )
        before = tuple(item.model_dump(mode="python") for item in elements)
        signals = StructureSignalExtractor().extract(elements)
        result = self.builder.build(
            elements,
            signals,
            _boundaries(elements, heading_ids=("h1", "h2")),
        )

        self.assertEqual([node.level for node in result.context_nodes], [0, 1, 1])
        root, first_section, second_section = result.context_nodes
        self.assertEqual(root.type, "DOCUMENT_TITLE")
        self.assertEqual(root.source, StructureSource.INFERRED)
        self.assertEqual(first_section.parent_id, root.id)
        self.assertEqual(second_section.parent_id, root.id)
        self.assertEqual(result.structure.mode, StructureMode.HIERARCHICAL)
        self.assertEqual(
            root.attributes["level_source"],
            "INFERRED_NAVIGATION_PRECEDED_ROOT",
        )
        self.assertEqual(
            tuple(item.model_dump(mode="python") for item in elements),
            before,
        )

    def test_adjacent_heading_pair_forms_title_subtitle_and_normalizes_peer_levels(self):
        elements = (
            _element("title", 0, ElementType.HEADING, "Survey 2012", heading_level=4),
            _element("subtitle", 1, ElementType.HEADING, "Guidance", heading_level=4),
            _element("p0", 2, ElementType.PARAGRAPH, "Intro"),
            _element("s1", 3, ElementType.HEADING, "Data available", heading_level=4),
            _element("p1", 4, ElementType.PARAGRAPH, "Body"),
            _element("s2", 5, ElementType.HEADING, "Terms", heading_level=1),
        )
        signals = StructureSignalExtractor().extract(elements)
        result = self.builder.build(
            elements,
            signals,
            _boundaries(elements, heading_ids=("subtitle", "s1", "s2")),
        )

        self.assertEqual([node.level for node in result.context_nodes], [0, 1, 1, 1])
        root, subtitle, first_section, second_section = result.context_nodes
        self.assertEqual(root.type, "DOCUMENT_TITLE")
        self.assertEqual(subtitle.type, "DOCUMENT_SUBTITLE")
        self.assertEqual(subtitle.parent_id, root.id)
        self.assertEqual(first_section.parent_id, root.id)
        self.assertEqual(second_section.parent_id, root.id)
        self.assertEqual(second_section.attributes["source_heading_level"], 1)
        self.assertEqual(second_section.attributes["level_source"], "HEADING_LEVEL")

    def test_plain_peer_headings_without_root_evidence_remain_grouped(self):
        elements = (
            _element("h0", 0, ElementType.HEADING, "Introduction", heading_level=1),
            _element("p0", 1, ElementType.PARAGRAPH, "Body"),
            _element("h1", 2, ElementType.HEADING, "Methods", heading_level=1),
            _element("p1", 3, ElementType.PARAGRAPH, "Body"),
            _element("h2", 4, ElementType.HEADING, "Results", heading_level=1),
        )
        signals = StructureSignalExtractor().extract(elements)
        result = self.builder.build(
            elements,
            signals,
            _boundaries(elements, heading_ids=("h1", "h2")),
        )

        self.assertEqual([node.level for node in result.context_nodes], [1, 1, 1])
        self.assertTrue(all(node.parent_id is None for node in result.context_nodes))
        self.assertEqual(result.structure.mode, StructureMode.GROUPED)
        self.assertEqual(result.context_nodes[0].type, ElementType.HEADING.value)


if __name__ == "__main__":
    unittest.main()
