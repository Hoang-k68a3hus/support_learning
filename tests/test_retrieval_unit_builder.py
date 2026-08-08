from __future__ import annotations

import unittest
from datetime import UTC, datetime

from source_understanding.retrieval_units.builder import (
    RetrievalStrategy,
    RetrievalUnitBuildError,
    RetrievalUnitBuildPolicy,
    RetrievalUnitBuilder,
)
from source_understanding.schemas.context import ContextNode, StructureMode, StructureSource
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
from source_understanding.schemas.retrieval_unit import RetrievalUnitType

HASH = "sha256:" + "a" * 64


def provenance() -> Provenance:
    return Provenance(source=StructureSource.EXPLICIT, extractor="test")


def element(
    eid: str,
    order: int,
    text: str | None,
    *,
    etype: ElementType = ElementType.PARAGRAPH,
    normalized: str | None = None,
    excluded: bool = False,
) -> Element:
    return Element(
        id=eid,
        order=order,
        type=etype,
        raw_text=text,
        normalized_text=normalized,
        provenance=provenance(),
        exclude_from_retrieval=excluded,
    )


def logical(
    uid: str,
    ids: tuple[str, ...],
    *,
    utype: LogicalUnitType = LogicalUnitType.TEXT_BLOCK,
    context: tuple[str, ...] = (),
) -> LogicalUnit:
    return LogicalUnit(
        id=uid,
        type=utype,
        element_ids=ids,
        context_node_ids=context,
        source=StructureSource.DERIVED,
        confidence=0.9,
    )


def document(
    elements: tuple[Element, ...],
    *,
    units: tuple[LogicalUnit, ...] = (),
    nodes: tuple[ContextNode, ...] = (),
    subdocs: tuple[SubDocument, ...] = (),
    regions: tuple[ContentRegion, ...] = (),
    mode: StructureMode = StructureMode.UNKNOWN,
    title: str | None = "Database Systems",
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
            processed_at=datetime(2026, 8, 8, tzinfo=UTC),
        ),
        metadata=DocumentMetadata(title=title),
        structure=structure,
        elements=elements,
        logical_units=units,
        context_nodes=nodes,
        subdocuments=subdocs,
        regions=regions,
    )


def tokens(text: str) -> int:
    return len(text.split())


