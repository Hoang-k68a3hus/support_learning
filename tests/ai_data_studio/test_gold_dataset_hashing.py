from __future__ import annotations

import unittest

from ai_data_studio.datasets import (
    DatasetSplit,
    GoldEligibilityPolicy,
    SemanticGoldCompiler,
    semantic_gold_dataset_hash,
    semantic_gold_split_hash,
    source_corpus_hash,
)
from source_understanding.evaluation import (
    BenchmarkSplit,
    SemanticGoldDataset,
    semantic_gold_dataset_hash as evaluation_semantic_gold_split_hash,
)
from source_understanding.schemas.document import (
    CanonicalDocument,
    SemanticAnnotationType,
    SemanticEvidenceSpan,
    SemanticTextView,
)

from ._freeze_fixtures import compiled_gold_dataset
from ._gold_compiler_fixtures import (
    adjudicated_record,
    document_variant,
    negative_decision,
    positive_decision,
    split_manifest,
)


class SemanticGoldDatasetHashingTests(unittest.TestCase):
    def test_same_semantic_content_has_same_order_independent_hash(self) -> None:
        dataset, _ = compiled_gold_dataset()
        payload = dataset.model_dump(mode="json")
        payload["cases"] = list(reversed(payload["cases"]))
        reversed_dataset = SemanticGoldDataset.model_validate(payload)

        self.assertEqual(
            semantic_gold_dataset_hash(dataset),
            semantic_gold_dataset_hash(reversed_dataset),
        )
        self.assertEqual(
            source_corpus_hash(dataset),
            source_corpus_hash(reversed_dataset),
        )

    def test_dataset_metadata_does_not_change_split_hash(self) -> None:
        dataset, _ = compiled_gold_dataset()
        payload = dataset.model_dump(mode="json")
        payload["metadata"] = {"exported_at": "2030-01-01T00:00:00Z"}
        noisy_dataset = SemanticGoldDataset.model_validate(payload)

        self.assertEqual(
            semantic_gold_dataset_hash(dataset),
            semantic_gold_dataset_hash(noisy_dataset),
        )

    def test_frozen_split_hash_matches_evaluator_dataset_hash(self) -> None:
        dataset, _ = compiled_gold_dataset()
        for split in DatasetSplit:
            with self.subTest(split=split.value):
                self.assertEqual(
                    semantic_gold_split_hash(dataset, split=split),
                    evaluation_semantic_gold_split_hash(
                        dataset,
                        split=BenchmarkSplit(split.value),
                    ),
                )

    def test_annotation_and_scope_changes_change_hash(self) -> None:
        document = document_variant(document_id="doc-hash", content_token="f")
        manifest = split_manifest(("group-hash", DatasetSplit.DEV))
        positive = adjudicated_record(
            document=document,
            record_id="record-hash",
            split_group_id="group-hash",
        )
        negative = adjudicated_record(
            document=document,
            record_id="record-hash",
            split_group_id="group-hash",
            decisions=(
                negative_decision(SemanticAnnotationType.DEFINITION),
            ),
        )
        wider_scope = adjudicated_record(
            document=document,
            record_id="record-hash",
            split_group_id="group-hash",
            decisions=(
                positive_decision(),
                negative_decision(SemanticAnnotationType.EXAMPLE),
            ),
        )
        compiler = SemanticGoldCompiler()
        datasets = tuple(
            compiler.compile_dataset(
                name="semantic-role",
                documents={document.document_id: document},
                records=(record,),
                split_manifest=manifest,
                policy=GoldEligibilityPolicy(),
            )
            for record in (positive, negative, wider_scope)
        )

        hashes = {semantic_gold_dataset_hash(dataset) for dataset in datasets}
        self.assertEqual(len(hashes), 3)

    def test_evidence_change_changes_hash(self) -> None:
        document = self._repeated_term_document()
        first = self._compile_extractive(document, start_char=0, end_char=4)
        second = self._compile_extractive(document, start_char=5, end_char=9)

        self.assertNotEqual(
            semantic_gold_dataset_hash(first),
            semantic_gold_dataset_hash(second),
        )

    def test_split_change_changes_hash(self) -> None:
        document = document_variant(document_id="doc-split-hash", content_token="9")
        record = adjudicated_record(
            document=document,
            record_id="record-split-hash",
            split_group_id="group-split-hash",
        )
        compiler = SemanticGoldCompiler()
        datasets = []
        for split in (DatasetSplit.DEV, DatasetSplit.TEST):
            datasets.append(
                compiler.compile_dataset(
                    name="semantic-role",
                    documents={document.document_id: document},
                    records=(record,),
                    split_manifest=split_manifest(
                        ("group-split-hash", split)
                    ),
                    policy=GoldEligibilityPolicy(),
                )
            )

        self.assertNotEqual(
            semantic_gold_dataset_hash(datasets[0]),
            semantic_gold_dataset_hash(datasets[1]),
        )

    def test_dataset_hash_aggregates_present_split_hashes(self) -> None:
        dataset, _ = compiled_gold_dataset()
        hashes = {
            semantic_gold_split_hash(dataset, split=split)
            for split in DatasetSplit
        }

        self.assertEqual(len(hashes), 3)
        self.assertNotIn(semantic_gold_dataset_hash(dataset), hashes)

    @staticmethod
    def _repeated_term_document() -> CanonicalDocument:
        document = document_variant(
            document_id="doc-evidence-hash",
            content_token="8",
        )
        elements = list(document.elements)
        elements[0] = elements[0].model_copy(
            update={
                "raw_text": "term term",
                "normalized_text": "term term",
            }
        )
        payload = document.model_dump(mode="python")
        payload["elements"] = tuple(elements)
        return CanonicalDocument.model_validate(payload)

    @staticmethod
    def _compile_extractive(
        document: CanonicalDocument,
        *,
        start_char: int,
        end_char: int,
    ) -> SemanticGoldDataset:
        record = adjudicated_record(
            document=document,
            record_id="record-evidence-hash",
            split_group_id="group-evidence-hash",
            decisions=(
                positive_decision(
                    SemanticAnnotationType.CONCEPT,
                    value="term",
                    evidence=(
                        SemanticEvidenceSpan(
                            element_id="e-1",
                            start_char=start_char,
                            end_char=end_char,
                            quoted_text="term",
                            text_view=SemanticTextView.RAW_TEXT,
                        ),
                    ),
                ),
            ),
        )
        manifest = split_manifest(
            ("group-evidence-hash", DatasetSplit.TEST)
        )
        return SemanticGoldCompiler().compile_dataset(
            name="semantic-role",
            documents={document.document_id: document},
            records=(record,),
            split_manifest=manifest,
            policy=GoldEligibilityPolicy(),
        )


if __name__ == "__main__":
    unittest.main()
