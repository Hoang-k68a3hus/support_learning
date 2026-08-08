from __future__ import annotations

import unittest
from datetime import UTC, datetime

from source_understanding.retrieval_units.builder import (
    RetrievalUnitBuildError,
    RetrievalUnitBuildPolicy,
    RetrievalUnitBuilder,
)
from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.document import (
    CanonicalDocument,
    ContentRegion,
    DocumentMetadata,
    DocumentStructure,
    ProcessingManifest,
    SubDocument,
)
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType

HASH = "sha256:" + "a" * 64


def provenance() -> Provenance:
    return Provenance(source=StructureSource.EXPLICIT, extractor="test")


def element(
    eid: str,
    order: int,
    text: str,
    *,
    etype: ElementType = ElementType.PARAGRAPH,
) -> Element:
    return Element(
        id=eid,
        order=order,
        type=etype,
        raw_text=text,
        provenance=provenance(),
    )


def logical(
    uid: str,
    ids: tuple[str, ...],
    *,
    utype: LogicalUnitType = LogicalUnitType.TEXT_BLOCK,
) -> LogicalUnit:
    return LogicalUnit(
        id=uid,
        type=utype,
        element_ids=ids,
        source=StructureSource.DERIVED,
        confidence=0.9,
    )


def document(
    elements: tuple[Element, ...],
    *,
    units: tuple[LogicalUnit, ...],
    title: str | None = None,
    subdocs: tuple[SubDocument, ...] = (),
    regions: tuple[ContentRegion, ...] = (),
    mode: StructureMode = StructureMode.UNKNOWN,
) -> CanonicalDocument:
    structure = (
        DocumentStructure()
        if mode == StructureMode.UNKNOWN
        else DocumentStructure(
            mode=mode,
            source=StructureSource.DERIVED,
            confidence=0.8,
        )
    )
    return CanonicalDocument(
        document_id="doc",
        content_hash=HASH,
        source_revision="rev1",
        processing=ProcessingManifest(
            adapter_name="test",
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        ),
        metadata=DocumentMetadata(title=title),
        structure=structure,
        elements=elements,
        logical_units=units,
        subdocuments=subdocs,
        regions=regions,
    )


def tokens(text: str) -> int:
    return len(text.split())


