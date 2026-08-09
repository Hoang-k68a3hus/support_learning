from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldEligibilityError,
    GoldEligibilityPolicy,
    GoldSourceResolutionError,
    SemanticGoldCompiler,
    semantic_gold_split_hash,
)
from source_understanding.evaluation import SemanticGoldDataset
from source_understanding.schemas.document import SemanticAnnotationType
from source_understanding.semantics import SemanticTargetKind

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

    def test_source_family_and_split_group_are_bound_into_gold_identity(self) -> None:
        document = canonical_document()
        record = adjudicated_record(
            document=document,
            source_family_id="family-lineage",
            split_group_id="group-lineage",
        )
        gold = SemanticGoldCompiler().compile_document(
            document=document,
            records=(record,),
            split=DatasetSplit.TEST,
            policy=GoldEligibilityPolicy(),
        )

        self.assertEqual(gold.metadata["source_family_id"], "family-lineage")
        self.assertEqual(gold.metadata["split_group_id"], "group-lineage")

        dataset = SemanticGoldDataset(name="lineage", cases=(gold,))
        original_hash = semantic_gold_split_hash(dataset, split=DatasetSplit.TEST)
        payload = dataset.model_dump(mode="python")
        changed_case = payload["cases"][0]
        changed_metadata = dict(changed_case["metadata"])
        changed_metadata["split_group_id"] = "tampered-group"
        changed_case["metadata"] = changed_metadata
        changed = SemanticGoldDataset.model_validate(payload)

        self.assertNotEqual(
            original_hash,
            semantic_gold_split_hash(changed, split=DatasetSplit.TEST),
        )

    def test_one_document_cannot_compile_from_multiple_source_families(self) -> None:
        document = canonical_document()
        first = adjudicated_record(
            document=document,
            record_id="record-a",
            source_family_id="family-a",
        )
        second = adjudicated_record(
            document=document,
            record_id="record-b",
            source_family_id="family-b",
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
        )

        with self.assertRaisesRegex(
            GoldSourceResolutionError,
            "multiple source families",
        ):
            SemanticGoldCompiler().compile_document(
                document=document,
                records=(first, second),
                split=DatasetSplit.TEST,
                policy=GoldEligibilityPolicy(),
            )


if __name__ == "__main__":
    unittest.main()