class RetrievalUnitBuilderTests(unittest.TestCase):
    def test_qa_pair_is_one_atomic_retrieval_unit(self) -> None:
        elements = (
            element("q", 0, "Q: What is SQL?", etype=ElementType.QUESTION),
            element("a", 1, "A: A query language.", etype=ElementType.ANSWER),
        )
        doc = document(
            elements,
            units=(logical("qa", ("q", "a"), utype=LogicalUnitType.QA_PAIR),),
            mode=StructureMode.LOCAL,
        )
        result = RetrievalUnitBuilder(tokens).build(doc)
        self.assertEqual(result.strategy, RetrievalStrategy.LOCAL)
        self.assertEqual(len(result.units), 1)
        unit = result.units[0]
        self.assertEqual(unit.unit_type, RetrievalUnitType.QA_PAIR)
        self.assertEqual(unit.element_ids, ("q", "a"))
        self.assertEqual(unit.logical_unit_ids, ("qa",))
        self.assertEqual(len(unit.source_anchors), 2)

    def test_display_preserves_raw_while_retrieval_prefers_normalized(self) -> None:
        elements = (
            element(
                "e",
                0,
                "  Raw   source  ",
                normalized="Raw source",
            ),
        )
        doc = document(elements, units=(logical("u", ("e",)),))
        unit = RetrievalUnitBuilder(tokens).build(doc).units[0]
        self.assertEqual(unit.display_text, "  Raw   source  ")
        self.assertTrue(unit.retrieval_text.endswith("Raw source"))
        self.assertNotEqual(unit.display_text, unit.retrieval_text)

    def test_code_view_preserves_source_indentation(self) -> None:
        code = "    if ready:\n        run()\n"
        elements = (element("code", 0, code, etype=ElementType.CODE),)
        doc = document(
            elements,
            units=(logical("u", ("code",), utype=LogicalUnitType.CODE_BLOCK),),
            title=None,
        )
        unit = RetrievalUnitBuilder(tokens).build(doc).units[0]
        self.assertEqual(unit.display_text, code)
        self.assertEqual(unit.retrieval_text, code)
        self.assertEqual(unit.unit_type, RetrievalUnitType.CODE)

    def test_document_title_and_explicit_context_are_retrieval_only(self) -> None:
        root = ContextNode(
            id="c0",
            type="TITLE",
            label="SQL",
            level=0,
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        child = ContextNode(
            id="c1",
            type="HEADING",
            label="JOIN",
            level=1,
            parent_id="c0",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        elements = (element("e", 0, "Returns matching rows."),)
        doc = document(
            elements,
            units=(logical("u", ("e",), context=("c0", "c1")),),
            nodes=(root, child),
            mode=StructureMode.HIERARCHICAL,
        )
        unit = RetrievalUnitBuilder(tokens).build(doc).units[0]
        self.assertEqual(unit.display_text, "Returns matching rows.")
        self.assertIn("Database Systems", unit.retrieval_text)
        self.assertIn("SQL > JOIN", unit.retrieval_text)
        self.assertEqual([ref.id for ref in unit.context_path], ["c0", "c1"])
        self.assertEqual(unit.metadata["strategy"], "HIERARCHICAL")

    def test_heading_left_out_of_grouping_gets_safe_fallback_unit(self) -> None:
        heading = element("h", 0, "JOIN", etype=ElementType.HEADING)
        paragraph = element("p", 1, "Join content")
        node = ContextNode(
            id="ctx",
            type="HEADING",
            label="JOIN",
            level=1,
            source=StructureSource.EXPLICIT,
            confidence=1.0,
            attributes={"anchor_element_id": "h"},
        )
        doc = document(
            (heading, paragraph),
            units=(logical("u", ("p",), context=("ctx",)),),
            nodes=(node,),
            mode=StructureMode.LOCAL,
        )
        result = RetrievalUnitBuilder(tokens).build(doc)
        self.assertEqual([unit.element_ids for unit in result.units], [("h",), ("p",)])
        self.assertEqual(result.units[0].unit_type, RetrievalUnitType.SECTION)
        self.assertEqual(result.units[0].context_path, ())

    def test_unresolved_table_subelements_are_not_silently_singleton_chunked(self) -> None:
        elements = (
            element("r", 0, "row", etype=ElementType.TABLE_ROW),
            element("c", 1, "cell", etype=ElementType.TABLE_CELL),
        )
        result = RetrievalUnitBuilder(tokens).build(document(elements, title=None))
        self.assertEqual(result.units, ())
        self.assertEqual(result.unresolved_integrity_element_ids, ("r", "c"))

    def test_logical_unit_cannot_mix_excluded_and_retrievable_elements(self) -> None:
        elements = (
            element("e0", 0, "keep"),
            element("e1", 1, "drop", excluded=True),
        )
        doc = document(elements, units=(logical("u", ("e0", "e1")),))
        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(tokens).build(doc)

    def test_fully_excluded_unit_is_skipped_without_breaking_integrity(self) -> None:
        elements = (
            element("e0", 0, "header", excluded=True, etype=ElementType.HEADER),
            element("e1", 1, "header2", excluded=True, etype=ElementType.HEADER),
        )
        doc = document(elements, units=(logical("u", ("e0", "e1")),), title=None)
        result = RetrievalUnitBuilder(tokens).build(doc)
        self.assertEqual(result.units, ())
        self.assertEqual(result.skipped_excluded_element_ids, ("e0", "e1"))

    def test_cross_subdocument_logical_unit_is_rejected(self) -> None:
        elements = (element("e0", 0, "A"), element("e1", 1, "B"))
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
        doc = document(elements, units=(logical("u", ("e0", "e1")),), subdocs=subdocs)
        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(tokens).build(doc)

    def test_subdocument_membership_is_preserved(self) -> None:
        elements = (element("e0", 0, "A"), element("e1", 1, "B"))
        subdoc = SubDocument(
            id="s",
            element_ids=("e0", "e1"),
            confidence=0.9,
            source=StructureSource.INFERRED,
        )
        doc = document(elements, units=(logical("u", ("e0", "e1")),), subdocs=(subdoc,))
        unit = RetrievalUnitBuilder(tokens).build(doc).units[0]
        self.assertEqual(unit.subdocument_id, "s")

    def test_token_budget_does_not_split_atomic_unit(self) -> None:
        elements = (
            element("q", 0, "one two three", etype=ElementType.QUESTION),
            element("a", 1, "four five six", etype=ElementType.ANSWER),
        )
        doc = document(
            elements,
            units=(logical("qa", ("q", "a"), utype=LogicalUnitType.QA_PAIR),),
            title=None,
        )
        result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(max_tokens=3),
        ).build(doc)
        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.units[0].element_ids, ("q", "a"))
        self.assertEqual(result.oversized_unit_ids, (result.units[0].id,))
        self.assertTrue(result.units[0].metadata["token_budget_exceeded"])

    def test_anchor_uses_exact_source_identity_without_inventing_location_provenance(self) -> None:
        elements = (element("e", 0, "text"),)
        doc = document(elements, units=(logical("u", ("e",)),), title=None)
        anchor = RetrievalUnitBuilder(tokens).build(doc).units[0].source_anchors[0]
        self.assertEqual(anchor.source_id, "doc")
        self.assertEqual(anchor.content_hash, HASH)
        self.assertEqual(anchor.source_revision, "rev1")
        self.assertEqual(anchor.element_id, "e")
        self.assertIsNone(anchor.location_source)
        self.assertIsNone(anchor.page)

    def test_unknown_structure_falls_back_to_flat(self) -> None:
        doc = document((element("e", 0, "text"),), units=(logical("u", ("e",)),))
        result = RetrievalUnitBuilder(tokens).build(doc)
        self.assertEqual(result.strategy, RetrievalStrategy.FLAT)
        self.assertEqual(result.units[0].metadata["strategy"], "FLAT")

    def test_invalid_token_counter_is_rejected(self) -> None:
        doc = document((element("e", 0, "text"),), units=(logical("u", ("e",)),))
        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(lambda _: 0).build(doc)
        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(lambda _: 1.5).build(doc)  # type: ignore[arg-type]

    def test_overlapping_logical_units_are_rejected_in_v1(self) -> None:
        elements = (element("e", 0, "text"),)
        doc = document(
            elements,
            units=(logical("u0", ("e",)), logical("u1", ("e",))),
        )
        with self.assertRaises(RetrievalUnitBuildError):
            RetrievalUnitBuilder(tokens).build(doc)

    def test_fallback_unit_uses_document_strategy(self) -> None:
        heading = element("h", 0, "Heading", etype=ElementType.HEADING)
        doc = document((heading,), mode=StructureMode.HIERARCHICAL)
        unit = RetrievalUnitBuilder(tokens).build(doc).units[0]
        self.assertEqual(unit.metadata["strategy"], "HIERARCHICAL")

    def test_policy_change_changes_unit_identity_and_is_recorded(self) -> None:
        doc = document((element("e", 0, "text"),), units=(logical("u", ("e",)),))
        default_result = RetrievalUnitBuilder(tokens).build(doc)
        no_title_result = RetrievalUnitBuilder(
            tokens,
            RetrievalUnitBuildPolicy(include_document_title=False, version="1-no-title"),
        ).build(doc)
        self.assertNotEqual(default_result.units[0].id, no_title_result.units[0].id)
        self.assertEqual(no_title_result.policy.version, "1-no-title")
        self.assertEqual(no_title_result.units[0].metadata["policy_version"], "1-no-title")

    def test_mixed_document_routes_unit_by_region_structure(self) -> None:
        e0 = element("e0", 0, "A")
        e1 = element("e1", 1, "B")
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
            units=(
                LogicalUnit(
                    id="u0",
                    type=LogicalUnitType.TEXT_BLOCK,
                    element_ids=("e0",),
                    region_id="r0",
                    source=StructureSource.DERIVED,
                    confidence=0.9,
                ),
                LogicalUnit(
                    id="u1",
                    type=LogicalUnitType.TEXT_BLOCK,
                    element_ids=("e1",),
                    region_id="r1",
                    source=StructureSource.DERIVED,
                    confidence=0.9,
                ),
            ),
            regions=(r0, r1),
            mode=StructureMode.MIXED,
        )
        result = RetrievalUnitBuilder(tokens).build(doc)
        self.assertEqual(result.strategy, RetrievalStrategy.MIXED)
        self.assertEqual([u.metadata["strategy"] for u in result.units], ["LOCAL", "GROUPED"])

    def test_mixed_document_rejects_cross_region_projection(self) -> None:
        e0 = element("e0", 0, "A")
        e1 = element("e1", 1, "B")
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
                mode=StructureMode.LOCAL,
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
            RetrievalUnitBuilder(tokens).build(doc)

    def test_same_input_is_deterministic(self) -> None:
        elements = (element("e0", 0, "A"), element("e1", 1, "B"))
        doc = document(elements, units=(logical("u", ("e0", "e1")),))
        builder = RetrievalUnitBuilder(tokens)
        self.assertEqual(builder.build(doc), builder.build(doc))


if __name__ == "__main__":
    unittest.main()
