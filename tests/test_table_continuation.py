from __future__ import annotations

import unittest

from source_understanding.relations import (
    TABLE_CONTINUATION_EVIDENCE_ATTRIBUTE,
    RelationBuildPolicy,
    RelationDiagnosticOutcome,
    StructuralRelationBuilder,
)
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import (
    BoundingBox,
    Element,
    ElementType,
    Provenance,
    SourceLocation,
)
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.schemas.relation import RelationType
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
)


def table_fragment(
    element_id: str,
    order: int,
    page: int,
    *,
    bottom: float = 0.96,
    top: float = 0.04,
    column_boundaries: list[float] | None = None,
    column_count: int = 2,
    topology: str = "rectangular",
    table_index: int = 0,
    orientation: str | None = None,
    leading_row_fingerprint: str | None = None,
) -> Element:
    boundaries = column_boundaries or [0.1, 0.5, 0.9]
    bbox = [0.1, top, 0.9, bottom]
    return Element(
        id=element_id,
        type=ElementType.TABLE,
        order=order,
        location=SourceLocation(
            source=StructureSource.DERIVED,
            page=page,
            bbox=BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
        ),
        attributes={
            INTEGRITY_GROUP_ID_ATTRIBUTE: f"pdf-table:p{page}:t{table_index}",
            SOURCE_ANCHOR_ATTRIBUTE: {
                "kind": "pdf_table",
                "id": f"page:{page}:table:{table_index}",
            },
            TABLE_CONTINUATION_EVIDENCE_ATTRIBUTE: {
                "version": "adjacent-page-table-continuation-v1",
                "page": page,
                "bbox": bbox,
                "column_boundaries": boundaries,
                "row_count": 4,
                "column_count": column_count,
                "topology": topology,
                "orientation": orientation,
                "leading_row_fingerprint": leading_row_fingerprint,
            },
        },
        provenance=Provenance(source=StructureSource.DERIVED, extractor="test"),
    )


def table_unit(unit_id: str, element_id: str) -> LogicalUnit:
    return LogicalUnit(
        id=unit_id,
        type=LogicalUnitType.TABLE_BLOCK,
        element_ids=(element_id,),
        source=StructureSource.DERIVED,
        confidence=0.9,
    )


class TableContinuationRelationTests(unittest.TestCase):
    def build(self, elements: tuple[Element, ...], units: tuple[LogicalUnit, ...], **kwargs):
        return StructuralRelationBuilder(RelationBuildPolicy(**kwargs)).build(elements, units)

    def test_adjacent_fragments_link_without_mutating_elements(self) -> None:
        elements = (
            table_fragment("a", 0, 1, leading_row_fingerprint="header"),
            table_fragment("b", 1, 2, leading_row_fingerprint="header"),
        )
        units = (table_unit("ua", "a"), table_unit("ub", "b"))
        result = self.build(elements, units)

        continuation = next(
            relation for relation in result.relations if relation.type == RelationType.CONTINUES
        )
        self.assertEqual((continuation.source_id, continuation.target_id), ("ua", "ub"))
        self.assertEqual(continuation.source, StructureSource.INFERRED)
        self.assertEqual(continuation.metadata["page_pair"], [1, 2])
        self.assertEqual(
            elements[0],
            table_fragment("a", 0, 1, leading_row_fingerprint="header"),
        )
        self.assertIn("leading_row_match", continuation.metadata["evidence_signals"])
        self.assertEqual(
            next(item for item in result.diagnostics if item.code == "TABLE_CONTINUATION_ACCEPTED").outcome,
            RelationDiagnosticOutcome.ACCEPTED,
        )

    def test_three_page_chain_is_adjacent_and_directional(self) -> None:
        elements = tuple(table_fragment(name, index, index + 1) for index, name in enumerate(("a", "b", "c")))
        units = tuple(table_unit(f"u{name}", name) for name in ("a", "b", "c"))
        result = self.build(elements, units)
        continuations = [item for item in result.relations if item.type == RelationType.CONTINUES]
        self.assertEqual(
            [(item.source_id, item.target_id) for item in continuations],
            [("ua", "ub"), ("ub", "uc")],
        )
        self.assertEqual(len({item.id for item in continuations}), 2)

    def test_same_column_count_with_incompatible_geometry_fails_closed(self) -> None:
        elements = (
            table_fragment("a", 0, 1),
            table_fragment("b", 1, 2, column_boundaries=[0.2, 0.6, 0.85]),
        )
        result = self.build(elements, (table_unit("ua", "a"), table_unit("ub", "b")))
        self.assertFalse(any(item.type == RelationType.CONTINUES for item in result.relations))
        self.assertTrue(
            any(
                item.reason == "column_geometry_mismatch"
                and item.outcome == RelationDiagnosticOutcome.REJECTED
                for item in result.diagnostics
            )
        )

    def test_edge_proximity_is_required(self) -> None:
        elements = (
            table_fragment("a", 0, 1, bottom=0.7),
            table_fragment("b", 1, 2),
        )
        result = self.build(elements, (table_unit("ua", "a"), table_unit("ub", "b")))
        self.assertFalse(any(item.type == RelationType.CONTINUES for item in result.relations))
        self.assertIn("page_edge_evidence_insufficient", {item.reason for item in result.diagnostics})

    def test_page_jump_is_never_linked(self) -> None:
        elements = (
            table_fragment("a", 0, 1),
            table_fragment("c", 1, 3),
        )
        result = self.build(elements, (table_unit("ua", "a"), table_unit("uc", "c")))
        self.assertFalse(any(item.type == RelationType.CONTINUES for item in result.relations))
        self.assertEqual(result.diagnostics, ())

    def test_multiple_compatible_pairs_are_ambiguous(self) -> None:
        elements = (
            table_fragment("a1", 0, 1, table_index=0),
            table_fragment("a2", 1, 1, table_index=1),
            table_fragment("b1", 2, 2, table_index=0),
            table_fragment("b2", 3, 2, table_index=1),
        )
        units = tuple(table_unit(f"u{name}", name) for name in ("a1", "a2", "b1", "b2"))
        result = self.build(elements, units)
        self.assertFalse(any(item.type == RelationType.CONTINUES for item in result.relations))
        ambiguous = next(item for item in result.diagnostics if item.code == "TABLE_CONTINUATION_AMBIGUOUS")
        self.assertEqual(ambiguous.reason, "multiple_candidate_pairs")

    def test_orientation_mismatch_is_hard_negative(self) -> None:
        elements = (
            table_fragment("a", 0, 1, orientation="PORTRAIT"),
            table_fragment("b", 1, 2, orientation="LANDSCAPE"),
        )
        result = self.build(elements, (table_unit("ua", "a"), table_unit("ub", "b")))
        self.assertFalse(any(item.type == RelationType.CONTINUES for item in result.relations))
        self.assertIn("page_orientation_mismatch", {item.reason for item in result.diagnostics})

    def test_policy_can_disable_continuation_without_changing_fragments(self) -> None:
        elements = (table_fragment("a", 0, 1), table_fragment("b", 1, 2))
        units = (table_unit("ua", "a"), table_unit("ub", "b"))
        result = self.build(elements, units, enable_table_continuation=False)
        self.assertFalse(any(item.type == RelationType.CONTINUES for item in result.relations))
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.relations, StructuralRelationBuilder(
            RelationBuildPolicy(enable_table_continuation=False)
        ).build(elements, units).relations)


if __name__ == "__main__":
    unittest.main()