class RetrievalUnitBuilderV2Tests(unittest.TestCase):
    def test_text_block_partitions_greedily_at_element_boundaries(self) -> None:
        elements = (
            element("e0", 0, "one two"),
            element("e1", 1, "three four"),
            element("e2", 2, "five six"),
            element("e3", 3, "seven eight"),
        )
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(max_tokens=5),
        ).build(
            document(
                elements,
                units=(logical("u", ("e0", "e1", "e2", "e3")),),
            )
        )

        self.assertEqual(
            [unit.element_ids for unit in result.units],
            [("e0", "e1"), ("e2", "e3")],
        )
        self.assertEqual(result.partitioned_logical_unit_ids, ("u",))
        self.assertTrue(all(unit.token_count <= 5 for unit in result.units))
        self.assertEqual(
            [unit.metadata["partition_index"] for unit in result.units],
            [0, 1],
        )
        self.assertTrue(all(unit.metadata["partition_count"] == 2 for unit in result.units))
        self.assertTrue(all(unit.logical_unit_ids == ("u",) for unit in result.units))

    def test_retrieval_prefix_overhead_counts_toward_budget(self) -> None:
        elements = (
            element("e0", 0, "one two"),
            element("e1", 1, "three four"),
        )
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(max_tokens=5),
        ).build(
            document(
                elements,
                units=(logical("u", ("e0", "e1")),),
                title="Database Systems",
            )
        )

        self.assertEqual([unit.element_ids for unit in result.units], [("e0",), ("e1",)])
        self.assertEqual([unit.token_count for unit in result.units], [4, 4])

    def test_single_oversized_element_is_not_split_inside_source_element(self) -> None:
        elements = (element("e", 0, "one two three four five"),)
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(max_tokens=3),
        ).build(document(elements, units=(logical("u", ("e",)),)))

        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.units[0].element_ids, ("e",))
        self.assertEqual(result.partitioned_logical_unit_ids, ())
        self.assertEqual(result.oversized_unit_ids, (result.units[0].id,))

    def test_atomic_qa_pair_is_not_partitioned(self) -> None:
        elements = (
            element("q", 0, "one two three", etype=ElementType.QUESTION),
            element("a", 1, "four five six", etype=ElementType.ANSWER),
        )
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(max_tokens=3),
        ).build(
            document(
                elements,
                units=(logical("qa", ("q", "a"), utype=LogicalUnitType.QA_PAIR),),
            )
        )

        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.units[0].element_ids, ("q", "a"))
        self.assertEqual(result.partitioned_logical_unit_ids, ())
        self.assertEqual(result.oversized_unit_ids, (result.units[0].id,))

    def test_partitioning_can_be_disabled(self) -> None:
        elements = (
            element("e0", 0, "one two three"),
            element("e1", 1, "four five six"),
        )
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(
                max_tokens=3,
                adaptive_text_partitioning=False,
            ),
        ).build(document(elements, units=(logical("u", ("e0", "e1")),)))

        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.units[0].element_ids, ("e0", "e1"))
        self.assertEqual(result.partitioned_logical_unit_ids, ())
        self.assertEqual(result.oversized_unit_ids, (result.units[0].id,))

    def test_partitioning_cannot_hide_cross_subdocument_unit(self) -> None:
        elements = (
            element("e0", 0, "one two"),
            element("e1", 1, "three four"),
        )
        subdocs = (
            SubDocument(
                id="s0",
                element_ids=("e0",),
                confidence=0.9,
                source=StructureSource.INFERRED,
            ),
            SubDocument(
                id="s1",
                element_ids=("e1",),
                confidence=0.9,
                source=StructureSource.INFERRED,
            ),
        )
        doc = document(
            elements,
            units=(logical("u", ("e0", "e1")),),
            subdocs=subdocs,
        )

        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(
                tokens,
                RetrievalUnitBuildPolicy(max_tokens=2),
            ).build(doc)

    def test_partitioning_cannot_hide_cross_region_unit(self) -> None:
        e0 = element("e0", 0, "one two")
        e1 = element("e1", 1, "three four")
        r0 = ContentRegion(
            id="r0",
            element_ids=("e0",),
            structure=DocumentStructure(
                mode=StructureMode.LOCAL,
                source=StructureSource.DERIVED,
                confidence=0.8,
            ),
            source=StructureSource.DERIVED,
            confidence=0.8,
        )
        r1 = ContentRegion(
            id="r1",
            element_ids=("e1",),
            structure=DocumentStructure(
                mode=StructureMode.GROUPED,
                source=StructureSource.DERIVED,
                confidence=0.8,
            ),
            source=StructureSource.DERIVED,
            confidence=0.8,
        )
        doc = document(
            (e0, e1),
            units=(logical("u", ("e0", "e1")),),
            regions=(r0, r1),
            mode=StructureMode.MIXED,
        )

        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(
                tokens,
                RetrievalUnitBuildPolicy(max_tokens=2),
            ).build(doc)

    def test_blank_element_never_becomes_empty_partition(self) -> None:
        elements = (
            element("blank", 0, "   "),
            element("e0", 1, "one two three four"),
            element("e1", 2, "five six"),
        )
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(max_tokens=4),
        ).build(
            document(
                elements,
                units=(logical("u", ("blank", "e0", "e1")),),
            )
        )

        self.assertEqual(
            [unit.element_ids for unit in result.units],
            [("blank", "e0"), ("e1",)],
        )
        self.assertEqual(result.partitioned_logical_unit_ids, ("u",))


if __name__ == "__main__":
    unittest.main()
