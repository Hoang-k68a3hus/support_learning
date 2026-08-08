from __future__ import annotations

import unittest
from enum import StrEnum
from types import SimpleNamespace

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.integrity import (
    IntegrityConsolidationError,
    IntegrityGroupConsolidator,
)


class BoundaryClass(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


def element(element_id: str, order: int, element_type: ElementType) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=element_id,
        normalized_text=element_id,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def boundaries(elements, classes=None):
    classes = classes or [BoundaryClass.NONE] * max(0, len(elements) - 1)
    decisions = tuple(
        SimpleNamespace(
            id=f"b{index}",
            left_element_id=elements[index].id,
            right_element_id=elements[index + 1].id,
            classification=classification,
        )
        for index, classification in enumerate(classes)
    )
    return SimpleNamespace(element_count=len(elements), boundaries=decisions)


def grouping(elements, units=(), ungrouped=()):
    return GroupingResult(
        element_count=len(elements),
        signal_version="1",
        boundary_version="1",
        policy=GroupingPolicy(),
        logical_units=units,
        ungrouped_element_ids=ungrouped,
    )


class IntegrityConsolidationTests(unittest.TestCase):
    def test_table_rows_and_cells_become_one_table_block(self):
        elements = (
            element("r1", 0, ElementType.TABLE_ROW),
            element("c1", 1, ElementType.TABLE_CELL),
            element("c2", 2, ElementType.TABLE_CELL),
            element("r2", 3, ElementType.TABLE_ROW),
        )
        result, report = IntegrityGroupConsolidator().consolidate(
            elements,
            boundaries(elements, [BoundaryClass.UNKNOWN] * 3),
            grouping(elements, ungrouped=tuple(item.id for item in elements)),
        )
        self.assertEqual(len(result.logical_units), 1)
        unit = result.logical_units[0]
        self.assertEqual(unit.type, LogicalUnitType.TABLE_BLOCK)
        self.assertEqual(unit.element_ids, ("r1", "c1", "c2", "r2"))
        self.assertEqual(result.ungrouped_element_ids, ())
        self.assertEqual(report.family_counts["table"], 1)
        self.assertFalse(unit.metadata["token_target_used"])

    def test_list_container_absorbs_items_but_second_container_starts_new_unit(self):
        elements = (
            element("l1", 0, ElementType.LIST),
            element("i1", 1, ElementType.LIST_ITEM),
            element("i2", 2, ElementType.LIST_ITEM),
            element("l2", 3, ElementType.LIST),
            element("i3", 4, ElementType.LIST_ITEM),
        )
        existing = (
            LogicalUnit(
                id="old_l1", type=LogicalUnitType.LIST_GROUP, element_ids=("l1",),
                source=StructureSource.DERIVED, confidence=0.95,
            ),
            LogicalUnit(
                id="old_l2", type=LogicalUnitType.LIST_GROUP, element_ids=("l2",),
                source=StructureSource.DERIVED, confidence=0.95,
            ),
        )
        result, report = IntegrityGroupConsolidator().consolidate(
            elements,
            boundaries(elements),
            grouping(elements, units=existing, ungrouped=("i1", "i2", "i3")),
        )
        self.assertEqual([unit.element_ids for unit in result.logical_units], [
            ("l1", "i1", "i2"), ("l2", "i3")
        ])
        self.assertEqual(set(report.replaced_unit_ids), {"old_l1", "old_l2"})

    def test_contiguous_code_singletons_are_replaced_by_one_code_block(self):
        elements = (
            element("c1", 0, ElementType.CODE),
            element("c2", 1, ElementType.CODE),
        )
        existing = tuple(
            LogicalUnit(
                id=f"old_{item.id}", type=LogicalUnitType.CODE_BLOCK,
                element_ids=(item.id,), source=StructureSource.DERIVED, confidence=0.95,
            )
            for item in elements
        )
        result, _ = IntegrityGroupConsolidator().consolidate(
            elements, boundaries(elements), grouping(elements, units=existing)
        )
        self.assertEqual(len(result.logical_units), 1)
        self.assertEqual(result.logical_units[0].element_ids, ("c1", "c2"))

    def test_hard_boundary_splits_same_integrity_family(self):
        elements = (
            element("f1", 0, ElementType.FORMULA),
            element("f2", 1, ElementType.FORMULA),
        )
        result, _ = IntegrityGroupConsolidator().consolidate(
            elements,
            boundaries(elements, [BoundaryClass.HARD]),
            grouping(elements, ungrouped=("f1", "f2")),
        )
        self.assertEqual([unit.element_ids for unit in result.logical_units], [("f1",), ("f2",)])

    def test_non_integrity_units_are_preserved(self):
        elements = (
            element("p1", 0, ElementType.PARAGRAPH),
            element("r1", 1, ElementType.TABLE_ROW),
            element("r2", 2, ElementType.TABLE_ROW),
        )
        text_unit = LogicalUnit(
            id="text", type=LogicalUnitType.TEXT_BLOCK, element_ids=("p1",),
            source=StructureSource.DERIVED, confidence=0.8,
        )
        result, _ = IntegrityGroupConsolidator().consolidate(
            elements,
            boundaries(elements, [BoundaryClass.HARD, BoundaryClass.NONE]),
            grouping(elements, units=(text_unit,), ungrouped=("r1", "r2")),
        )
        self.assertEqual(result.logical_units[0], text_unit)
        self.assertEqual(result.logical_units[1].type, LogicalUnitType.TABLE_BLOCK)

    def test_existing_cross_span_unit_is_rejected(self):
        elements = (
            element("r1", 0, ElementType.TABLE_ROW),
            element("p1", 1, ElementType.PARAGRAPH),
        )
        crossing = LogicalUnit(
            id="bad", type=LogicalUnitType.TEXT_BLOCK, element_ids=("r1", "p1"),
            source=StructureSource.DERIVED, confidence=0.8,
        )
        with self.assertRaisesRegex(IntegrityConsolidationError, "crosses.*integrity span"):
            IntegrityGroupConsolidator().consolidate(
                elements,
                boundaries(elements, [BoundaryClass.HARD]),
                grouping(elements, units=(crossing,)),
            )

    def test_result_is_deterministic(self):
        elements = (
            element("k1", 0, ElementType.KEY_VALUE),
            element("k2", 1, ElementType.KEY_VALUE),
        )
        consolidator = IntegrityGroupConsolidator()
        first = consolidator.consolidate(
            elements, boundaries(elements), grouping(elements, ungrouped=("k1", "k2"))
        )
        second = consolidator.consolidate(
            elements, boundaries(elements), grouping(elements, ungrouped=("k1", "k2"))
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
