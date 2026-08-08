from __future__ import annotations
import unittest
from datetime import datetime, timezone
from source_understanding.semantics import HeuristicSemanticProvider, SemanticAnnotationError, SemanticAnnotationPolicy, SemanticAnnotator, SemanticCandidate, SemanticCapability, SemanticOntologyLabel, SemanticProviderCapabilities, SemanticTargetKind
from source_understanding.schemas.context import ContextNode, StructureSource
from source_understanding.schemas.document import CanonicalDocument, DocumentMetadata, ProcessingManifest, SemanticAnnotation, SemanticAnnotationType
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
CONTENT_HASH = 'sha256:' + '4' * 64

def element(element_id: str, order: int, text: str, *, element_type: ElementType=ElementType.PARAGRAPH, excluded: bool=False) -> Element:
    return Element(id=element_id, type=element_type, order=order, raw_text=text, normalized_text=text, provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test'), exclude_from_retrieval=excluded)

def make_document(*, elements: tuple[Element, ...] | None=None, logical_units: tuple[LogicalUnit, ...] | None=None, annotations: tuple[SemanticAnnotation, ...]=()) -> CanonicalDocument:
    if elements is None:
        elements = (element('e1', 0, 'Definition: A queue follows FIFO.'), element('e2', 1, 'Ordinary explanation.'), element('e3', 2, 'Ví dụ: enqueue A rồi B.'))
    context_nodes = (ContextNode(id='ctx1', type='SECTION', label='Data Structures', level=1, source=StructureSource.EXPLICIT, confidence=1.0),)
    if logical_units is None:
        logical_units = (LogicalUnit(id='lu1', type=LogicalUnitType.TEXT_BLOCK, element_ids=('e1', 'e2'), context_node_ids=('ctx1',), source=StructureSource.DERIVED, confidence=0.95),)
    return CanonicalDocument(document_id='doc-sem', content_hash=CONTENT_HASH, source_revision='rev1', processing=ProcessingManifest(adapter_name='test', processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)), metadata=DocumentMetadata(title='Structures', language='vi'), elements=elements, logical_units=logical_units, context_nodes=context_nodes, semantic_annotations=annotations)

class RecordingProvider:
    name = 'recording'
    version = '1'
    capabilities = SemanticProviderCapabilities(capabilities=(SemanticCapability(name='test-all', target_kinds=(SemanticTargetKind.LOGICAL_UNIT, SemanticTargetKind.ELEMENT), annotation_types=tuple(SemanticAnnotationType), ontology_namespaces=('test', 'ner', 'temporal')),), deterministic=True)

    def __init__(self, candidates: tuple[SemanticCandidate, ...]=()) -> None:
        self.candidates = candidates
        self.requests = None

    def annotate(self, requests):
        self.requests = requests
        return self.candidates

