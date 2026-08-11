from __future__ import annotations

import unittest

from source_understanding.profiling.regions import ContentRegionSegmenter
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import DocumentStructure
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryDecision,
    BoundaryPolicy,
    BoundarySet,
)
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.hierarchy import (
    ElementContextAssignment,
    HierarchyPolicy,
    HierarchyResult,
)
from source_understanding.structure.integrity import IntegrityGroupConsolidator
from source_understanding.structure.region_routing import RegionRouter


def _list_item(
    element_id: str,
    order: int,
    text: str,
    *,
    integrity_group_id: str,
    numbering_id: str,
    level: int,
    number_format: str = "decimal",
) -> Element:
    return Element(
        id=element_id,
        type=ElementType.LIST_ITEM,
        order=order,
        raw_text=text,
        normalized_text=text,
        attributes={
            "opc_part": "word/document.xml",
            SOURCE_ZONE_ATTRIBUTE: "body",
            INTEGRITY_GROUP_ID_ATTRIBUTE: integrity_group_id,
            "numbering_id": numbering_id,
            "numbering_level": level,
            "number_format": number_format,
        },
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def _separator(order: int, *, kind: str = "section_break") -> Element:
    return Element(
        id="sep",
        type=ElementType.SEPARATOR,
        order=order,
        raw_text=None,
        normalized_text=None,
        attributes={
            "opc_part": "word/document.xml",
            SOURCE_ZONE_ATTRIBUTE: "body",
            "separator_kind": kind,
        },
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def _boundaries(elements: tuple[Element, ...]) -> BoundarySet:
    return BoundarySet(
        element_count=len(elements),
        signal_version="3",
        policy=BoundaryPolicy(),
        boundaries=tuple(
            BoundaryDecision(
                id=f"b{index}",
                left_element_id=elements[index].id,
                right_element_id=elements[index + 1].id,
                classification=BoundaryClass.HARD,
                score=1.0,
            )
            for index in range(len(elements) - 1)
        ),
    )


def _grouping(elements: tuple[Element, ...]) -> GroupingResult:
    separator = next(item for item in elements if item.type == ElementType.SEPARATOR)
    return GroupingResult(
        element_count=len(elements),
        signal_version="3",
        boundary_version="2",
        policy=GroupingPolicy(),
        logical_units=(
            LogicalUnit(
                id="separator-unit",
                type=LogicalUnitType.TEXT_BLOCK,
                element_ids=(separator.id,),
                source=StructureSource.DERIVED,
                confidence=0.7,
            ),
        ),
        ungrouped_element_ids=tuple(
            item.id for item in elements if item.id != separator.id
        ),
    )


def _hierarchy(elements: tuple[Element, ...]) -> HierarchyResult:
    return HierarchyResult(
        element_count=len(elements),
        signal_version="3",
        boundary_version="2",
        policy=HierarchyPolicy(),
        context_nodes=(),
        assignments=tuple(
            ElementContextAssignment(element_id=item.id, context_node_ids=())
            for item in elements
        ),
        structure=DocumentStructure(),
    )


class SectionBreakListContinuityTests(unittest.TestCase):
    def test_same_native_sequence_merges_across_section_break_without_absorbing_separator(self) -> None:
        elements = (
            _list_item(
                "left",
                0,
                "15 Governing Law and Jurisdiction",
                integrity_group_id="group-a",
                numbering_id="1",
                level=0,
            ),
            _separator(1),
            _list_item(
                "right",
                2,
                "15.1 This Agreement is governed by English law.",
                integrity_group_id="group-b",
                numbering_id="1",
                level=1,
            ),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            _boundaries(elements),
            _grouping(elements),
        )

        lists = [
            unit for unit in consolidated.logical_units if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].element_ids, ("left", "right"))
        self.assertNotIn("sep", lists[0].element_ids)
        self.assertEqual(report.merged_native_list_group_count, 1)
        self.assertEqual(
            lists[0].metadata["source_native_integrity_group_ids"],
            ["group-a", "group-b"],
        )
        self.assertEqual(elements[1].type, ElementType.SEPARATOR)

        regions = ContentRegionSegmenter().segment(
            elements,
            _hierarchy(elements),
            consolidated,
        )
        self.assertEqual(len(regions.regions), 1)
        self.assertEqual(regions.regions[0].element_ids, ("left", "sep", "right"))
        routed, _ = RegionRouter().apply(
            consolidated,
            _hierarchy(elements),
            regions,
        )
        routed_list = next(
            unit for unit in routed.logical_units if unit.type == LogicalUnitType.LIST_GROUP
        )
        self.assertEqual(routed_list.region_id, regions.regions[0].id)

    def test_different_native_numbering_sequence_does_not_merge(self) -> None:
        elements = (
            _list_item(
                "left", 0, "Section", integrity_group_id="group-a", numbering_id="1", level=0
            ),
            _separator(1),
            _list_item(
                "right", 2, "New list", integrity_group_id="group-b", numbering_id="2", level=0
            ),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            _boundaries(elements),
            _grouping(elements),
        )
        lists = [
            unit for unit in consolidated.logical_units if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual([unit.element_ids for unit in lists], [("left",), ("right",)])
        self.assertEqual(report.merged_native_list_group_count, 0)

    def test_other_separator_kind_does_not_merge(self) -> None:
        elements = (
            _list_item(
                "left", 0, "Section", integrity_group_id="group-a", numbering_id="1", level=0
            ),
            _separator(1, kind="source_zone_boundary"),
            _list_item(
                "right", 2, "Continuation", integrity_group_id="group-b", numbering_id="1", level=1
            ),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements,
            _boundaries(elements),
            _grouping(elements),
        )
        lists = [
            unit for unit in consolidated.logical_units if unit.type == LogicalUnitType.LIST_GROUP
        ]
        self.assertEqual([unit.element_ids for unit in lists], [("left",), ("right",)])
        self.assertEqual(report.merged_native_list_group_count, 0)


if __name__ == "__main__":
    unittest.main()
