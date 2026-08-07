from __future__ import annotations

import json
import math
import unittest

from pydantic import ValidationError

from source_understanding.schemas import (
    BoundingBox,
    CanonicalDocument,
    ContextNode,
    DocumentMetadata,
    DocumentStructure,
    Element,
    ElementType,
    LogicalUnit,
    LogicalUnitType,
    Provenance,
    Relation,
    RelationType,
    RetrievalUnit,
    SemanticAnnotation,
    SemanticAnnotationType,
    SourceAnchor,
    SourceLocation,
    StructureMode,
    StructureSource,
    SubDocument,
)


def provenance() -> Provenance:
    return Provenance(
        source=StructureSource.EXPLICIT,
        extractor="unit-test",
        confidence=1.0,
    )


def element(element_id: str, order: int, text: str = "text") -> Element:
    return Element(
        id=element_id,
        type=ElementType.PARAGRAPH,
        order=order,
        raw_text=text,
        provenance=provenance(),
    )


class SourceUnderstandingSchemaTests(unittest.TestCase):
    def test_default_structure_is_unknown_not_flat(self) -> None:
        structure = DocumentStructure()
        self.assertEqual(structure.mode, StructureMode.UNKNOWN)
        self.assertEqual(structure.confidence, 0.0)

    def test_structure_objects_require_source_and_confidence(self) -> None:
        constructors = (
            lambda: ContextNode(id="c1", type="TOPIC", label="A"),
            lambda: LogicalUnit(
                id="lu1",
                type=LogicalUnitType.TEXT_BLOCK,
                element_ids=("e1",),
            ),
            lambda: Relation(
                id="r1",
                type=RelationType.NEXT,
                source_id="e1",
                target_id="e2",
            ),
            lambda: SubDocument(id="s1", element_ids=("e1",)),
            lambda: SemanticAnnotation(
                id="a1",
                target_id="e1",
                type=SemanticAnnotationType.TOPIC,
                value="SQL",
            ),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(ValidationError):
                    constructor()

    def test_canonical_document_accepts_valid_faq_graph(self) -> None:
        q = element("e1", 0, "Q: Reset password?")
        a = element("e2", 1, "A: Open Settings.")
        unit = LogicalUnit(
            id="lu1",
            type=LogicalUnitType.QA_PAIR,
            element_ids=("e1", "e2"),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        relation = Relation(
            id="r1",
            type=RelationType.QUESTION_ANSWER,
            source_id="e1",
            target_id="e2",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        document = CanonicalDocument(
            document_id="doc1",
            structure=DocumentStructure(mode=StructureMode.LOCAL, confidence=0.95),
            elements=(q, a),
            logical_units=(unit,),
            relations=(relation,),
        )
        self.assertEqual(document.source_id, "doc1")
        json.loads(document.model_dump_json())

    def test_duplicate_ids_and_cross_namespace_collisions_rejected(self) -> None:
        e1 = element("same", 0)
        with self.assertRaises(ValidationError):
            CanonicalDocument(document_id="doc", elements=(e1, element("same", 1)))

        unit = LogicalUnit(
            id="same",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e1",),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        with self.assertRaises(ValidationError):
            CanonicalDocument(
                document_id="doc",
                elements=(element("e1", 0), element("same", 1)),
                logical_units=(unit,),
            )

    def test_dangling_references_rejected(self) -> None:
        unit = LogicalUnit(
            id="lu1",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("missing",),
            source=StructureSource.INFERRED,
            confidence=0.6,
        )
        with self.assertRaises(ValidationError):
            CanonicalDocument(
                document_id="doc",
                elements=(element("e1", 0),),
                logical_units=(unit,),
            )

    def test_context_cycle_rejected(self) -> None:
        c1 = ContextNode(
            id="c1",
            type="TOPIC",
            label="A",
            source=StructureSource.INFERRED,
            confidence=0.7,
            parent_id="c2",
        )
        c2 = ContextNode(
            id="c2",
            type="TOPIC",
            label="B",
            source=StructureSource.INFERRED,
            confidence=0.7,
            parent_id="c1",
        )
        with self.assertRaises(ValidationError):
            CanonicalDocument(document_id="doc", context_nodes=(c1, c2))

    def test_element_order_must_be_unique_and_ascending(self) -> None:
        with self.assertRaises(ValidationError):
            CanonicalDocument(
                document_id="doc",
                elements=(element("e1", 0), element("e2", 0)),
            )
        with self.assertRaises(ValidationError):
            CanonicalDocument(
                document_id="doc",
                elements=(element("e1", 2), element("e2", 1)),
            )

    def test_subdocuments_cannot_overlap(self) -> None:
        sub1 = SubDocument(
            id="s1",
            element_ids=("e1",),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        sub2 = SubDocument(
            id="s2",
            element_ids=("e1", "e2"),
            source=StructureSource.INFERRED,
            confidence=0.7,
        )
        with self.assertRaises(ValidationError):
            CanonicalDocument(
                document_id="doc",
                elements=(element("e1", 0), element("e2", 1)),
                subdocuments=(sub1, sub2),
            )

    def test_reference_collections_are_immutable(self) -> None:
        unit = LogicalUnit(
            id="lu1",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e1",),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        self.assertIsInstance(unit.element_ids, tuple)
        with self.assertRaises(AttributeError):
            unit.element_ids.append("e2")  # type: ignore[attr-defined]
        with self.assertRaises(ValidationError):
            unit.element_ids = ("e1", "e2")  # type: ignore[misc]

    def test_metadata_is_json_safe_and_finite(self) -> None:
        metadata = DocumentMetadata(attributes={"nested": [1, "x", True, None]})
        json.loads(metadata.model_dump_json())
        with self.assertRaises(ValidationError):
            DocumentMetadata(attributes={"bad": object()})
        with self.assertRaises(ValidationError):
            DocumentMetadata(attributes={"bad": math.inf})
        with self.assertRaises(ValidationError):
            DocumentMetadata(attributes={"bad": math.nan})
        with self.assertRaises(TypeError):
            metadata.attributes["new"] = 1
        with self.assertRaises(TypeError):
            metadata.attributes["nested"].append("mutation")

        structure = DocumentStructure(signals={"explicit": 0.9})
        with self.assertRaises(TypeError):
            structure.signals["explicit"] = 0.1

    def test_bbox_rejects_non_finite_and_invalid_extents(self) -> None:
        with self.assertRaises(ValidationError):
            BoundingBox(x0=0, y0=0, x1=math.inf, y1=1)
        with self.assertRaises(ValidationError):
            BoundingBox(x0=2, y0=0, x1=1, y1=1)

    def test_source_location_requires_complete_ranges(self) -> None:
        with self.assertRaises(ValidationError):
            SourceLocation(start_char=1)
        with self.assertRaises(ValidationError):
            SourceLocation(page=1, line_start=3, line_end=2)
        with self.assertRaises(ValidationError):
            SourceLocation(bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1))

    def test_retrieval_unit_requires_complete_anchor_coverage(self) -> None:
        base = dict(
            id="ru1",
            document_id="doc",
            element_ids=("e1", "e2"),
            retrieval_text="retrieval",
            display_text="display",
            token_count=2,
            version="ru_v1",
        )
        with self.assertRaises(ValidationError):
            RetrievalUnit(**base, source_anchors=())
        with self.assertRaises(ValidationError):
            RetrievalUnit(
                **base,
                source_anchors=(SourceAnchor(source_id="doc", element_id="e1"),),
            )

        unit = RetrievalUnit(
            **base,
            source_anchors=(
                SourceAnchor(source_id="doc", element_id="e1"),
                SourceAnchor(source_id="doc", element_id="e2"),
            ),
        )
        self.assertEqual(unit.source_id, "doc")

    def test_retrieval_anchor_must_match_source_and_elements(self) -> None:
        base = dict(
            id="ru1",
            document_id="doc",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            token_count=1,
            version="ru_v1",
        )
        with self.assertRaises(ValidationError):
            RetrievalUnit(
                **base,
                source_anchors=(SourceAnchor(source_id="other", element_id="e1"),),
            )
        with self.assertRaises(ValidationError):
            RetrievalUnit(
                **base,
                source_anchors=(SourceAnchor(source_id="doc", element_id="outside"),),
            )

    def test_bbox_is_part_of_anchor_identity(self) -> None:
        a1 = SourceAnchor(
            source_id="doc",
            element_id="e1",
            page=1,
            bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10),
        )
        a2 = SourceAnchor(
            source_id="doc",
            element_id="e1",
            page=1,
            bbox=BoundingBox(x0=20, y0=20, x1=30, y1=30),
        )
        RetrievalUnit(
            id="ru1",
            document_id="doc",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            source_anchors=(a1, a2),
            token_count=1,
            version="ru_v1",
        )
        with self.assertRaises(ValidationError):
            RetrievalUnit(
                id="ru2",
                document_id="doc",
                element_ids=("e1",),
                retrieval_text="retrieval",
                display_text="display",
                source_anchors=(a1, a1),
                token_count=1,
                version="ru_v1",
            )

    def test_retrieval_text_and_version_cannot_be_blank(self) -> None:
        anchor = SourceAnchor(source_id="doc", element_id="e1")
        for field in ("retrieval_text", "display_text", "version"):
            kwargs = dict(
                id="ru1",
                document_id="doc",
                element_ids=("e1",),
                retrieval_text="retrieval",
                display_text="display",
                source_anchors=(anchor,),
                token_count=1,
                version="ru_v1",
            )
            kwargs[field] = "   "
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    RetrievalUnit(**kwargs)


if __name__ == "__main__":
    unittest.main()
