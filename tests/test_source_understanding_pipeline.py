from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from source_understanding.pipeline import (
    SemanticFailureMode,
    SemanticStageStatus,
    SourceUnderstandingPipeline,
    SourceUnderstandingPipelineError,
    SourceUnderstandingPipelinePolicy,
)
from source_understanding.semantics import HeuristicSemanticProvider, SemanticAnnotator
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import ProcessingManifest, SemanticAnnotationType
from source_understanding.schemas.element import Element, ElementType, Provenance


HASH = "sha256:" + "a" * 64


def make_elements():
    return (
        Element(
            id="e1",
            type=ElementType.PARAGRAPH,
            order=0,
            raw_text="Definition: A queue follows FIFO.",
            normalized_text="Definition: A queue follows FIFO.",
            provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
        ),
        Element(
            id="e2",
            type=ElementType.PARAGRAPH,
            order=1,
            raw_text="Ordinary explanation.",
            normalized_text="Ordinary explanation.",
            provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
        ),
    )


def processing():
    return ProcessingManifest(
        adapter_name="test-adapter",
        adapter_version="1",
        normalizer_version="1",
        processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        configuration={"adapter": {"preserve_raw": True}},
    )


class SourceUnderstandingPipelineTests(unittest.TestCase):
    def test_structural_pipeline_is_terminal_without_semantics(self):
        result = SourceUnderstandingPipeline().understand(
            document_id="doc1",
            content_hash=HASH,
            processing=processing(),
            elements=make_elements(),
            source_revision="rev1",
        )
        self.assertEqual(result.semantic_status, SemanticStageStatus.NOT_CONFIGURED)
        self.assertEqual(result.document, result.structural_document)
        self.assertEqual(result.document.elements, make_elements())
        self.assertEqual(result.content_profile.element_count, 2)

    def test_semantics_enrich_final_document_without_mutating_structural_snapshot(self):
        pipeline = SourceUnderstandingPipeline(
            semantic_annotator=SemanticAnnotator(HeuristicSemanticProvider())
        )
        result = pipeline.understand(
            document_id="doc1",
            content_hash=HASH,
            processing=processing(),
            elements=make_elements(),
        )
        self.assertEqual(result.semantic_status, SemanticStageStatus.COMPLETED)
        self.assertEqual(result.structural_document.semantic_annotations, ())
        self.assertEqual(len(result.document.semantic_annotations), 1)
        annotation = result.document.semantic_annotations[0]
        self.assertEqual(annotation.target_id, "e1")
        self.assertEqual(annotation.type, SemanticAnnotationType.DEFINITION)
        self.assertEqual(result.document.elements, result.structural_document.elements)

    def test_optional_semantic_failure_keeps_structural_document(self):
        class BrokenSemantic:
            def annotate(self, document):
                raise RuntimeError("provider offline")

        result = SourceUnderstandingPipeline(semantic_annotator=BrokenSemantic()).understand(
            document_id="doc1",
            content_hash=HASH,
            processing=processing(),
            elements=make_elements(),
        )
        self.assertEqual(result.semantic_status, SemanticStageStatus.FAILED_OPTIONAL)
        self.assertEqual(result.document, result.structural_document)
        self.assertIn("provider offline", result.semantic_error)

    def test_strict_semantic_failure_raises_with_cause(self):
        class BrokenSemantic:
            def annotate(self, document):
                raise RuntimeError("provider offline")

        pipeline = SourceUnderstandingPipeline(
            semantic_annotator=BrokenSemantic(),
            policy=SourceUnderstandingPipelinePolicy(
                semantic_failure_mode=SemanticFailureMode.RAISE
            ),
        )
        with self.assertRaisesRegex(
            SourceUnderstandingPipelineError, "semantic enrichment failed"
        ) as ctx:
            pipeline.understand(
                document_id="doc1",
                content_hash=HASH,
                processing=processing(),
                elements=make_elements(),
            )
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_semantic_stage_cannot_mutate_source_or_structure(self):
        class MutatingSemantic:
            def annotate(self, document):
                changed = document.model_copy(
                    update={"elements": tuple(reversed(document.elements))}
                )
                return SimpleNamespace(document=changed)

        result = SourceUnderstandingPipeline(semantic_annotator=MutatingSemantic()).understand(
            document_id="doc1",
            content_hash=HASH,
            processing=processing(),
            elements=make_elements(),
        )
        self.assertEqual(result.semantic_status, SemanticStageStatus.FAILED_OPTIONAL)
        self.assertIn("mutated canonical source/structure", result.semantic_error)
        self.assertEqual(result.document.elements, make_elements())

    def test_pipeline_manifest_records_component_policies_and_preserves_existing_config(self):
        result = SourceUnderstandingPipeline().understand(
            document_id="doc1",
            content_hash=HASH,
            processing=processing(),
            elements=make_elements(),
        )
        config = result.document.processing.configuration
        self.assertEqual(config["adapter"]["preserve_raw"], True)
        manifest = config["source_understanding_pipeline"]
        self.assertEqual(manifest["pipeline_version"], "1")
        self.assertEqual(manifest["content_profiler_version"], "1")
        self.assertEqual(manifest["structure_signal_version"], "1")
        self.assertIn("boundary_policy", manifest)
        self.assertIn("grouping_policy", manifest)
        self.assertIn("hierarchy_policy", manifest)
        self.assertIn("relation_policy", manifest)
        self.assertIn("structure_quality_policy", manifest)

    def test_stage_errors_are_localized_and_preserve_original_cause(self):
        class BrokenProfiler:
            def analyze(self, elements):
                raise ValueError("bad profile")

        pipeline = SourceUnderstandingPipeline(profiler=BrokenProfiler())
        with self.assertRaisesRegex(
            SourceUnderstandingPipelineError, "content profiling failed"
        ) as ctx:
            pipeline.understand(
                document_id="doc1",
                content_hash=HASH,
                processing=processing(),
                elements=make_elements(),
            )
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_pipeline_rejects_stage_count_drift_before_assembly(self):
        class WrongProfiler:
            class Result:
                version = "1"
                element_count = 99

            def analyze(self, elements):
                return self.Result()

        pipeline = SourceUnderstandingPipeline(profiler=WrongProfiler())
        with self.assertRaisesRegex(
            SourceUnderstandingPipelineError, "element_count mismatch"
        ):
            pipeline.understand(
                document_id="doc1",
                content_hash=HASH,
                processing=processing(),
                elements=make_elements(),
            )


if __name__ == "__main__":
    unittest.main()
