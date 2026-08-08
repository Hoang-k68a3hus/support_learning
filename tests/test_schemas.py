from __future__ import annotations

import json
import math
import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from source_understanding.schemas import (
    AnnotationRef,
    BoundingBox,
    CanonicalDocument,
    ContentRegion,
    ContextNode,
    ContextNodeRef,
    DocumentMetadata,
    DocumentStructure,
    Element,
    ElementType,
    LogicalUnit,
    LogicalUnitType,
    ProcessingManifest,
    Provenance,
    Relation,
    RelationLayer,
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

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def processing() -> ProcessingManifest:
    return ProcessingManifest(
        adapter_name="unit-test",
        adapter_version="1",
        processed_at=datetime(2026, 8, 8, tzinfo=UTC),
    )


def provenance() -> Provenance:
    return Provenance(
        source=StructureSource.EXPLICIT,
        extractor="unit-test",
        confidence=1.0,
    )


def element(
    element_id: str,
    order: int,
    text: str = "text",
    location: SourceLocation | None = None,
) -> Element:
    return Element(
        id=element_id,
        type=ElementType.PARAGRAPH,
        order=order,
        raw_text=text,
        location=location,
        provenance=provenance(),
    )


def canonical(**kwargs: object) -> CanonicalDocument:
    data: dict[str, object] = {
        "document_id": "doc",
        "content_hash": HASH_A,
        "source_revision": "rev1",
        "processing": processing(),
    }
    data.update(kwargs)
    return CanonicalDocument(**data)


def anchor(
    element_id: str,
    *,
    source_id: str = "doc",
    content_hash: str = HASH_A,
    source_revision: str | None = "rev1",
    **kwargs: object,
) -> SourceAnchor:
    return SourceAnchor(
        source_id=source_id,
        content_hash=content_hash,
        source_revision=source_revision,
        element_id=element_id,
        **kwargs,
    )


class SourceUnderstandingSchemaTests(unittest.TestCase):
    def test_default_structure_is_unknown_without_fake_confidence(self) -> None:
        structure = DocumentStructure()
        self.assertEqual(structure.mode, StructureMode.UNKNOWN)
        self.assertIsNone(structure.source)
        self.assertIsNone(structure.confidence)

    def test_known_structure_requires_source_and_confidence(self) -> None:
        with self.assertRaises(ValidationError):
            DocumentStructure(mode=StructureMode.FLAT)
        with self.assertRaises(ValidationError):
            DocumentStructure(
                mode=StructureMode.HIERARCHICAL,
                source=StructureSource.EXPLICIT,
            )
        with self.assertRaises(ValidationError):
            DocumentStructure(
                mode=StructureMode.UNKNOWN,
                source=StructureSource.INFERRED,
                confidence=0.2,
            )

    def test_structure_objects_require_source_and_confidence(self) -> None:
        constructors = (
            lambda: ContextNode(id="c1", type="TOPIC", label="A"),
            lambda: LogicalUnit(
                id="lu1",
                type=LogicalUnitType.TEXT_BLOCK,
                element_ids=("e1",),
            ),
            lambda: ContentRegion(id="rg1", element_ids=("e1",)),
            lambda: Relation(
                id="r1",
                layer=RelationLayer.STRUCTURAL,
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

    def test_content_hash_is_explicit_sha256(self) -> None:
        with self.assertRaises(ValidationError):
            canonical(content_hash="abc")
        with self.assertRaises(ValidationError):
            canonical(content_hash="sha256:" + "A" * 64)

    def test_canonical_document_accepts_valid_faq_graph(self) -> None:
        q = element("e1", 0, "Q: Reset password?")
        a = element("e2", 1, "A: Open Settings.")
        region = ContentRegion(
            id="rg1",
            element_ids=("e1", "e2"),
            dominant_type="QA",
            structure=DocumentStructure(
                mode=StructureMode.LOCAL,
                source=StructureSource.EXPLICIT,
                confidence=1.0,
            ),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        unit = LogicalUnit(
            id="lu1",
            type=LogicalUnitType.QA_PAIR,
            element_ids=("e1", "e2"),
            region_id="rg1",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        relation = Relation(
            id="r1",
            layer=RelationLayer.STRUCTURAL,
            type=RelationType.QUESTION_ANSWER,
            source_id="e1",
            target_id="e2",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        document = canonical(
            structure=DocumentStructure(
                mode=StructureMode.LOCAL,
                source=StructureSource.DERIVED,
                confidence=0.95,
            ),
            elements=(q, a),
            regions=(region,),
            logical_units=(unit,),
            relations=(relation,),
        )
        self.assertEqual(document.source_id, "doc")
        self.assertEqual(document.schema_version, "1.1")
        json.loads(document.model_dump_json())

    def test_mixed_structure_requires_regions(self) -> None:
        with self.assertRaises(ValidationError):
            canonical(
                structure=DocumentStructure(
                    mode=StructureMode.MIXED,
                    source=StructureSource.INFERRED,
                    confidence=0.7,
                )
            )

    def test_regions_must_reference_ordered_non_overlapping_elements(self) -> None:
        e1, e2, e3 = element("e1", 0), element("e2", 1), element("e3", 2)
        rg1 = ContentRegion(
            id="rg1",
            element_ids=("e1", "e2"),
            source=StructureSource.INFERRED,
            confidence=0.7,
        )
        rg_overlap = ContentRegion(
            id="rg2",
            element_ids=("e2", "e3"),
            source=StructureSource.INFERRED,
            confidence=0.7,
        )
        with self.assertRaises(ValidationError):
            canonical(elements=(e1, e2, e3), regions=(rg1, rg_overlap))

        rg_reversed = ContentRegion(
            id="rg3",
            element_ids=("e3", "e1"),
            source=StructureSource.INFERRED,
            confidence=0.7,
        )
        with self.assertRaises(ValidationError):
            canonical(elements=(e1, e2, e3), regions=(rg_reversed,))

    def test_logical_unit_region_must_exist_and_contain_elements(self) -> None:
        e1, e2 = element("e1", 0), element("e2", 1)
        region = ContentRegion(
            id="rg1",
            element_ids=("e1",),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        missing = LogicalUnit(
            id="lu1",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e1",),
            region_id="missing",
            source=StructureSource.INFERRED,
            confidence=0.6,
        )
        with self.assertRaises(ValidationError):
            canonical(elements=(e1, e2), regions=(region,), logical_units=(missing,))

        outside = LogicalUnit(
            id="lu2",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e1", "e2"),
            region_id="rg1",
            source=StructureSource.INFERRED,
            confidence=0.6,
        )
        with self.assertRaises(ValidationError):
            canonical(elements=(e1, e2), regions=(region,), logical_units=(outside,))

    def test_duplicate_ids_and_cross_namespace_collisions_rejected(self) -> None:
        e1 = element("same", 0)
        with self.assertRaises(ValidationError):
            canonical(elements=(e1, element("same", 1)))

        region = ContentRegion(
            id="same",
            element_ids=("e1",),
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        with self.assertRaises(ValidationError):
            canonical(elements=(element("e1", 0), element("same", 1)), regions=(region,))

    def test_dangling_references_rejected(self) -> None:
        unit = LogicalUnit(
            id="lu1",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("missing",),
            source=StructureSource.INFERRED,
            confidence=0.6,
        )
        with self.assertRaises(ValidationError):
            canonical(elements=(element("e1", 0),), logical_units=(unit,))

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
            canonical(context_nodes=(c1, c2))

    def test_context_hierarchy_rejects_redundant_parent_relation(self) -> None:
        parent = ContextNode(
            id="c1",
            type="SECTION",
            label="A",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        child = ContextNode(
            id="c2",
            type="SECTION",
            label="B",
            parent_id="c1",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        relation = Relation(
            id="r1",
            layer=RelationLayer.STRUCTURAL,
            type=RelationType.PARENT_OF,
            source_id="c1",
            target_id="c2",
            source=StructureSource.DERIVED,
            confidence=1.0,
        )
        with self.assertRaises(ValidationError):
            canonical(context_nodes=(parent, child), relations=(relation,))

    def test_element_order_must_be_unique_and_ascending(self) -> None:
        with self.assertRaises(ValidationError):
            canonical(elements=(element("e1", 0), element("e2", 0)))
        with self.assertRaises(ValidationError):
            canonical(elements=(element("e1", 2), element("e2", 1)))

    def test_subdocuments_cannot_overlap_or_reverse_order(self) -> None:
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
            canonical(
                elements=(element("e1", 0), element("e2", 1)),
                subdocuments=(sub1, sub2),
            )

        reversed_subdoc = SubDocument(
            id="s3",
            element_ids=("e2", "e1"),
            source=StructureSource.INFERRED,
            confidence=0.7,
        )
        with self.assertRaises(ValidationError):
            canonical(
                elements=(element("e1", 0), element("e2", 1)),
                subdocuments=(reversed_subdoc,),
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

    def test_bbox_uses_normalized_page_coordinates(self) -> None:
        with self.assertRaises(ValidationError):
            BoundingBox(x0=0, y0=0, x1=math.inf, y1=1)
        with self.assertRaises(ValidationError):
            BoundingBox(x0=0, y0=0, x1=2, y1=1)
        with self.assertRaises(ValidationError):
            BoundingBox(x0=0.8, y0=0, x1=0.2, y1=1)
        box = BoundingBox(x0=0.1, y0=0.2, x1=0.8, y1=0.9)
        self.assertEqual(box.x0, 0.1)

    def test_source_location_requires_complete_ranges(self) -> None:
        with self.assertRaises(ValidationError):
            SourceLocation(start_char=1)
        with self.assertRaises(ValidationError):
            SourceLocation(page=1, line_start=3, line_end=2)
        with self.assertRaises(ValidationError):
            SourceLocation(bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1))

    def test_unknown_quality_does_not_default_to_perfect(self) -> None:
        e = element("e1", 0)
        self.assertIsNone(e.confidence.overall)
        self.assertEqual(e.provenance.confidence, 1.0)

        ru = RetrievalUnit(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            source_anchors=(anchor("e1"),),
            token_count=1,
            version="ru_v1",
        )
        self.assertIsNone(ru.quality)

    def test_relation_layer_is_explicit_and_inverse_types_are_not_canonical(self) -> None:
        Relation(
            id="r1",
            layer=RelationLayer.SEMANTIC,
            type=RelationType.SAME_TOPIC,
            source_id="e1",
            target_id="e2",
            source=StructureSource.INFERRED,
            confidence=0.5,
        )
        with self.assertRaises(ValidationError):
            Relation(
                id="r2",
                layer=RelationLayer.SEMANTIC,
                type=RelationType.NEXT,
                source_id="e1",
                target_id="e2",
                source=StructureSource.DERIVED,
                confidence=1.0,
            )
        with self.assertRaises(ValueError):
            RelationType("PREVIOUS")
        with self.assertRaises(ValueError):
            RelationType("CHILD_OF")

    def test_retrieval_unit_requires_complete_anchor_coverage(self) -> None:
        base = dict(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1", "e2"),
            retrieval_text="retrieval",
            display_text="display",
            token_count=2,
            version="ru_v1",
        )
        with self.assertRaises(ValidationError):
            RetrievalUnit(**base, source_anchors=())
        with self.assertRaises(ValidationError):
            RetrievalUnit(**base, source_anchors=(anchor("e1"),))

        unit = RetrievalUnit(
            **base,
            source_anchors=(anchor("e1"), anchor("e2")),
        )
        self.assertEqual(unit.source_id, "doc")

    def test_retrieval_anchor_must_match_source_revision_and_hash(self) -> None:
        base = dict(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            token_count=1,
            version="ru_v1",
        )
        for bad_anchor in (
            anchor("e1", source_id="other"),
            anchor("e1", content_hash=HASH_B),
            anchor("e1", source_revision="rev2"),
            anchor("outside"),
        ):
            with self.subTest(anchor=bad_anchor):
                with self.assertRaises(ValidationError):
                    RetrievalUnit(**base, source_anchors=(bad_anchor,))

    def test_source_anchor_location_requires_provenance(self) -> None:
        with self.assertRaises(ValidationError):
            anchor("e1", page=1)
        with self.assertRaises(ValidationError):
            anchor("e1", location_source=StructureSource.EXPLICIT)

    def test_retrieval_validate_against_document_catches_stale_or_dangling_refs(self) -> None:
        e = element("e1", 0)
        document = canonical(elements=(e,))
        valid = RetrievalUnit(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            source_anchors=(anchor("e1"),),
            token_count=1,
            version="ru_v1",
        )
        self.assertIs(valid.validate_against_document(document), valid)

        stale = RetrievalUnit(
            id="ru2",
            document_id="doc",
            content_hash=HASH_B,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            source_anchors=(anchor("e1", content_hash=HASH_B),),
            token_count=1,
            version="ru_v1",
        )
        with self.assertRaises(ValueError):
            stale.validate_against_document(document)

    def test_non_derived_anchor_must_agree_with_canonical_location(self) -> None:
        location = SourceLocation(page=1, start_char=10, end_char=20)
        e = element("e1", 0, location=location)
        document = canonical(elements=(e,))
        bad_anchor = anchor(
            "e1",
            location_source=StructureSource.EXPLICIT,
            page=2,
        )
        unit = RetrievalUnit(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            source_anchors=(bad_anchor,),
            token_count=1,
            version="ru_v1",
        )
        with self.assertRaises(ValueError):
            unit.validate_against_document(document)

        derived_anchor = anchor(
            "e1",
            location_source=StructureSource.DERIVED,
            page=2,
            bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1),
        )
        derived_unit = unit.model_copy(update={"source_anchors": (derived_anchor,)})
        self.assertIs(derived_unit.validate_against_document(document), derived_unit)

    def test_context_path_must_follow_canonical_parent_chain(self) -> None:
        root = ContextNode(
            id="c1",
            type="SECTION",
            label="Root",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        child = ContextNode(
            id="c2",
            type="SECTION",
            label="Child",
            parent_id="c1",
            source=StructureSource.EXPLICIT,
            confidence=1.0,
        )
        document = canonical(elements=(element("e1", 0),), context_nodes=(root, child))
        unit = RetrievalUnit(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            context_path=(ContextNodeRef(id="c2"),),
            source_anchors=(anchor("e1"),),
            token_count=1,
            version="ru_v1",
        )
        with self.assertRaises(ValueError):
            unit.validate_against_document(document)

    def test_annotation_refs_are_checked_against_canonical_annotation(self) -> None:
        e = element("e1", 0)
        annotation = SemanticAnnotation(
            id="a1",
            target_id="e1",
            type=SemanticAnnotationType.TOPIC,
            value="SQL",
            source=StructureSource.INFERRED,
            confidence=0.8,
        )
        document = canonical(elements=(e,), semantic_annotations=(annotation,))
        unit = RetrievalUnit(
            id="ru1",
            document_id="doc",
            content_hash=HASH_A,
            source_revision="rev1",
            element_ids=("e1",),
            retrieval_text="retrieval",
            display_text="display",
            semantic_annotations=(AnnotationRef(id="a1", value="NoSQL"),),
            source_anchors=(anchor("e1"),),
            token_count=1,
            version="ru_v1",
        )
        with self.assertRaises(ValueError):
            unit.validate_against_document(document)

    def test_retrieval_text_and_version_cannot_be_blank(self) -> None:
        for field in ("retrieval_text", "display_text", "version"):
            kwargs = dict(
                id="ru1",
                document_id="doc",
                content_hash=HASH_A,
                source_revision="rev1",
                element_ids=("e1",),
                retrieval_text="retrieval",
                display_text="display",
                source_anchors=(anchor("e1"),),
                token_count=1,
                version="ru_v1",
            )
            kwargs[field] = "   "
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    RetrievalUnit(**kwargs)

    def test_all_exported_models_generate_json_schema(self) -> None:
        model_types = (
            ProcessingManifest,
            DocumentStructure,
            ContentRegion,
            CanonicalDocument,
            SourceLocation,
            BoundingBox,
            Relation,
            RetrievalUnit,
            SourceAnchor,
        )
        for model_type in model_types:
            with self.subTest(model=model_type.__name__):
                self.assertIsInstance(model_type.model_json_schema(), dict)


if __name__ == "__main__":
    unittest.main()
