from __future__ import annotations

import unittest

from source_understanding.profiling.content_profiler import ContentCategory
from source_understanding.profiling.regions import (
    ContentRegionSegmentationError,
    ContentRegionSegmenter,
)
from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.document import DocumentStructure
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.hierarchy import (
    ElementContextAssignment,
    HierarchyPolicy,
    HierarchyResult,
)


def element(element_id: str, order: int, element_type: ElementType, text: str) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def hierarchy(elements: tuple[Element, ...]) -> HierarchyResult:
    return HierarchyResult(
        element_count=len(elements),
        signal_version="2",
        boundary_version="2",
        policy=HierarchyPolicy(),
        assignments=tuple(
            ElementContextAssignment(element_id=item.id, context_node_ids=())
            for item in elements
        ),
        structure=DocumentStructure(),
    )


def grouping(
    elements: tuple[Element, ...],
    unit: LogicalUnit,
) -> GroupingResult:
    owned = set(unit.element_ids)
    return GroupingResult(
        element_count=len(elements),
        signal_version="2",
        boundary_version="2",
        policy=GroupingPolicy(),
        logical_units=(unit,),
        ungrouped_element_ids=tuple(
            item.id for item in elements if item.id not in owned
        ),
    )


class GroupingAwareRegionTests(unittest.TestCase):
    def test_lexical_qa_group_refines_routing_without_mutating_source_types(self) -> None:
        elements = (
            element("intro", 0, ElementType.PARAGRAPH, "Intro"),
            element("q", 1, ElementType.PARAGRAPH, "Q: Why?"),
            element("a", 2, ElementType.PARAGRAPH, "A: Because."),
            element("end", 3, ElementType.PARAGRAPH, "Closing"),
        )
        qa = LogicalUnit(
            id="qa",
            type=LogicalUnitType.QA_PAIR,
            element_ids=("q", "a"),
            source=StructureSource.INFERRED,
            confidence=0.8,
        )
        result = ContentRegionSegmenter().segment(
            elements,
            hierarchy(elements),
            grouping(elements, qa),
        )

        self.assertEqual(result.version, "3")
        self.assertEqual(len(result.regions), 3)
        self.assertEqual(
            [region.metadata["routing_category"] for region in result.regions],
            [
                ContentCategory.NARRATIVE.value,
                ContentCategory.QA.value,
                ContentCategory.NARRATIVE.value,
            ],
        )
        self.assertEqual(result.regions[1].element_ids, ("q", "a"))
        self.assertEqual(result.regions[1].dominant_type, ContentCategory.NARRATIVE.value)
        self.assertEqual(
            result.regions[1].profile[ContentCategory.NARRATIVE.value],
            1.0,
        )
        self.assertEqual(
            result.regions[1].metadata["segmentation_basis"],
            "contiguous_content_category_plus_structural_grouping",
        )
        self.assertEqual(
            result.regions[1].metadata["grouping_routing_override_element_ids"],
            ("q", "a"),
        )
        self.assertEqual(result.diagnostics["grouping_routing_override_count"], 2)
        self.assertEqual(result.structure.mode, StructureMode.MIXED)
        self.assertTrue(result.mixed)
        self.assertTrue(all(item.type == ElementType.PARAGRAPH for item in elements))

    def test_structural_routing_evidence_cannot_overwrite_conflicting_source_category(self) -> None:
        elements = (
            element("q", 0, ElementType.CODE, "Q: not actually a paragraph"),
            element("a", 1, ElementType.PARAGRAPH, "A: answer"),
        )
        malformed = LogicalUnit(
            id="qa",
            type=LogicalUnitType.QA_PAIR,
            element_ids=("q", "a"),
            source=StructureSource.INFERRED,
            confidence=0.8,
        )
        with self.assertRaisesRegex(
            ContentRegionSegmentationError,
            "conflicts with observed routing category",
        ):
            ContentRegionSegmenter().segment(
                elements,
                hierarchy(elements),
                grouping(elements, malformed),
            )

    def test_grouping_reference_outside_region_input_is_rejected(self) -> None:
        elements = (element("e1", 0, ElementType.PARAGRAPH, "Text"),)
        malformed = LogicalUnit(
            id="qa",
            type=LogicalUnitType.QA_PAIR,
            element_ids=("e1", "missing"),
            source=StructureSource.INFERRED,
            confidence=0.8,
        )
        grouped = GroupingResult(
            element_count=1,
            signal_version="2",
            boundary_version="2",
            policy=GroupingPolicy(),
            logical_units=(malformed,),
        )
        with self.assertRaisesRegex(
            ContentRegionSegmentationError,
            "references unknown elements",
        ):
            ContentRegionSegmenter().segment(
                elements,
                hierarchy(elements),
                grouped,
            )


if __name__ == "__main__":
    unittest.main()