class SemanticAnnotationTests(unittest.TestCase):

    def test_heuristic_provider_generates_definition_and_orphan_example(self) -> None:
        doc = make_document()
        result = SemanticAnnotator(HeuristicSemanticProvider()).annotate(doc)
        by_target = {(a.target_id, a.type): a for a in result.document.semantic_annotations}
        self.assertIn(('e1', SemanticAnnotationType.DEFINITION), by_target)
        self.assertIn(('e3', SemanticAnnotationType.EXAMPLE), by_target)
        self.assertEqual(by_target['e1', SemanticAnnotationType.DEFINITION].source, StructureSource.INFERRED)
        self.assertEqual(result.request_count, 4)
        self.assertEqual(result.coverage.coverage, 0.5)

    def test_topic_group_label_becomes_derived_topic_not_source_heading(self) -> None:
        elements = (element('e1', 0, 'Paragraph about queues.'),)
        units = (LogicalUnit(id='lu_topic', type=LogicalUnitType.TOPIC_GROUP, element_ids=('e1',), label='Queues', source=StructureSource.INFERRED, confidence=0.8),)
        result = SemanticAnnotator(HeuristicSemanticProvider()).annotate(make_document(elements=elements, logical_units=units))
        annotation = result.document.semantic_annotations[0]
        self.assertEqual(annotation.type, SemanticAnnotationType.TOPIC)
        self.assertEqual(annotation.value, 'Queues')
        self.assertEqual(annotation.source, StructureSource.DERIVED)
        self.assertEqual(result.document.elements, elements)

    def test_requests_are_source_grounded_and_context_aware(self) -> None:
        provider = RecordingProvider()
        doc = make_document()
        SemanticAnnotator(provider).annotate(doc)
        self.assertIsNotNone(provider.requests)
        logical_request = provider.requests[0]
        element_requests = {request.target_id: request for request in provider.requests[1:]}
        self.assertEqual(logical_request.target_id, 'lu1')
        self.assertEqual(logical_request.element_ids, ('e1', 'e2'))
        self.assertEqual(logical_request.context_labels, ('Data Structures',))
        self.assertIn('Definition: A queue follows FIFO.', logical_request.text)
        self.assertEqual(element_requests['e1'].context_labels, ('Data Structures',))
        self.assertEqual(element_requests['e3'].target_id, 'e3')

    def test_provider_capabilities_filter_unsupported_target_kinds(self) -> None:
        class ElementOnlyProvider(RecordingProvider):
            capabilities = SemanticProviderCapabilities(capabilities=(SemanticCapability(name='element-only', target_kinds=(SemanticTargetKind.ELEMENT,), annotation_types=(SemanticAnnotationType.ENTITY,), ontology_namespaces=('ner',)),))
        provider = ElementOnlyProvider()
        result = SemanticAnnotator(provider).annotate(make_document())
        self.assertEqual(result.request_count, 3)
        self.assertTrue(all((request.target_kind == SemanticTargetKind.ELEMENT for request in provider.requests)))

    def test_provider_cannot_emit_undeclared_annotation_type(self) -> None:
        class EntityOnlyProvider(RecordingProvider):
            capabilities = SemanticProviderCapabilities(capabilities=(SemanticCapability(name='entity-only', target_kinds=(SemanticTargetKind.ELEMENT,), annotation_types=(SemanticAnnotationType.ENTITY,), ontology_namespaces=('ner',)),))
        provider = EntityOnlyProvider((SemanticCandidate(target_id='e1', type=SemanticAnnotationType.DEFINITION, value='Queue', confidence=0.9),))
        with self.assertRaisesRegex(SemanticAnnotationError, 'undeclared capability'):
            SemanticAnnotator(provider).annotate(make_document())

    def test_namespaced_specialized_label_is_preserved_in_metadata(self) -> None:
        class NerProvider(RecordingProvider):
            capabilities = SemanticProviderCapabilities(capabilities=(SemanticCapability(name='named-entities', target_kinds=(SemanticTargetKind.ELEMENT,), annotation_types=(SemanticAnnotationType.ENTITY,), ontology_namespaces=('ner',)),))
        provider = NerProvider((SemanticCandidate(target_id='e1', type=SemanticAnnotationType.ENTITY, value='queue', confidence=0.9, ontology=SemanticOntologyLabel(namespace='ner', label='DATA_STRUCTURE', version='1')),))
        result = SemanticAnnotator(provider).annotate(make_document())
        annotation = result.document.semantic_annotations[0]
        self.assertEqual(annotation.type, SemanticAnnotationType.ENTITY)
        self.assertEqual(annotation.metadata['semantic_ontology_namespace'], 'ner')
        self.assertEqual(annotation.metadata['semantic_ontology_label'], 'DATA_STRUCTURE')
        self.assertEqual(annotation.metadata['semantic_ontology_version'], '1')
        manifest = result.document.processing.configuration['semantic_understanding']
        self.assertEqual(manifest['provider_capabilities']['recording']['protocol_version'], '2')

    def test_provider_cannot_emit_undeclared_ontology_namespace(self) -> None:
        class NerProvider(RecordingProvider):
            capabilities = SemanticProviderCapabilities(capabilities=(SemanticCapability(name='named-entities', target_kinds=(SemanticTargetKind.ELEMENT,), annotation_types=(SemanticAnnotationType.ENTITY,), ontology_namespaces=('ner',)),))
        provider = NerProvider((SemanticCandidate(target_id='e1', type=SemanticAnnotationType.ENTITY, value='2026', confidence=0.9, ontology=SemanticOntologyLabel(namespace='temporal', label='TIMEX')),))
        with self.assertRaisesRegex(SemanticAnnotationError, 'undeclared capability'):
            SemanticAnnotator(provider).annotate(make_document())

    def test_provider_cannot_write_to_unrequested_target(self) -> None:
        provider = RecordingProvider((SemanticCandidate(target_id='ctx1', type=SemanticAnnotationType.TOPIC, value='Illegal target', confidence=0.9),))
        with self.assertRaisesRegex(SemanticAnnotationError, 'was not requested'):
            SemanticAnnotator(provider).annotate(make_document())

    def test_provider_candidate_cannot_claim_explicit_source(self) -> None:
        with self.assertRaisesRegex(ValueError, 'cannot promote.*EXPLICIT'):
            SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='Queue', confidence=0.9, source=StructureSource.EXPLICIT)

    def test_low_confidence_and_disallowed_types_are_filtered(self) -> None:
        provider = RecordingProvider((SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='weak', confidence=0.2), SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.CUSTOM, value='custom', confidence=0.99, ontology=SemanticOntologyLabel(namespace='test', label='CUSTOM'))))
        result = SemanticAnnotator(provider).annotate(make_document())
        self.assertEqual(result.accepted_annotation_count, 0)
        self.assertEqual(result.skipped_low_confidence_count, 1)
        self.assertEqual(result.skipped_disallowed_type_count, 1)

    def test_duplicates_keep_highest_confidence(self) -> None:
        provider = RecordingProvider((SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='Queue', confidence=0.7), SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='queue', confidence=0.95)))
        result = SemanticAnnotator(provider).annotate(make_document())
        self.assertEqual(result.accepted_annotation_count, 1)
        self.assertEqual(result.skipped_duplicate_count, 1)
        self.assertEqual(result.document.semantic_annotations[0].confidence, 0.95)

    def test_per_target_limit_is_policy_not_silent_overflow(self) -> None:
        provider = RecordingProvider(tuple((SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.KEYWORD, value=f'k{index}', confidence=0.99 - index * 0.01) for index in range(4))))
        policy = SemanticAnnotationPolicy(max_annotations_per_target=2)
        result = SemanticAnnotator(provider, policy).annotate(make_document())
        self.assertEqual(result.accepted_annotation_count, 2)
        self.assertEqual(result.skipped_target_limit_count, 2)

    def test_rerun_replaces_same_provider_but_preserves_other_annotations(self) -> None:
        old_same = SemanticAnnotation(id='old_same', target_id='lu1', type=SemanticAnnotationType.TOPIC, value='old', source=StructureSource.INFERRED, confidence=0.8, model_version='recording:0', metadata={'semantic_provider': 'recording'})
        other = SemanticAnnotation(id='other', target_id='lu1', type=SemanticAnnotationType.NOTE, value='manual enrichment', source=StructureSource.INFERRED, confidence=0.9, model_version='other:1', metadata={'semantic_provider': 'other'})
        provider = RecordingProvider((SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='new', confidence=0.9),))
        result = SemanticAnnotator(provider).annotate(make_document(annotations=(old_same, other)))
        ids = {annotation.id for annotation in result.document.semantic_annotations}
        self.assertIn('other', ids)
        self.assertNotIn('old_same', ids)
        self.assertEqual(result.replaced_annotation_ids, ('old_same',))
        self.assertEqual(result.retained_annotation_count, 1)

    def test_semantic_processing_manifest_is_reproducible_and_source_is_unchanged(self) -> None:
        provider = RecordingProvider((SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='Queue', confidence=0.9),))
        doc = make_document()
        result = SemanticAnnotator(provider).annotate(doc)
        enriched = result.document
        self.assertEqual(enriched.elements, doc.elements)
        self.assertEqual(enriched.logical_units, doc.logical_units)
        self.assertEqual(enriched.context_nodes, doc.context_nodes)
        self.assertEqual(enriched.processing.semantic_version, 'semantic-annotations:1')
        config = enriched.processing.configuration['semantic_understanding']
        self.assertEqual(config['providers']['recording'], '1')

    def test_output_is_deterministic_for_same_document_provider_and_policy(self) -> None:
        candidates = (SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='Queue', confidence=0.9),)
        first = SemanticAnnotator(RecordingProvider(candidates)).annotate(make_document())
        second = SemanticAnnotator(RecordingProvider(candidates)).annotate(make_document())
        self.assertEqual(first.document, second.document)
        self.assertEqual(first.document.semantic_annotations[0].id, second.document.semantic_annotations[0].id)

    def test_disabled_policy_does_not_call_provider_or_mutate_document(self) -> None:
        class ExplodingProvider:
            name = 'explode'
            version = '1'
            capabilities = RecordingProvider.capabilities
            def annotate(self, requests):
                raise AssertionError('provider should not be called')
        doc = make_document()
        policy = SemanticAnnotationPolicy(enabled=False)
        result = SemanticAnnotator(ExplodingProvider(), policy).annotate(doc)
        self.assertIs(result.document, doc)
        self.assertEqual(result.provider_candidate_count, 0)

    def test_reserved_metadata_collision_is_rejected(self) -> None:
        provider = RecordingProvider((SemanticCandidate(target_id='lu1', type=SemanticAnnotationType.TOPIC, value='Queue', confidence=0.9, metadata={'semantic_provider': 'spoofed'}),))
        with self.assertRaisesRegex(SemanticAnnotationError, 'reserved semantic keys'):
            SemanticAnnotator(provider).annotate(make_document())
if __name__ == '__main__':
    unittest.main()
