from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldEligibilityPolicy,
    SemanticGoldCompiler,
)
from source_understanding.evaluation import SemanticRoleEvaluator
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import (
    SemanticAnnotation,
    SemanticAnnotationType,
)
from source_understanding.semantics import SemanticTargetKind

from ._gold_compiler_fixtures import (
    adjudicated_record,
    negative_decision,
    positive_decision,
)
from ._validation_fixtures import canonical_document


class SemanticGoldCompilerScopeTests(unittest.TestCase):
    def test_real_evaluator_scores_only_compiled_target_type_pairs(self) -> None:
        document = canonical_document()
        negative_element = adjudicated_record(
            document=document,
            record_id="record-element",
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
            decisions=(negative_decision(SemanticAnnotationType.DEFINITION),),
        )
        positive_logical = adjudicated_record(
            document=document,
            record_id="record-logical",
            decisions=(positive_decision(SemanticAnnotationType.EXAMPLE),),
        )
        gold = SemanticGoldCompiler().compile_document(
            document=document,
            records=(positive_logical, negative_element),
            split=DatasetSplit.DEV,
            policy=GoldEligibilityPolicy(),
        )
        annotations = (
            SemanticAnnotation(
                id="prediction-true-positive",
                target_id="lu-1",
                type=SemanticAnnotationType.EXAMPLE,
                value="EXAMPLE",
                source=StructureSource.INFERRED,
                confidence=0.9,
            ),
            SemanticAnnotation(
                id="prediction-negative-target",
                target_id="e-1",
                type=SemanticAnnotationType.DEFINITION,
                value="DEFINITION",
                source=StructureSource.INFERRED,
                confidence=0.9,
            ),
            SemanticAnnotation(
                id="prediction-unannotated-target",
                target_id="e-context",
                type=SemanticAnnotationType.DEFINITION,
                value="DEFINITION",
                source=StructureSource.INFERRED,
                confidence=0.9,
            ),
            SemanticAnnotation(
                id="prediction-unevaluated-type",
                target_id="e-1",
                type=SemanticAnnotationType.WARNING,
                value="WARNING",
                source=StructureSource.INFERRED,
                confidence=0.9,
            ),
        )
        predicted = document.model_copy(
            update={"semantic_annotations": annotations}
        )

        report = SemanticRoleEvaluator().evaluate(gold, predicted)

        self.assertEqual(report.overall.true_positive, 1)
        self.assertEqual(report.overall.false_positive, 1)
        self.assertEqual(report.overall.false_negative, 0)
        self.assertEqual(report.predicted_annotation_count, 2)
        self.assertEqual(
            {scope.target.kind for scope in gold.evaluation_scopes},
            {SemanticTargetKind.ELEMENT, SemanticTargetKind.LOGICAL_UNIT},
        )


if __name__ == "__main__":
    unittest.main()
