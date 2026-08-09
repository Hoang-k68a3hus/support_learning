from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from pydantic import BaseModel, TypeAdapter

from source_understanding.evaluation import (
    BenchmarkSplit,
    SemanticGoldDataset,
    semantic_gold_dataset_hash as evaluation_semantic_gold_split_hash,
)
from source_understanding.schemas.context import ContentHash

from .splits import DatasetSplit


GOLD_DATASET_HASH_VERSION = "2"
FROZEN_MANIFEST_HASH_VERSION = "1"
SOURCE_CORPUS_HASH_VERSION = "1"


def semantic_gold_split_hash(
    dataset: SemanticGoldDataset,
    *,
    split: DatasetSplit,
) -> ContentHash:
    """Return the canonical evaluator hash for one semantic-gold split.

    The evaluation report and the frozen release must identify the same TEST
    payload with the same hash.  Keep the canonical split-content definition in
    ``source_understanding.evaluation`` and delegate to it here instead of
    maintaining a second, subtly different payload contract.
    """

    return evaluation_semantic_gold_split_hash(
        dataset,
        split=BenchmarkSplit(split.value),
    )


def semantic_gold_dataset_hash(dataset: SemanticGoldDataset) -> ContentHash:
    """Hash the complete dataset from its canonical per-split hashes."""

    present_splits = {
        DatasetSplit(case.split.value) for case in dataset.cases
    }
    split_hashes = {
        split: semantic_gold_split_hash(dataset, split=split)
        for split in DatasetSplit
        if split in present_splits
    }
    return dataset_hash_from_splits(split_hashes)


def dataset_hash_from_splits(
    hashes: Mapping[DatasetSplit, ContentHash],
) -> ContentHash:
    if not hashes:
        raise ValueError("dataset hash requires at least one split hash")
    validated = {
        DatasetSplit(split): _CONTENT_HASH_ADAPTER.validate_python(content_hash)
        for split, content_hash in hashes.items()
    }
    payload = {
        "hash_version": GOLD_DATASET_HASH_VERSION,
        "splits": [
            {
                "split": split.value,
                "hash": validated[split],
            }
            for split in DatasetSplit
            if split in validated
        ],
    }
    return _content_hash(payload)


def source_corpus_hash(dataset: SemanticGoldDataset) -> ContentHash:
    payload = {
        "hash_version": SOURCE_CORPUS_HASH_VERSION,
        "documents": [
            {
                "document_id": case.document_id,
                "content_hash": case.content_hash,
                "element_snapshot_hash": case.element_snapshot_hash,
            }
            for case in sorted(dataset.cases, key=lambda item: item.document_id)
        ],
    }
    return _content_hash(payload)


def frozen_manifest_hash(manifest: BaseModel | Mapping[str, object]) -> ContentHash:
    """Hash stable manifest inputs; ``created_at`` is audit-only."""

    if isinstance(manifest, BaseModel):
        manifest_payload = manifest.model_dump(mode="json", exclude_none=False)
    else:
        manifest_payload = dict(manifest)
    manifest_payload.pop("created_at", None)
    manifest_payload.pop("manifest_hash", None)
    return _content_hash(
        {
            "hash_version": FROZEN_MANIFEST_HASH_VERSION,
            "manifest": manifest_payload,
        }
    )


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_hash(payload: object) -> ContentHash:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


_CONTENT_HASH_ADAPTER = TypeAdapter(ContentHash)
