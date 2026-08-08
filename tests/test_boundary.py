from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance, StyleInfo
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryError,
    BoundaryIntegrityGuard,
    BoundaryReason,
    BoundaryScorer,
)
from source_understanding.structure.signals import (
    StructureSignal,
    StructureSignalKind,
    StructureSignalSet,
)


def element(
    element_id: str,
    order: int,
    element_type: ElementType,
    *,
    text: str = "text",
    source: StructureSource = StructureSource.EXPLICIT,
    style: StyleInfo | None = None,
) -> Element:
    return Element(
        id=element_id,
        order=order,
        type=element_type,
        raw_text=text,
        style=style,
        provenance=Provenance(source=source, extractor="test"),
    )


def sig(
    signal_id: str,
    kind: StructureSignalKind,
    element_ids: tuple[str, ...],
    *,
    source: StructureSource = StructureSource.INFERRED,
    text_value: str | None = None,
) -> StructureSignal:
    return StructureSignal(
        id=signal_id,
        kind=kind,
        element_ids=element_ids,
        source=source,
        text_value=text_value,
    )


def signals(elements: tuple[Element, ...], *items: StructureSignal) -> StructureSignalSet:
    base = [
        sig(
            f"type_{item.id}",
            StructureSignalKind.ELEMENT_TYPE,
            (item.id,),
            source=item.provenance.source,
            text_value=item.type.value,
        )
        for item in elements
    ]
    return StructureSignalSet(element_count=len(elements), signals=tuple(base + list(items)))


class BoundaryScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scorer = BoundaryScorer()

    def test_explicit_heading_start_is_hard(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.HEADING),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.HARD)
        self.assertIn(BoundaryReason.EXPLICIT_STRUCTURE_START, decision.reasons)
        self.assertEqual(decision.source, StructureSource.DERIVED)

    def test_inferred_heading_is_not_hard_from_type_alone(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.HEADING, source=StructureSource.INFERRED),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.SOFT)
        self.assertNotIn(BoundaryReason.EXPLICIT_STRUCTURE_START, decision.reasons)

    def test_separator_is_hard(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.SEPARATOR),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.HARD)
        self.assertIn(BoundaryReason.SEPARATOR, decision.reasons)

    def test_table_continuity_is_unknown_without_block_identity(self) -> None:
        elements = (
            element("e0", 0, ElementType.TABLE_ROW),
            element("e1", 1, ElementType.TABLE_CELL),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.UNKNOWN)
        self.assertIsNone(decision.integrity_guard)
        self.assertIn(BoundaryReason.CONTENT_INTEGRITY_UNRESOLVED, decision.reasons)

    def test_entering_table_is_hard(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.TABLE),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.HARD)
        self.assertIn(BoundaryReason.TABLE_BOUNDARY, decision.reasons)

    def test_code_continuity_is_unknown_and_exit_is_hard(self) -> None:
        elements = (
            element("e0", 0, ElementType.CODE),
            element("e1", 1, ElementType.CODE),
            element("e2", 2, ElementType.PARAGRAPH),
        )
        result = self.scorer.score(elements, signals(elements))
        self.assertEqual(result.boundaries[0].classification, BoundaryClass.UNKNOWN)
        self.assertIn(
            BoundaryReason.CONTENT_INTEGRITY_UNRESOLVED,
            result.boundaries[0].reasons,
        )
        self.assertEqual(result.boundaries[1].classification, BoundaryClass.HARD)
        self.assertIn(BoundaryReason.CODE_BOUNDARY, result.boundaries[1].reasons)

    def test_question_answer_pair_is_never_split(self) -> None:
        elements = (
            element("q", 0, ElementType.QUESTION),
            element("a", 1, ElementType.ANSWER),
        )
        transition = sig(
            "t",
            StructureSignalKind.ELEMENT_TYPE_TRANSITION,
            ("q", "a"),
            source=StructureSource.DERIVED,
        )
        decision = self.scorer.score(elements, signals(elements, transition)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.NONE)
        self.assertEqual(decision.integrity_guard, BoundaryIntegrityGuard.QA_PAIR)
        self.assertGreater(decision.score, 0)

    def test_lexical_question_answer_pair_is_protected_without_mutating_types(self) -> None:
        elements = (
            element("q", 0, ElementType.PARAGRAPH, text="Q: x"),
            element("a", 1, ElementType.PARAGRAPH, text="A: y"),
        )
        decision = self.scorer.score(
            elements,
            signals(
                elements,
                sig("qm", StructureSignalKind.QUESTION_MARKER, ("q",)),
                sig("am", StructureSignalKind.ANSWER_MARKER, ("a",)),
            ),
        ).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.NONE)
        self.assertEqual(decision.integrity_guard, BoundaryIntegrityGuard.QA_PAIR)
        self.assertEqual(elements[0].type, ElementType.PARAGRAPH)
        self.assertEqual(elements[1].type, ElementType.PARAGRAPH)

    def test_list_continuity_is_unknown_without_continuity_evidence(self) -> None:
        elements = (
            element("e0", 0, ElementType.LIST_ITEM),
            element("e1", 1, ElementType.LIST_ITEM),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.UNKNOWN)
        self.assertIsNone(decision.integrity_guard)
        self.assertIn(BoundaryReason.CONTENT_INTEGRITY_UNRESOLVED, decision.reasons)

    def test_paragraph_break_is_soft(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.PARAGRAPH),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.SOFT)
        self.assertIn(BoundaryReason.PARAGRAPH_BREAK, decision.reasons)

    def test_unknown_pair_without_evidence_stays_unknown(self) -> None:
        elements = (
            element("e0", 0, ElementType.UNKNOWN),
            element("e1", 1, ElementType.UNKNOWN),
        )
        decision = self.scorer.score(elements, signals(elements)).boundaries[0]
        self.assertEqual(decision.classification, BoundaryClass.UNKNOWN)
        self.assertIn(BoundaryReason.INSUFFICIENT_EVIDENCE, decision.reasons)

    def test_pattern_and_style_evidence_accumulate_without_becoming_source_fact(self) -> None:
        elements = (
            element(
                "e0",
                0,
                ElementType.PARAGRAPH,
                style=StyleInfo(font_size=11, bold=False, indentation=0, alignment="left"),
            ),
            element(
                "e1",
                1,
                ElementType.PARAGRAPH,
                style=StyleInfo(font_size=16, bold=True, indentation=0, alignment="left"),
            ),
        )
        marker = sig("sec", StructureSignalKind.SECTION_MARKER, ("e1",))
        decision = self.scorer.score(elements, signals(elements, marker)).boundaries[0]
        self.assertEqual(decision.source, StructureSource.DERIVED)
        self.assertEqual(decision.classification, BoundaryClass.HARD)
        self.assertIn(BoundaryReason.PATTERN_START, decision.reasons)
        self.assertIn(BoundaryReason.STYLE_CHANGE, decision.reasons)
        self.assertIn("sec", decision.signal_ids)

    def test_single_element_produces_no_boundaries(self) -> None:
        elements = (element("e0", 0, ElementType.PARAGRAPH),)
        result = self.scorer.score(elements, signals(elements))
        self.assertEqual(result.boundaries, ())

    def test_rejects_mismatched_and_invalid_signal_references(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.CODE),
        )
        with self.assertRaises(BoundaryError):
            self.scorer.score(elements, StructureSignalSet(element_count=1, signals=()))

        bad = StructureSignalSet(
            element_count=2,
            signals=(sig("bad", StructureSignalKind.SECTION_MARKER, ("missing",)),),
        )
        with self.assertRaises(BoundaryError):
            self.scorer.score(elements, bad)

    def test_rejects_missing_or_mismatched_element_type_signal(self) -> None:
        elements = (element("e0", 0, ElementType.PARAGRAPH),)
        with self.assertRaises(BoundaryError):
            self.scorer.score(elements, StructureSignalSet(element_count=1, signals=()))

        wrong = StructureSignalSet(
            element_count=1,
            signals=(
                sig(
                    "wrong",
                    StructureSignalKind.ELEMENT_TYPE,
                    ("e0",),
                    source=StructureSource.EXPLICIT,
                    text_value="HEADING",
                ),
            ),
        )
        with self.assertRaises(BoundaryError):
            self.scorer.score(elements, wrong)

    def test_rejects_nonadjacent_transition_and_is_deterministic(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.PARAGRAPH),
            element("e2", 2, ElementType.CODE),
        )
        bad_transition = sig(
            "bad-transition",
            StructureSignalKind.ELEMENT_TYPE_TRANSITION,
            ("e0", "e2"),
            source=StructureSource.DERIVED,
        )
        with self.assertRaises(BoundaryError):
            self.scorer.score(elements, signals(elements, bad_transition))

        good = signals(elements)
        self.assertEqual(self.scorer.score(elements, good), self.scorer.score(elements, good))


if __name__ == "__main__":
    unittest.main()
