from __future__ import annotations

import unittest
from types import SimpleNamespace

from source_understanding.relations.builder import StructuralRelationBuilder
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnitType
from source_understanding.schemas.relation import RelationType
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE,
)
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.integrity import IntegrityConsolidationError, IntegrityGroupConsolidator


def element(element_id: str, order: int, group: str, parent: str | None = None) -> Element:
    attrs = {INTEGRITY_GROUP_ID_ATTRIBUTE: group}
    if parent is not None:
        attrs[INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE] = parent
    return Element(
        id=element_id,
        type=ElementType.TABLE_ROW,
        order=order,
        raw_text=element_id,
        normalized_text=element_id,
        attributes=attrs,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="native"),
    )


def boundaries(elements):
    return SimpleNamespace(
        element_count=len(elements),
        boundaries=tuple(
            SimpleNamespace(
                id=f"b{i}",
                left_element_id=elements[i].id,
                right_element_id=elements[i + 1].id,
                classification=SimpleNamespace(value="NONE"),
                reasons=(),
            )
            for i in range(len(elements) - 1)
        ),
    )


def grouping(elements):
    return GroupingResult(
        element_count=len(elements),
        signal_version="2",
        boundary_version="2",
        policy=GroupingPolicy(),
        logical_units=(),
        ungrouped_element_ids=tuple(item.id for item in elements),
    )


class NativeIntegrityContractTests(unittest.TestCase):
    def test_nested_native_groups_build_distinct_units_and_parent_relation(self):
        elements = (
            element("outer1", 0, "outer"),
            element("inner", 1, "inner", "outer"),
            element("outer2", 2, "outer"),
        )
        consolidated, report = IntegrityGroupConsolidator().consolidate(
            elements, boundaries(elements), grouping(elements)
        )
        self.assertEqual(report.native_group_count, 2)
        self.assertEqual(report.nested_native_group_count, 1)
        units = {unit.metadata[INTEGRITY_GROUP_ID_ATTRIBUTE]: unit for unit in consolidated.logical_units}
        self.assertEqual(units["outer"].element_ids, ("outer1", "outer2"))
        self.assertEqual(units["inner"].element_ids, ("inner",))
        self.assertEqual(units["outer"].type, LogicalUnitType.TABLE_BLOCK)

        relations = StructuralRelationBuilder().build(elements, consolidated.logical_units).relations
        nesting = [
            relation for relation in relations
            if relation.type == RelationType.PART_OF
            and relation.source_id == units["inner"].id
            and relation.target_id == units["outer"].id
        ]
        self.assertEqual(len(nesting), 1)

    def test_native_parent_cycle_is_rejected(self):
        elements = (
            element("a", 0, "A", "B"),
            element("b", 1, "B", "A"),
        )
        with self.assertRaisesRegex(IntegrityConsolidationError, "cycle"):
            IntegrityGroupConsolidator().consolidate(
                elements, boundaries(elements), grouping(elements)
            )

    def test_native_group_cannot_jump_over_unrelated_content(self):
        unrelated = Element(
            id="p",
            type=ElementType.PARAGRAPH,
            order=1,
            raw_text="outside",
            normalized_text="outside",
            provenance=Provenance(source=StructureSource.EXPLICIT, extractor="native"),
        )
        elements = (
            element("outer1", 0, "outer"),
            unrelated,
            element("outer2", 2, "outer"),
        )
        with self.assertRaisesRegex(IntegrityConsolidationError, "crosses unrelated"):
            IntegrityGroupConsolidator().consolidate(
                elements, boundaries(elements), grouping(elements)
            )


if __name__ == "__main__":
    unittest.main()
