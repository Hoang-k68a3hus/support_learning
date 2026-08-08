from __future__ import annotations

import unittest

from source_understanding.profiling import (
    ContentCategory,
    ContentProfiler,
    ContentProfilingError,
)
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance


def element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str | None = "text",
    *,
    excluded: bool = False,
) -> Element:
    return Element(
        id=element_id,
        type=element_type,
        order=order,
        raw_text=text,
        provenance=Provenance(
            source=StructureSource.EXPLICIT,
            extractor="test",
            confidence=1.0,
        ),
        exclude_from_retrieval=excluded,
    )


class ContentProfilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiler = ContentProfiler()

    def test_profiles_mixed_content_as_distribution_not_document_type(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 1, ElementType.LIST_ITEM),
            element("e2", 2, ElementType.DIALOGUE_TURN),
            element("e3", 3, ElementType.CODE),
            element("e4", 4, ElementType.TABLE),
            element("e5", 5, ElementType.QUESTION),
        )
        profile = self.profiler.analyze(elements)

        self.assertEqual(profile.element_count, 6)
        for category in (
            ContentCategory.NARRATIVE,
            ContentCategory.LIST,
            ContentCategory.DIALOGUE,
            ContentCategory.CODE,
            ContentCategory.TABLE,
            ContentCategory.QA,
        ):
            self.assertAlmostEqual(profile.category_distribution[category.value], 1 / 6)
        self.assertIsNone(profile.dominant_category)
        self.assertIsNone(profile.dominant_share)
        self.assertAlmostEqual(sum(profile.category_distribution.values()), 1.0)
        self.assertAlmostEqual(sum(profile.element_type_distribution.values()), 1.0)

    def test_signals_are_observed_counts_only(self) -> None:
        elements = (
            element("e0", 0, ElementType.TITLE),
            element("e1", 1, ElementType.HEADING),
            element("e2", 2, ElementType.LIST),
            element("e3", 3, ElementType.LIST_ITEM),
            element("e4", 4, ElementType.DIALOGUE_TURN),
            element("e5", 5, ElementType.TABLE),
            element("e6", 6, ElementType.TABLE_CELL),
            element("e7", 7, ElementType.QUESTION),
            element("e8", 8, ElementType.ANSWER),
        )
        signals = self.profiler.analyze(elements).signals

        self.assertEqual(signals.title_count, 1)
        self.assertEqual(signals.heading_count, 1)
        self.assertEqual(signals.list_count, 1)
        self.assertEqual(signals.list_item_count, 1)
        self.assertEqual(signals.speaker_turn_count, 1)
        self.assertEqual(signals.table_count, 1)
        self.assertEqual(signals.table_cell_count, 1)
        self.assertEqual(signals.question_count, 1)
        self.assertEqual(signals.answer_count, 1)

    def test_does_not_infer_question_from_text(self) -> None:
        profile = self.profiler.analyze(
            (element("e0", 0, ElementType.PARAGRAPH, "Q: What is SQL?"),)
        )
        self.assertEqual(profile.signals.question_count, 0)
        self.assertEqual(profile.category_distribution[ContentCategory.QA.value], 0.0)
        self.assertEqual(profile.category_distribution[ContentCategory.NARRATIVE.value], 1.0)

    def test_unknown_type_is_explicitly_profiled(self) -> None:
        profile = self.profiler.analyze((element("e0", 0, ElementType.UNKNOWN),))
        self.assertEqual(profile.signals.unknown_count, 1)
        self.assertEqual(profile.signals.typed_element_ratio, 0.0)
        self.assertEqual(profile.category_distribution[ContentCategory.UNKNOWN.value], 1.0)
        self.assertEqual(profile.dominant_category, ContentCategory.UNKNOWN)
        self.assertEqual(profile.dominant_share, 1.0)

    def test_category_switch_ratio_uses_canonical_adjacency(self) -> None:
        profile = self.profiler.analyze(
            (
                element("e0", 0, ElementType.PARAGRAPH),
                element("e1", 1, ElementType.SENTENCE),
                element("e2", 2, ElementType.CODE),
                element("e3", 3, ElementType.CODE),
                element("e4", 4, ElementType.TABLE),
            )
        )
        self.assertEqual(profile.signals.category_switch_count, 2)
        self.assertEqual(profile.signals.category_switch_ratio, 0.5)

    def test_excluded_elements_remain_in_source_profile(self) -> None:
        profile = self.profiler.analyze(
            (
                element("e0", 0, ElementType.HEADER, excluded=True),
                element("e1", 1, ElementType.PARAGRAPH),
            )
        )
        self.assertEqual(profile.element_count, 2)
        self.assertEqual(profile.signals.excluded_from_retrieval_count, 1)
        self.assertEqual(profile.category_distribution[ContentCategory.BOILERPLATE.value], 0.5)

    def test_rejects_duplicate_ids_orders_and_nonascending_order(self) -> None:
        with self.assertRaises(ContentProfilingError):
            self.profiler.analyze(
                (
                    element("same", 0, ElementType.PARAGRAPH),
                    element("same", 1, ElementType.PARAGRAPH),
                )
            )
        with self.assertRaises(ContentProfilingError):
            self.profiler.analyze(
                (
                    element("e0", 0, ElementType.PARAGRAPH),
                    element("e1", 0, ElementType.PARAGRAPH),
                )
            )
        with self.assertRaises(ContentProfilingError):
            self.profiler.analyze(
                (
                    element("e0", 2, ElementType.PARAGRAPH),
                    element("e1", 1, ElementType.PARAGRAPH),
                )
            )

    def test_rejects_empty_input(self) -> None:
        with self.assertRaises(ContentProfilingError):
            self.profiler.analyze(())

    def test_same_input_is_deterministic(self) -> None:
        elements = (
            element("e0", 0, ElementType.PARAGRAPH),
            element("e1", 3, ElementType.CODE),
        )
        self.assertEqual(self.profiler.analyze(elements), self.profiler.analyze(elements))


if __name__ == "__main__":
    unittest.main()
