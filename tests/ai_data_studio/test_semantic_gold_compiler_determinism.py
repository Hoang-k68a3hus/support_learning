from __future__ import annotations

import json
import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldEligibilityPolicy,
    SemanticGoldCompiler,
)
from ai_data_studio.schemas import AnnotationSuggestion
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
)

from ._gold_compiler_fixtures import (
    adjudicated_record,
    document_variant,
    negative_decision,
    positive_decision,
    split_manifest,
)


class SemanticGoldCompilerDeterminismTests(unittest.TestCase):
    def test_input_order_and_document_mapping_order_do_not_change_output(self) -> None:
        first_document = document_variant(document_id="doc-a", content_token="c")
        second_document = document_variant(document_id="doc-b", content_token="d")
        first_record = adjudicated_record(
            document=first_document,
            record_id="record-a",
            source_family_id="family-a",
            split_group_id="group-a",
        )
        second_record = adjudicated_record(
            document=second_document,
            record_id="record-b",
            source_family_id="family-b",
            split_group_id="group-b",
            decisions=(negative_decision(SemanticAnnotationType.DEFINITION),),
        )
        manifest = split_manifest(
            ("group-a", DatasetSplit.DEV),
            ("group-b", DatasetSplit.TEST),
        )
        compiler = SemanticGoldCompiler()
        policy = GoldEligibilityPolicy()

        first = compiler.compile_dataset(
            name="semantic-gold",
            documents={
                second_document.document_id: second_document,
                first_document.document_id: first_document,
            },
            records=(second_record, first_record),
            split_manifest=manifest,
            policy=policy,
        )
        second = compiler.compile_dataset(
            name="semantic-gold",
            documents={
                first_document.document_id: first_document,
                second_document.document_id: second_document,
            },
            records=(first_record, second_record),
            split_manifest=manifest,
            policy=policy,
        )

        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(
            tuple(case.document_id for case in first.cases),
            ("doc-a", "doc-b"),
        )

    def test_compilation_is_pure_and_excludes_workflow_noise(self) -> None:
        document = document_variant(document_id="doc-a", content_token="c")
        suggestion = AnnotationSuggestion(
            agent="teacher-model",
            agent_version="secret-v1",
            annotation_type=SemanticAnnotationType.DEFINITION,
            score=0.999,
            score_method=SemanticConfidenceMethod.UNCALIBRATED,
        )
        record = adjudicated_record(
            document=document,
            record_id="record-a",
            source_family_id="family-a",
            split_group_id="group-a",
            decisions=(
                positive_decision(SemanticAnnotationType.DEFINITION),
                negative_decision(SemanticAnnotationType.EXAMPLE),
            ),
            suggestions=(suggestion,),
            metadata={"argilla_id": "external-123", "teacher": "hidden"},
        )
        before_record = record.model_dump()
        before_document = document.model_dump()

        dataset = SemanticGoldCompiler().compile_dataset(
            name="semantic-gold",
            documents={document.document_id: document},
            records=(record,),
            split_manifest=split_manifest(("group-a", DatasetSplit.DEV)),
            policy=GoldEligibilityPolicy(),
        )

        self.assertEqual(record.model_dump(), before_record)
        self.assertEqual(document.model_dump(), before_document)
        case_payload = dataset.cases[0].model_dump(mode="json")
        encoded_case = json.dumps(case_payload, ensure_ascii=False)
        for forbidden in (
            "rationale",
            "negative_reason",
            "competing_labels",
            "suggestions",
            "reviewer_id",
            "Reviewed against",
            "teacher-model",
            "secret-v1",
            "argilla_id",
            "external-123",
            "hidden",
        ):
            self.assertNotIn(forbidden, encoded_case)
        self.assertEqual(dataset.cases[0].annotations[0].metadata, {})
        self.assertEqual(
            dataset.cases[0].metadata["working_record_ids"],
            ["record-a"],
        )
        self.assertIn("split_manifest_hash", dataset.metadata)
        self.assertIn("eligibility_policy", dataset.metadata)


if __name__ == "__main__":
    unittest.main()
