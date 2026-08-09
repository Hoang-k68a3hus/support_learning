from __future__ import annotations

import unittest

from benchmarks.semantic_roles_v0_1.run_benchmark import (
    GOLD_PATH,
    heuristic_quality_gate,
    heuristic_annotator_policy,
    heuristic_provider,
    materialize_case,
)
from source_understanding.evaluation import load_semantic_gold_dataset
from source_understanding.evaluation.schemas import BenchmarkSplit
from source_understanding.retrieval_units import (
    RetrievalUnitBuilder,
    SemanticRetrievalEnricher,
)
from source_understanding.semantics import SemanticAnnotator


def token_count(text: str) -> int:
    return len(text.split())


class SemanticQualityGateEndToEndTests(unittest.TestCase):
    def test_evaluated_annotations_can_enrich_retrieval_without_mutating_source_view(self) -> None:
        dataset = load_semantic_gold_dataset(GOLD_PATH)
        test_case = next(
            case
            for case in dataset.cases
            if case.split == BenchmarkSplit.TEST
            and case.document_id == "semantic-vi-roles"
        )
        source_document = materialize_case(test_case)
        enriched_document = SemanticAnnotator(
            heuristic_provider(),
            heuristic_annotator_policy(),
        ).annotate(source_document).document
        base_units = RetrievalUnitBuilder(token_count).build(enriched_document).units
        gate = heuristic_quality_gate()

        result = SemanticRetrievalEnricher(
            token_count,
            quality_gate=gate,
        ).enrich(enriched_document, base_units)

        self.assertGreater(result.enriched_unit_count, 0)
        first_base = base_units[0]
        first_enriched = result.units[0]
        self.assertIn(
            "Định nghĩa: Hàng đợi tuân theo nguyên tắc FIFO.",
            first_enriched.retrieval_text,
        )
        self.assertEqual(first_enriched.display_text, first_base.display_text)
        self.assertEqual(first_enriched.source_anchors, first_base.source_anchors)
        self.assertEqual(result.quality_gate.report_hash, gate.report_hash)
        first_enriched.validate_against_document(enriched_document)


if __name__ == "__main__":
    unittest.main()
