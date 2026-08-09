from __future__ import annotations

from collections.abc import Sequence

from ai_data_studio.datasets import (
    SEMANTIC_GOLD_COMPILER_VERSION,
    DatasetSplit,
    DatasetSplitManifest,
    FreezePolicy,
    FreezeProvenance,
    GoldEligibilityPolicy,
    SemanticGoldCompiler,
)
from ai_data_studio.schemas import WORKING_RECORD_SCHEMA_VERSION
from source_understanding.evaluation import SemanticGoldDataset

from ._gold_compiler_fixtures import (
    adjudicated_record,
    document_variant,
    negative_decision,
    split_manifest,
)
from source_understanding.schemas.document import SemanticAnnotationType


def compiled_gold_dataset(
    splits: Sequence[DatasetSplit] = (
        DatasetSplit.TRAIN,
        DatasetSplit.DEV,
        DatasetSplit.TEST,
    ),
    *,
    name: str = "semantic-role",
    all_negative: bool = False,
) -> tuple[SemanticGoldDataset, DatasetSplitManifest]:
    documents = {}
    records = []
    assignments = []
    for index, split in enumerate(splits, start=1):
        token = chr(ord("a") + index)
        document_id = f"doc-{split.value}-{index}"
        document = document_variant(
            document_id=document_id,
            content_token=token,
        )
        group_id = f"group-{split.value}-{index}"
        documents[document.document_id] = document
        records.append(
            adjudicated_record(
                document=document,
                record_id=f"record-{split.value}-{index}",
                batch_id=f"batch-{split.value}-{index}",
                source_family_id=f"family-{split.value}-{index}",
                split_group_id=group_id,
                decisions=(
                    negative_decision(SemanticAnnotationType.DEFINITION),
                )
                if all_negative
                else None,
            )
        )
        assignments.append((group_id, split))
    manifest = split_manifest(*assignments)
    dataset = SemanticGoldCompiler().compile_dataset(
        name=name,
        documents=documents,
        records=tuple(records),
        split_manifest=manifest,
        policy=GoldEligibilityPolicy(),
    )
    return dataset, manifest


def freeze_provenance() -> FreezeProvenance:
    return FreezeProvenance(
        compiler_version=SEMANTIC_GOLD_COMPILER_VERSION,
        guideline_version="roles-v1",
        working_record_schema_version=WORKING_RECORD_SCHEMA_VERSION,
        eligibility_policy_name="semantic-gold-strict",
        eligibility_policy_version="1",
        producer_revision="test-suite",
    )


def freeze_policy(
    *splits: DatasetSplit,
) -> FreezePolicy:
    selected = splits or (
        DatasetSplit.TRAIN,
        DatasetSplit.DEV,
        DatasetSplit.TEST,
    )
    return FreezePolicy(required_splits=selected)
