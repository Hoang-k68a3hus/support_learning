from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldDuplicateTargetError,
    GoldEligibilityError,
    GoldEligibilityPolicy,
    GoldSourceResolutionError,
    GoldSplitResolutionError,
    GoldUnsupportedDecisionError,
    SemanticGoldCompiler,
)
from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecision,
    AnnotationDecisionState,
    WorkingRecordStatus,
)
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

    def test_canonical_document_is_the_only_gold_text_source(self) -> None:
        document = canonical_document()
        record = adjudicated_record(document=document)
        altered_target = record.target.model_copy(
            update={
                "raw_text": "workflow snapshot noise",
                "normalized_text": "workflow snapshot noise",
            }
        )
        record = record.model_copy(update={"target": altered_target})

        gold = self.compiler.compile_document(
            document=document,
            records=(record,),
            split=DatasetSplit.DEV,
            policy=self.policy,
        )

        self.assertEqual(gold.elements[0].raw_text, document.elements[0].raw_text)
        self.assertNotEqual(gold.elements[0].raw_text, record.target.raw_text)

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

    def test_undecided_decision_cannot_compile_even_in_a_pass_snapshot(self) -> None:
        document = canonical_document()
        valid = adjudicated_record(document=document)
        undecided = AnnotationDecision(
            annotation_type=SemanticAnnotationType.DEFINITION,
            state=AnnotationDecisionState.UNDECIDED,
            rationale="The adjudication is unresolved.",
            confidence=AdjudicationConfidence.LOW,
        )
        invalid_snapshot = valid.model_copy(
            update={"decisions": (undecided,)}
        )

        with self.assertRaises(GoldUnsupportedDecisionError) as caught:
            self.compiler.compile_document(
                document=document,
                records=(invalid_snapshot,),
                split=DatasetSplit.DEV,
                policy=self.policy,
            )

        self.assertIn("UNDECIDED", str(caught.exception))

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

    def test_source_revision_snapshot_and_document_mismatches_fail(self) -> None:
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
                with self.assertRaises(GoldSourceResolutionError):
                    self.compiler.compile_document(
                        document=document,
                        records=(record,),
                        split=DatasetSplit.DEV,
                        policy=self.policy,
                    )

    def test_multiple_working_revisions_for_one_document_fail(self) -> None:
        document = canonical_document()
        first = adjudicated_record(document=document, record_id="record-a")
        second = adjudicated_record(document=document, record_id="record-b")
        second = second.model_copy(
            update={
                "source": second.source.model_copy(
                    update={"content_hash": "sha256:" + "c" * 64}
                )
            }
        )

        with self.assertRaisesRegex(
            GoldSourceResolutionError,
            "multiple source revisions",
        ):
            self.compiler.compile_document(
                document=document,
                records=(first, second),
                split=DatasetSplit.DEV,
                policy=self.policy,
            )

    def test_dataset_requires_documents_and_valid_split_resolution(self) -> None:
        document = canonical_document()
        record = adjudicated_record(document=document)
        manifest = split_manifest(("group-1", DatasetSplit.TRAIN))

        with self.assertRaises(GoldSourceResolutionError):
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

    def test_dataset_preserves_train_split_from_manifest(self) -> None:
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
