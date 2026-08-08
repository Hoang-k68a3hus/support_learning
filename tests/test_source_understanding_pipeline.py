from __future__ import annotations
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from source_understanding.pipeline import SemanticFailureMode, SemanticStageStatus, SourceUnderstandingPipeline, SourceUnderstandingPipelineError, SourceUnderstandingPipelinePolicy
from source_understanding.semantics import HeuristicSemanticProvider, SemanticAnnotator
from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.document import ContentRegion, ProcessingManifest, SemanticAnnotationType
from source_understanding.schemas.element import Element, ElementType, Provenance, RawElement
HASH = 'sha256:' + 'a' * 64

def make_elements():
    return (Element(id='e1', type=ElementType.PARAGRAPH, order=0, raw_text='Definition: A queue follows FIFO.', normalized_text='Definition: A queue follows FIFO.', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')), Element(id='e2', type=ElementType.PARAGRAPH, order=1, raw_text='Ordinary explanation.', normalized_text='Ordinary explanation.', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')))

def make_raw_elements():
    return (RawElement(text='Definition: A queue follows FIFO.\r\ncontinued', type_hint='paragraph', order=0, provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test-adapter')), RawElement(text='Ordinary explanation.', type_hint='paragraph', order=1, provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test-adapter')))

def processing():
    return ProcessingManifest(adapter_name='test-adapter', adapter_version='1', processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), configuration={'adapter': {'preserve_raw': True}})

