from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldEligibilityPolicy,
    SemanticGoldCompiler,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticEvidenceSpan,
    SemanticTextView,
)
from source_understanding.semantics import SemanticTargetKind

from ._gold_compiler_fixtures import (
    adjudicated_record,
    positive_decision,
)
from ._validation_fixtures import canonical_document


class SemanticGoldCompilerEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = SemanticGoldCompiler()
        self.policy = GoldEligibilityPolicy()

    def compile_record(self, record):
        return self.compiler.compile_document(
            document=canonical_document(),
            records=(record,),
            split=DatasetSplit.DEV,
            policy=self.policy,
        )

    def test_element_evidence_maps_id_to_order_without_rewriting_offsets(self) -> None:
        evidence = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=0,
            end_char=8,
            quoted_text="Gradient",
            text_view=SemanticTextView.RAW_TEXT,
        )
        record = adjudicated_record(
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
            decisions=(
                positive_decision(
                    SemanticAnnotationType.CONCEPT,
                    value="Gradient",
                    evidence=(evidence,),
                ),
            ),
        )

        annotation = self.compile_record(record).annotations[0]
        span = annotation.evidence[0]
        self.assertEqual(span.element_order, 0)
        self.assertEqual(span.start_char, evidence.start_char)
        self.assertEqual(span.end_char, evidence.end_char)
        self.assertEqual(span.quoted_text, evidence.quoted_text)
        self.assertEqual(span.text_view, SemanticTextView.RAW_TEXT)

    def test_logical_unit_preserves_raw_and_normalized_spans_canonically(self) -> None:
        raw_second = SemanticEvidenceSpan(
            element_id="e-2",
            start_char=0,
            end_char=9,
            quoted_text="minimizes",
            text_view=SemanticTextView.RAW_TEXT,
        )
        normalized_first = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=0,
            end_char=16,
            quoted_text="Gradient descent",
            text_view=SemanticTextView.NORMALIZED_TEXT,
        )
        record = adjudicated_record(
            decisions=(
                positive_decision(
                    SemanticAnnotationType.CONCEPT,
                    value="Gradient descent",
                    evidence=(raw_second, normalized_first),
                ),
            )
        )

        annotation = self.compile_record(record).annotations[0]

        self.assertEqual(annotation.value, "Gradient descent")
        self.assertEqual(
            tuple(span.element_order for span in annotation.evidence),
            (0, 1),
        )
        self.assertEqual(
            tuple(span.text_view for span in annotation.evidence),
            (SemanticTextView.NORMALIZED_TEXT, SemanticTextView.RAW_TEXT),
        )
        self.assertEqual(annotation.evidence[0].start_char, 0)
        self.assertEqual(annotation.evidence[0].end_char, 16)

    def test_label_only_positive_keeps_optional_source_evidence(self) -> None:
        evidence = SemanticEvidenceSpan(
            element_id="e-1",
            start_char=0,
            end_char=8,
            quoted_text="Gradient",
            text_view=SemanticTextView.RAW_TEXT,
        )
        record = adjudicated_record(
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
            decisions=(
                positive_decision(
                    SemanticAnnotationType.DEFINITION,
                    evidence=(evidence,),
                ),
            ),
        )

        annotation = self.compile_record(record).annotations[0]

        self.assertEqual(len(annotation.evidence), 1)
        self.assertEqual(annotation.evidence[0].quoted_text, "Gradient")


if __name__ == "__main__":
    unittest.main()
