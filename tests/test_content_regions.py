from __future__ import annotations

import unittest

from source_understanding.profiling.content_profiler import ContentCategory
from source_understanding.profiling.regions import ContentRegionSegmenter
from source_understanding.schemas.context import ContextNode, StructureMode, StructureSource
from source_understanding.schemas.document import DocumentStructure
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.hierarchy import (
    ElementContextAssignment,
    HierarchyPolicy,
    HierarchyResult,
)
from source_understanding.structure.region_routing import RegionRouter, RegionRoutingError


def element(element_id: str, order: int, element_type: ElementType, text: str) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def hierarchy(
    elements: tuple[Element, ...],
    *,
    nodes: tuple[ContextNode, ...] = (),
    structure: DocumentStructure | None = None,
) -> HierarchyResult:
    assignments = []
    active: list[str] = []
    anchored = {node.attributes.get("anchor_element_id"): node for node in nodes}
    node_by_id = {node.id: node for node in nodes}
    for item in elements:
        node = anchored.get(item.id)
        if node is not None:
            if node.parent_id is None:
                active = [node.id]
            else:
                parent_chain = []
                current = node.parent_id
                while current is not None:
                    parent_chain.append(current)
                    current = node_by_id[current].parent_id
                active = [*reversed(parent_chain), node.id]
        assignments.append(
            ElementContextAssignment(
                element_id=item.id,
                context_node_ids=tuple(active),
            )
        )
    return HierarchyResult(
        element_count=len(elements),
        signal_version="1",
        boundary_version="1",
        policy=HierarchyPolicy(),
        context_nodes=nodes,
        assignments=tuple(assignments),
        structure=structure if structure is not None else DocumentStructure(),
    )


class ContentRegionTests(unittest.TestCase):
    def test_segments_contiguous_categories_and_covers_every_element(self) -> None:
        elements = (
            element("e1", 0, ElementType.PARAGRAPH, "Intro"),
            element("e2", 1, ElementType.SEPARATOR, "---"),
            element("e3", 2, ElementType.CODE, "print('x')"),
            element("e4", 3, ElementType.CODE, "print('y')"),
            element("e5", 4, ElementType.QUESTION, "Why?"),
            element("e6", 5, ElementType.ANSWER, "Because."),
        )
        result = ContentRegionSegmenter().segment(elements, hierarchy(elements))
        self.assertEqual(len(result.regions), 3)
        self.assertEqual(result.regions[0].element_ids, ("e1", "e2"))
        self.assertEqual(result.regions[1].element_ids, ("e3", "e4"))
        self.assertEqual(result.regions[2].element_ids, ("e5", "e6"))
        self.assertEqual(
            [region.metadata["routing_category"] for region in result.regions],
            [ContentCategory.NARRATIVE.value, ContentCategory.CODE.value, ContentCategory.QA.value],
        )
        self.assertEqual(
            [item for region in result.regions for item in region.element_ids],
            [item.id for item in elements],
        )
        self.assertFalse(result.regions[0].metadata["token_target_used"])

    def test_interaction_pattern_marks_document_mixed(self) -> None:
        elements = (
            element("e1", 0, ElementType.PARAGRAPH, "Background"),
            element("e2", 1, ElementType.QUESTION, "Question?"),
            element("e3", 2, ElementType.ANSWER, "Answer."),
        )
        result = ContentRegionSegmenter().segment(elements, hierarchy(elements))
        self.assertTrue(result.mixed)
        self.assertEqual(result.structure.mode, StructureMode.MIXED)
        self.assertEqual(
            result.diagnostics["mixed_reason"],
            "interaction_pattern_coexists_with_other_content",
        )

    def test_embedded_code_does_not_destroy_explicit_hierarchy(self) -> None:
        elements = (
            element("e1", 0, ElementType.HEADING, "Section"),
            element("e2", 1, ElementType.PARAGRAPH, "Explanation"),
            element("e3", 2, ElementType.CODE, "x = 1"),
            element("e4", 3, ElementType.PARAGRAPH, "More explanation"),
        )
        node = ContextNode(
            id="ctx1",
            type="HEADING",
            label="Section",
            level=1,
            source=StructureSource.EXPLICIT,
            confidence=0.95,
            attributes={"anchor_element_id": "e1"},
        )
        global_structure = DocumentStructure(
            mode=StructureMode.HIERARCHICAL,
            source=StructureSource.DERIVED,
            confidence=0.85,
        )
        result = ContentRegionSegmenter().segment(
            elements,
            hierarchy(elements, nodes=(node,), structure=global_structure),
        )
        self.assertFalse(result.mixed)
        self.assertEqual(result.structure.mode, StructureMode.HIERARCHICAL)
        self.assertEqual(
            result.diagnostics["mixed_reason"],
            "embedded_blocks_preserve_global_hierarchy",
        )

    def test_single_specialized_region_can_promote_unknown_to_local(self) -> None:
        elements = (
            element("e1", 0, ElementType.CODE, "x = 1"),
            element("e2", 1, ElementType.CODE, "y = 2"),
        )
        result = ContentRegionSegmenter().segment(elements, hierarchy(elements))
        self.assertEqual(len(result.regions), 1)
        self.assertEqual(result.regions[0].structure.mode, StructureMode.LOCAL)
        self.assertEqual(result.structure.mode, StructureMode.LOCAL)

    def test_all_bridge_material_is_preserved_in_one_region(self) -> None:
        elements = (
            element("e1", 0, ElementType.HEADER, "Header"),
            element("e2", 1, ElementType.SEPARATOR, "---"),
            element("e3", 2, ElementType.PAGE_NUMBER, "1"),
        )
        result = ContentRegionSegmenter().segment(elements, hierarchy(elements))
        self.assertEqual(len(result.regions), 1)
        self.assertEqual(result.regions[0].element_ids, ("e1", "e2", "e3"))
        self.assertEqual(result.structure.mode, StructureMode.UNKNOWN)

    def test_region_ids_are_deterministic(self) -> None:
        elements = (
            element("e1", 0, ElementType.PARAGRAPH, "A"),
            element("e2", 1, ElementType.CODE, "x = 1"),
        )
        builder = ContentRegionSegmenter()
        first = builder.segment(elements, hierarchy(elements))
        second = builder.segment(elements, hierarchy(elements))
        self.assertEqual(first, second)


