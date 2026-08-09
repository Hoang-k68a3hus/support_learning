from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldEligibilityError,
    GoldEligibilityPolicy,
    GoldSourceResolutionError,
    SemanticGoldCompiler,
)
from source_understanding.schemas.document import SemanticAnnotationType

from ._gold_compiler_fixtures import (
    adjudicated_record,
    negative_decision,
)
from ._validation_fixtures import canonical_document


class SemanticGoldCompilerHardeningTests(unittest.TestCase):
    def test_stale_logical_unit_membership_cannot_be_frozen_as_gold(self) -> None:
        document = canonical_document()
        record = adjudicated_record(document=document)
        stale_target = record.target.model_copy(
            update={
                "element_ids": ("e-1",),
                "element_orders": (0,),
            }
        )
        stale_record = record.model_copy(update={"target": stale_target})

        with self.assertRaisesRegex(
            GoldSourceResolutionError,
            "target element_ids",
        ):
            SemanticGoldCompiler().compile_document(
                document=document,
                records=(stale_record,),
                split=DatasetSplit.TEST,
                policy=GoldEligibilityPolicy(),
            )

    def test_decisions_changed_after_review_cannot_compile(self) -> None:
        document = canonical_document()
        record = adjudicated_record(document=document)
        changed = record.model_copy(
            update={
                "decisions": (
                    negative_decision(SemanticAnnotationType.DEFINITION),
                )
            }
        )

        with self.assertRaises(GoldEligibilityError) as caught:
            SemanticGoldCompiler().compile_document(
                document=document,
                records=(changed,),
                split=DatasetSplit.TEST,
                policy=GoldEligibilityPolicy(),
            )

        self.assertIn(
            "REVIEW_FINAL_HASH_MISMATCH",
            caught.exception.record_reasons[0][1],
        )


if __name__ == "__main__":
    unittest.main()
