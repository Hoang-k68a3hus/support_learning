from __future__ import annotations

import unittest
from enum import StrEnum
from types import SimpleNamespace

from source_understanding.profiling.content_profiler import (
    ContentCategory,
    content_category_for_element,
)
from source_understanding.profiling.regions import ContentRegionSegmenter
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import DocumentStructure
from source_understanding.schemas.element import Element, ElementType, Provenance, StyleInfo
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.hierarchy import (
    ElementContextAssignment,
    HierarchyPolicy,
    HierarchyResult,
)
from source_understanding.structure.integrity import IntegrityGroupConsolidator
from source_understanding.structure.region_routing import RegionRouter


class BoundaryClass(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


def _element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str | None,
    *,
    group_id: str | None = None,
    level: int | None = None,
    number_format: str | None = None,
    indentation: float | None = None,
) -> Element:
    attributes: dict[str, object] = {
        SOURCE_ZONE_ATTRIBUTE: "body",
        "opc_part": "word/document.xml",
    }
    if group_id is not None:
        attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] = group_id
        attributes["numbering_id"] = group_id
    if level is not None:
        attributes["numbering_level"] = level
    if number_format is not None:
        attributes["number_format"] = number_format
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        normalized_text=text,
        attributes=attributes,
        style=None if indentation is None else StyleInfo(indentation=indentation),
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def _boundaries(
    elements: tuple[Element, ...],
    classes: tuple[BoundaryClass, ...] | None = None,
):
    resolved = classes or (BoundaryClass.NONE,) * max(0, len(elements) - 1)
    return SimpleNamespace(
        element_count=len(elements),
        boundaries=tuple(
            SimpleNamespace(
                id=f"b{index}",
                left_element_id=elements[index].id,
                right_element_id=elements[index + 1].id,
                classification=classification,
                reasons=(),
            )
            for index, classification in enumerate(resolved)
        ),
    )


def _grouping(
    elements: tuple[Element, ...],
    *,
    blank_id: str | None = None,
) -> GroupingResult:
    units = ()
    ungrouped = tuple(item.id for item in elements)
    if blank_id is not None:
        units = (
            LogicalUnit(
                id="blank-text",
                type=LogicalUnitType.TEXT_BLOCK,
                element_ids=(blank_id,),
                source=StructureSource.DERIVED,
                confidence=0.7,
            ),
        )
        ungrouped = tuple(item.id for item in elements if item.id != blank_id)
    return GroupingResult(
        element_count=len(elements),
        signal_version="1",
        boundary_version="1",
        policy=GroupingPolicy(),
        logical_units=units,
        ungrouped_element_ids=ungrouped,
    )


def _hierarchy(elements: tuple[Element, ...]) -> HierarchyResult:
    return HierarchyResult(
        element_count=len(elements),
        signal_version="1",
        boundary_version="1",
        policy=HierarchyPolicy(),
        context_nodes=(),
        assignments=tuple(
            ElementContextAssignment(element_id=item.id, context_node_ids=())
            for item in elements
        ),
        structure=DocumentStructure(),
    )