class SourceUnderstandingPipelineTests(unittest.TestCase):

    def test_understand_raw_normalizes_before_structural_understanding(self):
        result = SourceUnderstandingPipeline().understand_raw(document_id='doc1', content_hash=HASH, processing=processing(), raw_elements=make_raw_elements())
        self.assertIsNotNone(result.normalization_result)
        self.assertEqual(result.document.elements[0].raw_text, make_raw_elements()[0].text)
        self.assertIn('\ncontinued', result.document.elements[0].normalized_text)
        self.assertNotIn('\r', result.document.elements[0].normalized_text)
        self.assertEqual(result.document.processing.normalizer_version, '1')
        config = result.document.processing.configuration['element_normalization']
        self.assertEqual(config['normalizer_version'], '1')
        self.assertIn('policy', config)

    def test_direct_element_pipeline_has_no_normalization_result(self):
        result = SourceUnderstandingPipeline().understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertIsNone(result.normalization_result)

    def test_understand_raw_rejects_conflicting_normalizer_version(self):
        stale = processing().model_copy(update={'normalizer_version': 'old'})
        with self.assertRaisesRegex(SourceUnderstandingPipelineError, 'normalizer_version conflicts'):
            SourceUnderstandingPipeline().understand_raw(document_id='doc1', content_hash=HASH, processing=stale, raw_elements=make_raw_elements())

    def test_raw_normalization_errors_are_localized(self):
        with self.assertRaisesRegex(SourceUnderstandingPipelineError, 'element normalization failed') as ctx:
            SourceUnderstandingPipeline().understand_raw(document_id='doc1', content_hash=HASH, processing=processing(), raw_elements=())
        self.assertIsNotNone(ctx.exception.__cause__)

    def test_structural_pipeline_is_terminal_without_semantics(self):
        result = SourceUnderstandingPipeline().understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements(), source_revision='rev1')
        self.assertEqual(result.semantic_status, SemanticStageStatus.NOT_CONFIGURED)
        self.assertEqual(result.document, result.structural_document)
        self.assertEqual(result.document.elements, make_elements())
        self.assertEqual(result.content_profile.element_count, 2)

    def test_semantics_enrich_final_document_without_mutating_structural_snapshot(self):
        pipeline = SourceUnderstandingPipeline(semantic_annotator=SemanticAnnotator(HeuristicSemanticProvider()))
        result = pipeline.understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertEqual(result.semantic_status, SemanticStageStatus.COMPLETED)
        self.assertEqual(result.structural_document.semantic_annotations, ())
        self.assertEqual(len(result.document.semantic_annotations), 1)
        annotation = result.document.semantic_annotations[0]
        self.assertEqual(annotation.target_id, 'e1')
        self.assertEqual(annotation.type, SemanticAnnotationType.DEFINITION)
        self.assertEqual(result.document.elements, result.structural_document.elements)

    def test_optional_semantic_failure_keeps_structural_document(self):
        class BrokenSemantic:
            def annotate(self, document):
                raise RuntimeError('provider offline')
        result = SourceUnderstandingPipeline(semantic_annotator=BrokenSemantic()).understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertEqual(result.semantic_status, SemanticStageStatus.FAILED_OPTIONAL)
        self.assertEqual(result.document, result.structural_document)
        self.assertIn('provider offline', result.semantic_error)

    def test_strict_semantic_failure_raises_with_cause(self):
        class BrokenSemantic:
            def annotate(self, document):
                raise RuntimeError('provider offline')
        pipeline = SourceUnderstandingPipeline(semantic_annotator=BrokenSemantic(), policy=SourceUnderstandingPipelinePolicy(semantic_failure_mode=SemanticFailureMode.RAISE))
        with self.assertRaisesRegex(SourceUnderstandingPipelineError, 'semantic enrichment failed') as ctx:
            pipeline.understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_semantic_stage_cannot_mutate_source_or_structure(self):
        class MutatingSemantic:
            def annotate(self, document):
                changed = document.model_copy(update={'elements': tuple(reversed(document.elements))})
                return SimpleNamespace(document=changed)
        result = SourceUnderstandingPipeline(semantic_annotator=MutatingSemantic()).understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertEqual(result.semantic_status, SemanticStageStatus.FAILED_OPTIONAL)
        self.assertIn('mutated canonical source/structure', result.semantic_error)
        self.assertEqual(result.document.elements, make_elements())

    def test_auto_content_regions_are_generated_and_recorded(self):
        elements = (Element(id='e1', type=ElementType.PARAGRAPH, order=0, raw_text='Intro', normalized_text='Intro', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')), Element(id='e2', type=ElementType.CODE, order=1, raw_text='x = 1', normalized_text='x = 1', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')))
        result = SourceUnderstandingPipeline().understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=elements)
        self.assertIsNotNone(result.region_result)
        self.assertEqual(len(result.document.regions), 2)
        manifest = result.document.processing.configuration['source_understanding_pipeline']
        self.assertEqual(manifest['content_regions']['source'], 'AUTO')
        self.assertEqual(manifest['content_regions']['count'], 2)
        self.assertIn('segmenter_policy', manifest['content_regions'])

    def test_auto_content_regions_can_be_disabled(self):
        result = SourceUnderstandingPipeline(policy=SourceUnderstandingPipelinePolicy(auto_segment_regions=False)).understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertIsNone(result.region_result)
        self.assertEqual(result.document.regions, ())
        manifest = result.document.processing.configuration['source_understanding_pipeline']
        self.assertEqual(manifest['content_regions']['source'], 'DISABLED')

    def test_interaction_region_can_promote_document_to_mixed(self):
        elements = (Element(id='e1', type=ElementType.PARAGRAPH, order=0, raw_text='Intro', normalized_text='Intro', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')), Element(id='e2', type=ElementType.QUESTION, order=1, raw_text='Why?', normalized_text='Why?', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')), Element(id='e3', type=ElementType.ANSWER, order=2, raw_text='Because.', normalized_text='Because.', provenance=Provenance(source=StructureSource.EXPLICIT, extractor='test')))
        result = SourceUnderstandingPipeline().understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=elements)
        self.assertEqual(result.document.structure.mode, StructureMode.MIXED)
        self.assertTrue(result.region_result.mixed)

    def test_pipeline_manifest_records_component_policies_and_preserves_existing_config(self):
        result = SourceUnderstandingPipeline().understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        config = result.document.processing.configuration
        self.assertEqual(config['adapter']['preserve_raw'], True)
        manifest = config['source_understanding_pipeline']
        self.assertEqual(manifest['pipeline_version'], '1')
        self.assertEqual(manifest['content_profiler_version'], '1')
        self.assertEqual(manifest['structure_signal_version'], '1')
        self.assertIn('structure_signal_policy', manifest)
        self.assertIn('section_markers', manifest['structure_signal_policy'])
        self.assertIn('boundary_policy', manifest)
        self.assertIn('grouping_policy', manifest)
        self.assertIn('hierarchy_policy', manifest)
        self.assertIn('relation_policy', manifest)
        self.assertIn('structure_quality_policy', manifest)

    def test_stage_errors_are_localized_and_preserve_original_cause(self):
        class BrokenProfiler:
            def analyze(self, elements):
                raise ValueError('bad profile')
        pipeline = SourceUnderstandingPipeline(profiler=BrokenProfiler())
        with self.assertRaisesRegex(SourceUnderstandingPipelineError, 'content profiling failed') as ctx:
            pipeline.understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_pipeline_rejects_stage_count_drift_before_assembly(self):
        class WrongProfiler:
            class Result:
                version = '1'
                element_count = 99
            def analyze(self, elements):
                return self.Result()
        pipeline = SourceUnderstandingPipeline(profiler=WrongProfiler())
        with self.assertRaisesRegex(SourceUnderstandingPipelineError, 'element_count mismatch'):
            pipeline.understand(document_id='doc1', content_hash=HASH, processing=processing(), elements=make_elements())
if __name__ == '__main__':
    unittest.main()
