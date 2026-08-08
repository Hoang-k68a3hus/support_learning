from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import (
    Element,
    ElementConfidence,
    ElementType,
    Provenance,
    StyleInfo,
)
from source_understanding.structure import (
    StructureSignalError,
    StructureSignalExtractor,
    StructureSignalKind,
)


def element(
    element_id: str,
    order: int,
    element_type: ElementType = ElementType.PARAGRAPH,
    text: str | None = "text",
    *,
    style: StyleInfo | None = None,
    source: StructureSource = StructureSource.EXPLICIT,
    type_confidence: float | None = None,
) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        style=style,
        confidence=ElementConfidence(type=type_confidence),
        provenance=Provenance(source=source, extractor="test"),
    )


class StructureSignalExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = StructureSignalExtractor()

    def test_element_type_signal_preserves_upstream_provenance(self) -> None:
        result = self.extractor.extract(
            (
                element(
                    "e0",
                    0,
                    ElementType.HEADING,
                    source=StructureSource.INFERRED,
                    type_confidence=0.7,
                ),
            )
        )
        signal = result.signals[0]
        self.assertEqual(signal.kind, StructureSignalKind.ELEMENT_TYPE)
        self.assertEqual(signal.text_value, "HEADING")
        self.assertEqual(signal.source, StructureSource.INFERRED)
        self.assertEqual(signal.confidence, 0.7)

    def test_style_is_emitted_as_observation_not_heading_claim(self) -> None:
        result = self.extractor.extract(
            (
                element(
                    "e0",
                    0,
                    style=StyleInfo(font_size=18, bold=True, indentation=12),
                ),
            )
        )
        kinds = [signal.kind for signal in result.signals]
        self.assertIn(StructureSignalKind.STYLE_BOLD, kinds)
        self.assertIn(StructureSignalKind.STYLE_FONT_SIZE, kinds)
        self.assertIn(StructureSignalKind.STYLE_INDENTATION, kinds)
        self.assertNotIn(StructureSignalKind.SECTION_MARKER, kinds)
        self.assertEqual(result.signals[0].text_value, "PARAGRAPH")

    def test_numbering_and_section_markers_are_inferred_evidence_only(self) -> None:
        result = self.extractor.extract(
            (
                element("e0", 0, text="1.2 Retrieval"),
                element("e1", 1, text="Điều 5. Phạm vi"),
            )
        )
        numbering = next(
            signal
            for signal in result.signals
            if signal.kind == StructureSignalKind.NUMBERING_MARKER
        )
        section = next(
            signal
            for signal in result.signals
            if signal.kind == StructureSignalKind.SECTION_MARKER
        )
        self.assertEqual(numbering.source, StructureSource.INFERRED)
        self.assertEqual(section.source, StructureSource.INFERRED)
        self.assertTrue(all("BOUNDARY" not in signal.kind.name for signal in result.signals))

    def test_question_and_answer_prefixes_do_not_mutate_element_type(self) -> None:
        q = element("e0", 0, ElementType.PARAGRAPH, "Q: What is SQL?")
        a = element("e1", 1, ElementType.PARAGRAPH, "Answer: A query language.")
        result = self.extractor.extract((q, a))
        kinds = [signal.kind for signal in result.signals]
        self.assertIn(StructureSignalKind.QUESTION_MARKER, kinds)
        self.assertIn(StructureSignalKind.ANSWER_MARKER, kinds)
        element_type_values = [
            signal.text_value
            for signal in result.signals
            if signal.kind == StructureSignalKind.ELEMENT_TYPE
        ]
        self.assertEqual(element_type_values, ["PARAGRAPH", "PARAGRAPH"])

    def test_code_text_is_not_lexically_reinterpreted(self) -> None:
        result = self.extractor.extract(
            (element("e0", 0, ElementType.CODE, "Q: not a real question"),)
        )
        kinds = [signal.kind for signal in result.signals]
        self.assertEqual(kinds, [StructureSignalKind.ELEMENT_TYPE])

    def test_timestamp_and_speaker_patterns_are_candidates(self) -> None:
        result = self.extractor.extract(
            (
                element("e0", 0, text="[12:30] started"),
                element("e1", 1, text="Alice: hello"),
            )
        )
        kinds = [signal.kind for signal in result.signals]
        self.assertIn(StructureSignalKind.TIMESTAMP_PATTERN, kinds)
        self.assertIn(StructureSignalKind.SPEAKER_LABEL_CANDIDATE, kinds)

    def test_type_transition_is_derived_evidence_not_boundary(self) -> None:
        result = self.extractor.extract(
            (
                element("e0", 0, ElementType.PARAGRAPH),
                element("e1", 1, ElementType.CODE),
            )
        )
        transition = next(
            signal
            for signal in result.signals
            if signal.kind == StructureSignalKind.ELEMENT_TYPE_TRANSITION
        )
        self.assertEqual(transition.source, StructureSource.DERIVED)
        self.assertEqual(transition.element_ids, ("e0", "e1"))
        self.assertEqual(transition.metadata["from_type"], "PARAGRAPH")
        self.assertEqual(transition.metadata["to_type"], "CODE")

    def test_custom_section_markers_are_supported(self) -> None:
        extractor = StructureSignalExtractor(section_markers=("article",))
        result = extractor.extract((element("e0", 0, text="Article 4 Scope"),))
        self.assertIn(
            StructureSignalKind.SECTION_MARKER,
            [signal.kind for signal in result.signals],
        )

    def test_rejects_empty_duplicate_and_unsorted_inputs(self) -> None:
        with self.assertRaises(StructureSignalError):
            self.extractor.extract(())
        with self.assertRaises(StructureSignalError):
            self.extractor.extract((element("same", 0), element("same", 1)))
        with self.assertRaises(StructureSignalError):
            self.extractor.extract((element("e0", 0), element("e1", 0)))
        with self.assertRaises(StructureSignalError):
            self.extractor.extract((element("e0", 2), element("e1", 1)))

    def test_same_input_is_deterministic(self) -> None:
        elements = (
            element("e0", 0, text="1. Intro"),
            element("e1", 5, ElementType.CODE, "print(1)"),
        )
        self.assertEqual(
            self.extractor.extract(elements),
            self.extractor.extract(elements),
        )


if __name__ == "__main__":
    unittest.main()