class ListFragmentContinuityTests(unittest.TestCase):
    def test_blank_paragraph_remains_narrative_without_structural_override(self) -> None:
        blank = _element("blank", 0, ElementType.PARAGRAPH, None)
        whitespace = _element("space", 1, ElementType.PARAGRAPH, "  \t")
        narrative = _element("text", 2, ElementType.PARAGRAPH, "Body")

        self.assertEqual(content_category_for_element(blank), ContentCategory.NARRATIVE)
        self.assertEqual(content_category_for_element(whitespace), ContentCategory.NARRATIVE)
        self.assertEqual(content_category_for_element(narrative), ContentCategory.NARRATIVE)
        self.assertEqual(blank.type, ElementType.PARAGRAPH)

    def test_native_list_fragments_merge_across_blank_spacer_and_route_once(self) -> None:
        elements = (
            _element(
                "i1",
                0,
                ElementType.LIST_ITEM,
                "First",
                group_id="list-a",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
            _element("blank", 1, ElementType.PARAGRAPH, None),
            _element(
                "i2",
                2,
                ElementType.LIST_ITEM,
                "Second",
                group_id="list-b",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
        )
        boundaries = _boundaries(elements)
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            boundaries,
            _grouping(elements, blank_id="blank"),
        )

        list_units = [
            unit
            for unit in consolidated.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual(len(list_units), 1)
        self.assertEqual(list_units[0].element_ids, ("i1", "i2"))
        self.assertNotIn("blank", list_units[0].element_ids)
        self.assertEqual(
            list_units[0].metadata["source_native_integrity_group_ids"],
            ["list-a", "list-b"],
        )
        self.assertEqual(report.merged_native_list_group_count, 1)

        region_result = ContentRegionSegmenter().segment(
            elements,
            _hierarchy(elements),
            consolidated,
        )
        self.assertEqual(len(region_result.regions), 1)
        self.assertEqual(
            region_result.regions[0].metadata["routing_category"],
            ContentCategory.LIST.value,
        )
        self.assertEqual(
            region_result.regions[0].element_ids,
            ("i1", "blank", "i2"),
        )
        self.assertEqual(region_result.diagnostics["list_bridge_override_count"], 1)
        self.assertEqual(
            region_result.regions[0].metadata["grouping_routing_overrides"]["blank"][
                "routing_role"
            ],
            "list_bridge_blank_paragraph",
        )
        self.assertEqual(
            content_category_for_element(elements[1]),
            ContentCategory.NARRATIVE,
        )

        routed, _ = RegionRouter().apply(
            consolidated,
            _hierarchy(elements),
            region_result,
        )
        routed_list = next(
            unit
            for unit in routed.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        )
        self.assertEqual(routed_list.element_ids, ("i1", "i2"))
        self.assertEqual(routed_list.region_id, region_result.regions[0].id)
        routed_blank = next(
            unit for unit in routed.logical_units if unit.id == "blank-text"
        )
        self.assertEqual(routed_blank.region_id, region_result.regions[0].id)

    def test_nonblank_gap_prevents_native_list_fragment_merge(self) -> None:
        elements = (
            _element(
                "i1",
                0,
                ElementType.LIST_ITEM,
                "First",
                group_id="list-a",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
            _element("body", 1, ElementType.PARAGRAPH, "New section"),
            _element(
                "i2",
                2,
                ElementType.LIST_ITEM,
                "Second",
                group_id="list-b",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            _boundaries(elements),
            _grouping(elements, blank_id="body"),
        )
        list_units = [
            unit
            for unit in consolidated.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual(
            [unit.element_ids for unit in list_units],
            [("i1",), ("i2",)],
        )
        self.assertEqual(report.merged_native_list_group_count, 0)

    def test_hard_boundary_prevents_native_list_fragment_merge(self) -> None:
        elements = (
            _element(
                "i1",
                0,
                ElementType.LIST_ITEM,
                "First",
                group_id="list-a",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
            _element(
                "i2",
                1,
                ElementType.LIST_ITEM,
                "Second",
                group_id="list-b",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            _boundaries(elements, (BoundaryClass.HARD,)),
            _grouping(elements),
        )
        list_units = [
            unit
            for unit in consolidated.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual(
            [unit.element_ids for unit in list_units],
            [("i1",), ("i2",)],
        )
        self.assertEqual(report.merged_native_list_group_count, 0)

    def test_blank_gap_requires_compatible_numbering_and_indentation(self) -> None:
        elements = (
            _element(
                "i1",
                0,
                ElementType.LIST_ITEM,
                "First",
                group_id="list-a",
                level=0,
                number_format="bullet",
                indentation=720.0,
            ),
            _element("blank", 1, ElementType.PARAGRAPH, None),
            _element(
                "i2",
                2,
                ElementType.LIST_ITEM,
                "Second",
                group_id="list-b",
                level=1,
                number_format="bullet",
                indentation=1440.0,
            ),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            _boundaries(elements),
            _grouping(elements, blank_id="blank"),
        )
        list_units = [
            unit
            for unit in consolidated.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual(
            [unit.element_ids for unit in list_units],
            [("i1",), ("i2",)],
        )
        self.assertEqual(report.merged_native_list_group_count, 0)


if __name__ == "__main__":
    unittest.main()
