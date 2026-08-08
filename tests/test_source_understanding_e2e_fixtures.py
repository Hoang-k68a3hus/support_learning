from __future__ import annotations

import unittest
from datetime import datetime, timezone

from source_understanding.pipeline import SourceUnderstandingPipeline
from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.document import ProcessingManifest
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnitType

HASH = "sha256:" + "8" * 64


def processing():
    return ProcessingManifest(
        adapter_name="fixture",
        processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def el(element_id: str, order: int, element_type: ElementType, text: str) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="fixture"),
    )


def understand(elements):
    return SourceUnderstandingPipeline().understand(
        document_id="fixture-doc",
        content_hash=HASH,
        processing=processing(),
        elements=tuple(elements),
    )


class SourceUnderstandingE2EFixtures(unittest.TestCase):
    def test_flat_text_is_valid_without_invented_hierarchy(self):
        result = understand(
            (
                el("p1", 0, ElementType.PARAGRAPH, "First paragraph."),
                el("p2", 1, ElementType.PARAGRAPH, "Second paragraph."),
            )
        )
        self.assertNotEqual(result.document.structure.mode, StructureMode.MIXED)
        self.assertTrue(result.completion_report.structural_ready)
        self.assertEqual(result.completion_report.metrics.unresolved_integrity_count, 0)

    def test_faq_is_routed_as_one_qa_region(self):
        result = understand(
            (
                el("q1", 0, ElementType.QUESTION, "What is caching?"),
                el("a1", 1, ElementType.ANSWER, "Caching stores reusable results."),
                el("q2", 2, ElementType.QUESTION, "Why use it?"),
                el("a2", 3, ElementType.ANSWER, "It reduces repeated work."),
            )
        )
        self.assertEqual(len(result.document.regions), 1)
        self.assertEqual(result.document.regions[0].metadata["routing_category"], "qa")
        self.assertTrue(result.completion_report.structural_ready)

    def test_dialogue_and_log_are_specialized_local_documents(self):
        dialogue = understand(
            (
                el("d1", 0, ElementType.DIALOGUE_TURN, "A: Hello"),
                el("d2", 1, ElementType.DIALOGUE_TURN, "B: Hi"),
            )
        )
        log = understand(
            (
                el("l1", 0, ElementType.LOG_ENTRY, "10:00 started"),
                el("l2", 1, ElementType.LOG_ENTRY, "10:01 finished"),
            )
        )
        self.assertEqual(dialogue.document.regions[0].metadata["routing_category"], "dialogue")
        self.assertEqual(log.document.regions[0].metadata["routing_category"], "log")
        self.assertEqual(dialogue.document.structure.mode, StructureMode.LOCAL)
        self.assertEqual(log.document.structure.mode, StructureMode.LOCAL)

    def test_granular_table_is_consolidated_before_region_routing(self):
        result = understand(
            (
                el("r1", 0, ElementType.TABLE_ROW, "Name | Score"),
                el("c1", 1, ElementType.TABLE_CELL, "Alice"),
                el("c2", 2, ElementType.TABLE_CELL, "90"),
                el("r2", 3, ElementType.TABLE_ROW, "Bob | 80"),
            )
        )
        table_units = [
            unit for unit in result.document.logical_units
            if unit.type == LogicalUnitType.TABLE_BLOCK
        ]
        self.assertEqual(len(table_units), 1)
        self.assertEqual(table_units[0].element_ids, ("r1", "c1", "c2", "r2"))
        self.assertEqual(result.completion_report.metrics.integrity_sensitive_ungrouped_count, 0)

    def test_narrative_plus_qa_is_mixed_with_exact_region_coverage(self):
        result = understand(
            (
                el("p1", 0, ElementType.PARAGRAPH, "Background."),
                el("q1", 1, ElementType.QUESTION, "Question?"),
                el("a1", 2, ElementType.ANSWER, "Answer."),
            )
        )
        self.assertEqual(result.document.structure.mode, StructureMode.MIXED)
        self.assertEqual(result.completion_report.metrics.region_coverage_ratio, 1.0)
        self.assertTrue(result.completion_report.structural_ready)

    def test_small_embedded_code_does_not_force_mixed_structure(self):
        result = understand(
            (
                el("p1", 0, ElementType.PARAGRAPH, "Explanation before."),
                el("c1", 1, ElementType.CODE, "x = 1"),
                el("p2", 2, ElementType.PARAGRAPH, "Explanation after."),
            )
        )
        self.assertNotEqual(result.document.structure.mode, StructureMode.MIXED)
        code_units = [
            unit for unit in result.document.logical_units
            if unit.type == LogicalUnitType.CODE_BLOCK
        ]
        self.assertEqual(len(code_units), 1)
        self.assertTrue(result.completion_report.structural_ready)


if __name__ == "__main__":
    unittest.main()
