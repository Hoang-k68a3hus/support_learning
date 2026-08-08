from __future__ import annotations

import unittest
from datetime import datetime, timezone

from source_understanding.pipeline import SemanticStageStatus, SourceUnderstandingPipeline
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import ProcessingManifest
from source_understanding.schemas.element import Element, ElementType, Provenance

HASH = "sha256:" + "7" * 64


def processing():
    return ProcessingManifest(
        adapter_name="test",
        processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def element(element_id, order, element_type, text):
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


class CompletionReportTests(unittest.TestCase):
    def test_flat_narrative_can_be_structurally_ready_without_fake_hierarchy(self):
        result = SourceUnderstandingPipeline().understand(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=(element("p1", 0, ElementType.PARAGRAPH, "plain text"),),
        )
        report = result.completion_report
        self.assertTrue(report.structural_pipeline_complete)
        self.assertTrue(report.structural_ready)
        self.assertEqual(report.semantic_status, SemanticStageStatus.NOT_CONFIGURED.value)
        self.assertTrue(report.diagnostics["completion_is_not_accuracy"])

    def test_table_integrity_is_reported_as_resolved_after_consolidation(self):
        result = SourceUnderstandingPipeline().understand(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=(
                element("r1", 0, ElementType.TABLE_ROW, "row 1"),
                element("c1", 1, ElementType.TABLE_CELL, "cell"),
                element("r2", 2, ElementType.TABLE_ROW, "row 2"),
            ),
        )
        report = result.completion_report
        self.assertTrue(report.structural_ready)
        self.assertEqual(report.metrics.integrity_sensitive_ungrouped_count, 0)
        self.assertEqual(report.metrics.unresolved_integrity_count, 0)
        self.assertEqual(report.metrics.region_coverage_ratio, 1.0)

    def test_optional_semantic_failure_does_not_make_structure_unready(self):
        class BrokenSemantic:
            def annotate(self, document):
                raise RuntimeError("offline")

        result = SourceUnderstandingPipeline(semantic_annotator=BrokenSemantic()).understand(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=(element("p1", 0, ElementType.PARAGRAPH, "plain text"),),
        )
        report = result.completion_report
        self.assertTrue(report.structural_ready)
        self.assertEqual(report.semantic_status, SemanticStageStatus.FAILED_OPTIONAL.value)
        self.assertTrue(any("semantic enrichment failed" in warning for warning in report.warnings))


if __name__ == "__main__":
    unittest.main()
