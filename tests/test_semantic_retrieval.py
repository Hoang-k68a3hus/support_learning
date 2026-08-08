from __future__ import annotations

import unittest
from datetime import datetime, timezone

from source_understanding.retrieval_units.semantic import (
    SemanticRetrievalEnrichmentError,
    SemanticRetrievalEnricher,
    SemanticRetrievalPolicy,
)
from source_understanding.schemas.context import ContextNode, StructureSource
from source_understanding.schemas.document import (
    CanonicalDocument,
    ContentRegion,
    DocumentMetadata,
    DocumentStructure,
    ProcessingManifest,
    SemanticAnnotation,
    SemanticAnnotationType,
    SubDocument,
)
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.schemas.retrieval_unit import RetrievalUnit, RetrievalUnitType, SourceAnchor


CONTENT_HASH = "sha256:" + "1" * 64


def token_count(text: str) -> int:
    return len(text.split())


def element(element_id: str, order: int, text: str) -> Element:
    return Element(
        id=element_id,
        type=ElementType.PARAGRAPH,
        order=order,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def annotation(
    annotation_id: str,
    target_id: str,
    annotation_type: SemanticAnnotationType,
    value: str,
    confidence: float = 0.9,
) -> SemanticAnnotation:
    return SemanticAnnotation(
        id=annotation_id,
        target_id=target_id,
        type=annotation_type,
        value=value,
        source=StructureSource.INFERRED,
        confidence=confidence,
        model_version="test-semantic-v1",
    )


def document_with(
    annotations: tuple[SemanticAnnotation, ...],
    *,
    with_context: bool = False,
    with_region: bool = False,
    with_subdocument: bool = False,
) -> CanonicalDocument:
    elements = (
        element("e1", 0, "Alpha source text."),
        element("e2", 1, "Beta source text."),
    )
    context_nodes = ()
    context_ids = ()
    if with_context:
        context_nodes = (
            ContextNode(
                id="ctx1",
                type="SECTION",
                label="Context heading",
                level=1,
                source=StructureSource.INFERRED,
                confidence=0.95,
            ),
        )
        context_ids = ("ctx1",)
    logical_units = (
        LogicalUnit(
            id="lu1",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=("e1", "e2"),
            region_id="r1" if with_region else None,
            context_node_ids=context_ids,
            source=StructureSource.DERIVED,
            confidence=0.9,
        ),
    )
    regions = ()
    structure = DocumentStructure()
    if with_region:
        regions = (
            ContentRegion(
                id="r1",
                element_ids=("e1", "e2"),
                source=StructureSource.INFERRED,
                confidence=0.9,
            ),
        )
    subdocuments = ()
    if with_subdocument:
        subdocuments = (
            SubDocument(
                id="sub1",
                element_ids=("e1", "e2"),
                source=StructureSource.INFERRED,
                confidence=0.9,
            ),
        )
    return CanonicalDocument(
        document_id="doc1",
        content_hash=CONTENT_HASH,
        source_revision="rev1",
        processing=ProcessingManifest(
            adapter_name="test",
            processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            semantic_version="test-semantic-v1",
        ),
        metadata=DocumentMetadata(title="Test document"),
        structure=structure,
        elements=elements,
        regions=regions,
        logical_units=logical_units,
        context_nodes=context_nodes,
        semantic_annotations=annotations,
        subdocuments=subdocuments,
    )


def base_unit(
    document: CanonicalDocument,
    *,
    element_ids: tuple[str, ...] = ("e1", "e2"),
    logical_unit_ids: tuple[str, ...] = ("lu1",),
    context: bool = False,
    subdocument_id: str | None = None,
    max_tokens: int | None = None,
) -> RetrievalUnit:
    text = "Test document\nAlpha source text. Beta source text."
    metadata: dict[str, object] = {
        "semantic_enrichment_used": False,
        "policy_version": "2",
    }
    if max_tokens is not None:
        metadata["max_tokens"] = max_tokens
    context_path = ()
    if context:
        node = document.context_nodes[0]
        from source_understanding.schemas.retrieval_unit import ContextNodeRef

        context_path = (
            ContextNodeRef(
                id=node.id,
                type=node.type,
                label=node.label,
                source=node.source,
                confidence=node.confidence,
            ),
        )
    return RetrievalUnit(
        id="ru_base",
        document_id=document.document_id,
        content_hash=document.content_hash,
        source_revision=document.source_revision,
        subdocument_id=subdocument_id,
        logical_unit_ids=logical_unit_ids,
        element_ids=element_ids,
        retrieval_text=text,
        display_text="Alpha source text.\n\nBeta source text.",
        context_path=context_path,
        source_anchors=tuple(
            SourceAnchor(
                source_id=document.document_id,
                content_hash=document.content_hash,
                source_revision=document.source_revision,
                element_id=element_id,
            )
            for element_id in element_ids
        ),
        unit_type=RetrievalUnitType.TEXT,
        token_count=token_count(text),
        version="2",
        metadata=metadata,
    )


class SemanticRetrievalTests(unittest.TestCase):
    def test_direct_annotation_is_attached_and_rendered_without_touching_display_or_anchors(self) -> None:
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.TOPIC, "Machine learning"),)
        )
        unit = base_unit(doc)
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (unit,))
        enriched = result.units[0]

        self.assertEqual(result.enriched_unit_count, 1)
        self.assertIn("Topic: Machine learning", enriched.retrieval_text)
        self.assertEqual(enriched.display_text, unit.display_text)
        self.assertEqual(enriched.source_anchors, unit.source_anchors)
        self.assertEqual(enriched.semantic_annotations[0].id, "a1")
        self.assertNotEqual(enriched.id, unit.id)
        self.assertEqual(enriched.metadata["base_retrieval_unit_id"], unit.id)
        self.assertFalse(enriched.metadata["semantic_context_is_source_fact"])
        enriched.validate_against_document(doc)

    def test_low_confidence_annotation_is_skipped(self) -> None:
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.TOPIC, "Weak topic", 0.4),)
        )
        unit = base_unit(doc)
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (unit,))
        self.assertEqual(result.units[0], unit)
        self.assertEqual(result.skipped_low_confidence_annotation_ids, ("a1",))

    def test_custom_annotation_is_disallowed_by_default(self) -> None:
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.CUSTOM, "opaque"),)
        )
        unit = base_unit(doc)
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (unit,))
        self.assertEqual(result.units[0], unit)
        self.assertEqual(result.skipped_disallowed_type_annotation_ids, ("a1",))

    def test_logical_unit_annotation_applies_to_partition_projection(self) -> None:
        doc = document_with(
            (annotation("a1", "lu1", SemanticAnnotationType.KEY_POINT, "Shared key point"),)
        )
        first = base_unit(doc, element_ids=("e1",))
        second = base_unit(doc, element_ids=("e2",))
        second = RetrievalUnit(**{**second.model_dump(mode="python"), "id": "ru_base_2"})
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (first, second))
        self.assertEqual(result.enriched_unit_count, 2)
        self.assertTrue(all("Shared key point" in unit.retrieval_text for unit in result.units))
        self.assertEqual(result.referenced_annotation_ids, ("a1",))

    def test_unrelated_annotation_does_not_leak_between_chunks(self) -> None:
        doc = document_with(
            (annotation("a1", "e2", SemanticAnnotationType.TOPIC, "Only beta"),)
        )
        first = base_unit(doc, element_ids=("e1",))
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (first,))
        self.assertEqual(result.units[0], first)

    def test_context_annotation_is_inherited_but_region_and_subdocument_are_opt_in(self) -> None:
        doc = document_with(
            (
                annotation("ctx_ann", "ctx1", SemanticAnnotationType.TOPIC, "Context topic"),
                annotation("region_ann", "r1", SemanticAnnotationType.TOPIC, "Region topic"),
                annotation("sub_ann", "sub1", SemanticAnnotationType.TOPIC, "Subdoc topic"),
            ),
            with_context=True,
            with_region=True,
            with_subdocument=True,
        )
        unit = base_unit(doc, context=True, subdocument_id="sub1")
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (unit,))
        enriched = result.units[0]
        self.assertIn("Context topic", enriched.retrieval_text)
        self.assertNotIn("Region topic", enriched.retrieval_text)
        self.assertNotIn("Subdoc topic", enriched.retrieval_text)

    def test_budget_can_attach_annotation_without_rendering_it(self) -> None:
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.TOPIC, "Machine learning"),)
        )
        unit = base_unit(doc)
        unit = RetrievalUnit(
            **{
                **unit.model_dump(mode="python"),
                "metadata": {**dict(unit.metadata), "max_tokens": unit.token_count},
            }
        )
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (unit,))
        enriched = result.units[0]
        self.assertEqual(enriched.retrieval_text, unit.retrieval_text)
        self.assertEqual(enriched.token_count, unit.token_count)
        self.assertEqual(enriched.semantic_annotations[0].id, "a1")
        self.assertEqual(result.rendered_annotation_ids, ())
        self.assertEqual(result.skipped_budget_annotation_ids, ("a1",))
        self.assertFalse(enriched.metadata["semantic_enrichment_used"])

    def test_long_annotation_value_does_not_violate_annotation_ref_schema(self) -> None:
        long_value = "x" * 3000
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.SUMMARY, long_value),)
        )
        unit = base_unit(doc)
        result = SemanticRetrievalEnricher(token_count).enrich(doc, (unit,))
        enriched = result.units[0]
        self.assertIsNone(enriched.semantic_annotations[0].value)
        self.assertIn("…", enriched.retrieval_text)
        enriched.validate_against_document(doc)

    def test_duplicate_semantic_values_are_deduplicated_deterministically(self) -> None:
        doc = document_with(
            (
                annotation("logical", "lu1", SemanticAnnotationType.TOPIC, "Same topic", 0.99),
                annotation("direct", "e1", SemanticAnnotationType.TOPIC, "Same   topic", 0.8),
            )
        )
        unit = base_unit(doc)
        enricher = SemanticRetrievalEnricher(token_count)
        first = enricher.enrich(doc, (unit,)).units[0]
        second = enricher.enrich(doc, (unit,)).units[0]
        self.assertEqual(first, second)
        self.assertEqual(tuple(ref.id for ref in first.semantic_annotations), ("direct",))

    def test_disabled_policy_returns_base_units_unchanged(self) -> None:
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.TOPIC, "Machine learning"),)
        )
        unit = base_unit(doc)
        policy = SemanticRetrievalPolicy(enabled=False)
        result = SemanticRetrievalEnricher(token_count, policy).enrich(doc, (unit,))
        self.assertEqual(result.units, (unit,))
        self.assertEqual(result.enriched_unit_count, 0)

    def test_reenrichment_is_rejected_to_prevent_semantic_prefix_duplication(self) -> None:
        doc = document_with(
            (annotation("a1", "e1", SemanticAnnotationType.TOPIC, "Machine learning"),)
        )
        unit = base_unit(doc)
        enricher = SemanticRetrievalEnricher(token_count)
        enriched = enricher.enrich(doc, (unit,)).units[0]
        with self.assertRaisesRegex(SemanticRetrievalEnrichmentError, "already semantic-enriched"):
            enricher.enrich(doc, (enriched,))

    def test_scope_priority_prefers_direct_target_when_annotation_limit_is_one(self) -> None:
        doc = document_with(
            (
                annotation("logical", "lu1", SemanticAnnotationType.TOPIC, "Logical topic", 0.99),
                annotation("direct", "e1", SemanticAnnotationType.TOPIC, "Direct topic", 0.8),
            )
        )
        unit = base_unit(doc)
        policy = SemanticRetrievalPolicy(max_annotations_per_unit=1)
        result = SemanticRetrievalEnricher(token_count, policy).enrich(doc, (unit,))
        enriched = result.units[0]
        self.assertIn("Direct topic", enriched.retrieval_text)
        self.assertNotIn("Logical topic", enriched.retrieval_text)


if __name__ == "__main__":
    unittest.main()
