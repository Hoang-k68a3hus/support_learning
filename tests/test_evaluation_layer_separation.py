from __future__ import annotations

import unittest
from types import SimpleNamespace

from source_understanding.evaluation.element_scoring import ElementScorer
from source_understanding.evaluation.report import EvaluationErrorType
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.source_attributes import HEADING_LEVEL_ATTRIBUTE


class EvaluationLayerSeparationTests(unittest.TestCase):
    @staticmethod
    def _prediction(*, source_level: int, context_level: int):
        element = Element(
            id="p1",
            order=0,
            type=ElementType.HEADING,
            raw_text="Heading",
            normalized_text="Heading",
            attributes={HEADING_LEVEL_ATTRIBUTE: source_level},
            provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
        )
        return SimpleNamespace(
            elements=(element,),
            context_nodes=(
                SimpleNamespace(
                    attributes={"anchor_element_id": "p1"},
                    level=context_level,
                ),
            ),
        )

    @staticmethod
    def _gold(*, source_level: int):
        return SimpleNamespace(
            elements=(
                SimpleNamespace(
                    id="g1",
                    required=True,
                    type=ElementType.HEADING,
                    heading_level=source_level,
                ),
            )
        )

    @staticmethod
    def _alignment():
        return SimpleNamespace(gold_to_predicted={"g1": "p1"})

    def test_source_heading_metric_ignores_different_inferred_context_level(self):
        errors = []
        score = ElementScorer().heading_levels(
            self._gold(source_level=4),
            self._prediction(source_level=4, context_level=1),
            self._alignment(),
            errors,
        )

        self.assertEqual(score.accuracy, 1.0)
        self.assertEqual(errors, [])

    def test_context_level_cannot_mask_wrong_source_heading_level(self):
        errors = []
        score = ElementScorer().heading_levels(
            self._gold(source_level=1),
            self._prediction(source_level=4, context_level=1),
            self._alignment(),
            errors,
        )

        self.assertEqual(score.accuracy, 0.0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].type, EvaluationErrorType.HEADING_LEVEL_MISMATCH)
        self.assertEqual(errors[0].metadata["metric_scope"], "source_element_heading_level")


if __name__ == "__main__":
    unittest.main()