class RegionRouterTests(unittest.TestCase):
    def test_assigns_region_id_without_changing_unit_membership(self) -> None:
        elements = (
            element("e1", 0, ElementType.PARAGRAPH, "A"),
            element("e2", 1, ElementType.CODE, "x = 1"),
        )
        region_result = ContentRegionSegmenter().segment(elements, hierarchy(elements))
        grouping = GroupingResult(
            element_count=2,
            signal_version="1",
            boundary_version="1",
            policy=GroupingPolicy(),
            logical_units=(
                LogicalUnit(
                    id="lu1",
                    type=LogicalUnitType.TEXT_BLOCK,
                    element_ids=("e1",),
                    source=StructureSource.DERIVED,
                    confidence=0.8,
                ),
                LogicalUnit(
                    id="lu2",
                    type=LogicalUnitType.CODE_BLOCK,
                    element_ids=("e2",),
                    source=StructureSource.DERIVED,
                    confidence=0.8,
                ),
            ),
        )
        routed, routed_hierarchy = RegionRouter().apply(
            grouping,
            hierarchy(elements),
            region_result,
        )
        self.assertEqual(routed.logical_units[0].element_ids, ("e1",))
        self.assertEqual(routed.logical_units[1].element_ids, ("e2",))
        self.assertEqual(routed.logical_units[0].region_id, region_result.regions[0].id)
        self.assertEqual(routed.logical_units[1].region_id, region_result.regions[1].id)
        self.assertEqual(routed_hierarchy.structure, region_result.structure)

    def test_rejects_logical_unit_crossing_regions(self) -> None:
        elements = (
            element("e1", 0, ElementType.PARAGRAPH, "A"),
            element("e2", 1, ElementType.CODE, "x = 1"),
        )
        region_result = ContentRegionSegmenter().segment(elements, hierarchy(elements))
        grouping = GroupingResult(
            element_count=2,
            signal_version="1",
            boundary_version="1",
            policy=GroupingPolicy(),
            logical_units=(
                LogicalUnit(
                    id="lu1",
                    type=LogicalUnitType.TEXT_BLOCK,
                    element_ids=("e1", "e2"),
                    source=StructureSource.DERIVED,
                    confidence=0.8,
                ),
            ),
        )
        with self.assertRaisesRegex(RegionRoutingError, "crosses content region"):
            RegionRouter().apply(grouping, hierarchy(elements), region_result)


if __name__ == "__main__":
    unittest.main()
