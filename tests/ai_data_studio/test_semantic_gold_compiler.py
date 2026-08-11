from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldDuplicateTargetError,
    GoldEligibilityError,
    GoldEligibilityPolicy,
    GoldSplitResolutionError,
    GoldValidationError,
    SemanticGoldCompiler,
)
from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    WorkingRecordStatus,
)
from ai_data_studio.validation import ValidationIssueCode
from source_understanding.evaluation import (
    BenchmarkSplit,
    semantic_gold_dataset_hash,
)
from source_understanding.schemas.document import SemanticAnnotationType
from source_understanding.semantics import (
    SemanticOntologyLabel,
    SemanticTargetKind,
)

from ._gold_compiler_fixtures import (
    adjudicated_record,
    document_variant,
    negative_decision,
    not_applicable_decision,
    positive_decision,
    split_manifest,
)
from ._validation_fixtures import canonical_document


class SemanticGoldCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = SemanticGoldCompiler()
        self.policy = GoldEligibilityPolicy()

    def test_positive_negative_and_not_applicable_mapping(self) -> None:
        document = canonical_document()
        record = adjudicated_record(
            document=document,
            decisions=(
                positive_decision(SemanticAnnotationType.DEFINITION),
                negative_decision(SemanticAnnotationType.EXAMPLE),
                not_applicable_decision(SemanticAnnotationType.WARNING),
            ),
        )

        gold = self.compiler.compile_document(
            document=document,
            records=(record,),
            split=DatasetSplit.DEV,
            policy=self.policy,
        )

        self.assertEqual(gold.split, BenchmarkSplit.DEV)
        self.assertEqual(
            gold.evaluation_scopes[0].evaluated_types,
            (
                SemanticAnnotationType.DEFINITION,
                SemanticAnnotationType.EXAMPLE,
                SemanticAnnotationType.WARNING,
            ),
        )
        self.assertEqual(
            tuple(annotation.type for annotation in gold.annotations),
            (SemanticAnnotationType.DEFINITION,),
        )
        self.assertEqual(gold.annotations[0].metadata, {})

    def test_all_negative_document_keeps_scope_without_annotations(self) -> None:
        document = canonical_document()
        record = adjudicated_record(
            document=document,
            decisions=(negative_decision(SemanticAnnotationType.DEFINITION),),
        )

        gold = self.compiler.compile_document(
            document=document,
            records=(record,),
            split=DatasetSplit.TEST,
            policy=self.policy,
        )

        self.assertEqual(gold.annotations, ())
        self.assertEqual(len(gold.evaluation_scopes), 1)

    def test_stale_target_snapshot_fails_closed_before_gold_projection(self) -> None:
        document = canonical_document()
        record = adjudicated_record(document=document)
        altered_target = record.target.model_copy(
            update={
                "raw_text": "workflow snapshot noise",
                "normalized_text": "workflow snapshot noise",
            }
        )
        stale = record.model_copy(update={"target": altered_target})

        with self.assertRaises(GoldValidationError) as caught:
            self.compiler.compile_document(
                document=document,
                records=(stale,),
                split=DatasetSplit.DEV,
                policy=self.policy,
            )

        codes = {issue.code for issue in caught.exception.report.errors}
        self.assertIn(ValidationIssueCode.TARGET_RAW_TEXT_MISMATCH, codes)
        self.assertIn(ValidationIssueCode.TARGET_NORMALIZED_TEXT_MISMATCH, codes)

    def test_ineligible_record_fails_instead_of_being_silently_skipped(self) -> None:
        document = canonical_document()
        record = adjudicated_record(
            document=document,
            status=WorkingRecordStatus.REVIEW_REQUIRED,
        )

        with self.assertRaises(GoldEligibilityError) as caught:
            self.compiler.compile_document(
                document=document,
                records=(record,),
                split=DatasetSplit.DEV,
                policy=self.policy,
            )

        self.assertEqual(caught.exception.record_reasons[0][0], record.record_id)

    def test_stale_review_hash_is_rejected_before_unsupported_decision_projection(self) -> None:
        document = canonical_document()
        valid = adjudicated_record(document=document)
        undecided = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.UNDECIDED,
            rationale="The adjudication is unresolved.",
            confidence=AdjudicationConfidence.LOW,
        )
        invalid_snapshot = valid.model_copy(update={"decisions": (undecided,)})

        with self.assertRaises(GoldValidationError) as caught:
            self.compiler.compile_document(
                document=document,
                records=(invalid_snapshot,),
                split=DatasetSplit.DEV,
                policy=self.policy,
            )

        self.assertIn(
            ValidationIssueCode.REVIEW_FINAL_HASH_MISMATCH,
            {issue.code for issue in caught.exception.report.errors},
        )

    def test_custom_positive_preserves_ontology_exactly(self) -> None:
        document = canonical_document()
        ontology = SemanticOntologyLabel(
            namespace="education",
            label="LEMMA",
            version="ontology-v1",
        )
        record = adjudicated_record(
            document=document,
            decisions=(
                positive_decision(
                    SemanticAnnotationType.CUSTOM,
                    ontology=ontology,
                ),
            ),
        )

        gold = self.compiler.compile_document(
            document=document,
            records=(record,),
            split=DatasetSplit.DEV,
            policy=self.policy,
        )

        self.assertEqual(gold.annotations[0].ontology, ontology)

    def test_duplicate_physical_target_is_rejected_defensively(self) -> None:
        document = canonical_document()
        first = adjudicated_record(document=document, record_id="record-a")
        second = adjudicated_record(document=document, record_id="record-b")

        with self.assertRaises(GoldDuplicateTargetError):
            self.compiler.compile_document(
                document=document,
                records=(first, second),
                split=DatasetSplit.DEV,
                policy=self.policy,
            )

    def test_source_revision_snapshot_and_document_mismatches_fail_validation(self) -> None:
        document = canonical_document()
        valid = adjudicated_record(document=document)
        cases = {
            "document": valid.model_copy(
                update={
                    "source": valid.source.model_copy(
                        update={"document_id": "different-document"}
                    )
                }
            ),
            "content": valid.model_copy(
                update={
                    "source": valid.source.model_copy(
                        update={"content_hash": "sha256:" + "c" * 64}
                    )
                }
            ),
            "snapshot": valid.model_copy(
                update={
                    "source": valid.source.model_copy(
                        update={"element_snapshot_hash": "sha256:" + "d" * 64}
                    )
                }
            ),
        }

        for name, record in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(GoldValidationError):
                    self.compiler.compile_document(
                        document=document,
                        records=(record,),
                        split=DatasetSplit.DEV,
                        policy=self.policy,
                    )

    def test_dataset_requires_documents_and_valid_split_resolution(self) -> None:
        document = canonical_document()
        record = adjudicated_record(document=document)
        manifest = split_manifest(("group-1", DatasetSplit.TRAIN))

        with self.assertRaises(GoldValidationError):
            self.compiler.compile_dataset(
                name="semantic-gold",
                documents={},
                records=(record,),
                split_manifest=manifest,
                policy=self.policy,
            )

        with self.assertRaises(GoldSplitResolutionError):
            self.compiler.compile_dataset(
                name="semantic-gold",
                documents={document.document_id: document},
                records=(record,),
                split_manifest=split_manifest(
                    ("other-group", DatasetSplit.TRAIN)
                ),
                policy=self.policy,
            )

    def test_dataset_preserves_train_split_and_records_provenance_hashes(self) -> None:
        document = document_variant(document_id="doc-train", content_token="c")
        record = adjudicated_record(
            document=document,
            split_group_id="train-group",
        )

        dataset = self.compiler.compile_dataset(
            name="semantic-gold",
            documents={document.document_id: document},
            records=(record,),
            split_manifest=split_manifest(
                ("train-group", DatasetSplit.TRAIN)
            ),
            policy=self.policy,
        )

        self.assertEqual(dataset.cases[0].split, BenchmarkSplit.TRAIN)
        self.assertTrue(
            semantic_gold_dataset_hash(
                dataset,
                split=BenchmarkSplit.TRAIN,
            ).startswith("sha256:")
        )
        self.assertEqual(dataset.metadata["guideline_version"], "roles-v1")
        self.assertEqual(
            dataset.metadata["eligibility_policy_name"], self.policy.name
        )
        self.assertTrue(dataset.metadata["eligibility_policy_hash"].startswith("sha256:"))
        self.assertTrue(dataset.metadata["validated_working_set_hash"].startswith("sha256:"))

    def test_dataset_reports_all_ineligible_record_ids(self) -> None:
        document = canonical_document()
        first = adjudicated_record(
            document=document,
            record_id="record-a",
            target_id="e-1",
            target_kind=SemanticTargetKind.ELEMENT,
            status=WorkingRecordStatus.REVIEW_REQUIRED,
        )
        second = adjudicated_record(
            document=document,
            record_id="record-b",
            target_id="e-2",
            target_kind=SemanticTargetKind.ELEMENT,
            status=WorkingRecordStatus.REJECT,
        )

        with self.assertRaises(GoldEligibilityError) as caught:
            self.compiler.compile_dataset(
                name="semantic-gold",
                documents={document.document_id: document},
                records=(second, first),
                split_manifest=split_manifest(
                    ("group-1", DatasetSplit.DEV)
                ),
                policy=self.policy,
            )

        self.assertEqual(
            tuple(record_id for record_id, _ in caught.exception.record_reasons),
            ("record-a", "record-b"),
        )


if __name__ == "__main__":
    unittest.main()
