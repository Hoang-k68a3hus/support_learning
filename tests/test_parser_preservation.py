from __future__ import annotations

import unittest

from source_understanding.atomic.normalizer import ElementNormalizer
from source_understanding.evaluation.preservation import evaluate_parser_preservation
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Provenance, RawElement


def raw(order: int, text: str) -> RawElement:
    return RawElement(
        text=text,
        type_hint="paragraph",
        order=order,
        attributes={"source_order": order},
        provenance=Provenance(
            source=StructureSource.EXPLICIT,
            extractor="test-adapter",
            extractor_version="1",
        ),
    )


class ParserPreservationTests(unittest.TestCase):
    def test_normalization_preserves_every_source_near_fact(self) -> None:
        raw_elements = (raw(0, "alpha\r\nline"), raw(1, "beta"))
        normalized = ElementNormalizer().normalize(raw_elements, document_id="doc1")

        report = evaluate_parser_preservation(raw_elements, normalized.elements)

        self.assertTrue(report.fully_preserved)
        self.assertEqual(report.raw_text_preservation_ratio, 1.0)
        self.assertEqual(report.type_hint_preservation_ratio, 1.0)
        self.assertEqual(report.exact_element_ratio, 1.0)
        self.assertEqual(report.type_hint_preserved_count, 2)
        self.assertEqual(normalized.elements[0].source_type_hint, "paragraph")
        self.assertEqual(report.issues, ())

    def test_audit_reports_loss_without_repairing_it(self) -> None:
        raw_elements = (raw(0, "alpha"), raw(1, "beta"))
        normalized = ElementNormalizer().normalize(raw_elements, document_id="doc1")
        lossy = (
            normalized.elements[0].model_copy(update={"raw_text": "changed"}),
        )

        report = evaluate_parser_preservation(raw_elements, lossy)

        self.assertFalse(report.fully_preserved)
        self.assertFalse(report.cardinality_preserved)
        self.assertFalse(report.order_preserved)
        self.assertEqual(report.raw_text_preservation_ratio, 0.0)
        self.assertTrue(any("raw_text" in issue for issue in report.issues))

    def test_audit_detects_lost_source_type_hint(self) -> None:
        raw_elements = (raw(0, "alpha"),)
        normalized = ElementNormalizer().normalize(raw_elements, document_id="doc1")
        without_hint = normalized.elements[0].model_copy(
            update={"source_type_hint": None}
        )

        report = evaluate_parser_preservation(raw_elements, (without_hint,))

        self.assertFalse(report.fully_preserved)
        self.assertEqual(report.type_hint_preserved_count, 0)
        self.assertEqual(report.type_hint_preservation_ratio, 0.0)
        self.assertTrue(any("source_type_hint" in issue for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
