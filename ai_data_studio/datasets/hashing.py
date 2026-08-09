from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from pydantic import BaseModel, TypeAdapter

from source_understanding.evaluation import SemanticGoldDataset
from source_understanding.evaluation.semantic import (
    GoldSemanticAnnotation,
    GoldSemanticDocument,
    GoldSemanticEvidenceSpan,
    GoldSemanticEvaluationScope,
)
from source_understanding.schemas.context import ContentHash
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticTextView,
)

from .splits import DatasetSplit


GOLD_DATASET_HASH_VERSION = "1"
FROZEN_MANIFEST_HASH_VERSION = "1"
SOURCE_CORPUS_HASH_VERSION = "1"


def semantic_gold_split_hash(
    dataset: SemanticGoldDataset,
    *,
    split: DatasetSplit,
) -> ContentHash:
    """Hash one split's semantic truth, excluding identity and metadata noise."""

    selected_cases = tuple(
        sorted(
            (
                case
                for case in dataset.cases
                if case.split.value == split.value
            ),
            key=lambda case: case.document_id,
        )
    )
    if not selected_cases:
        raise ValueError(
            f"semantic gold dataset has no cases for split {split.value!r}"
        )
    payload = {
        "hash_version": GOLD_DATASET_HASH_VERSION,
        "gold_schema_version": dataset.schema_version,
        "benchmark_version": dataset.benchmark_version,
        "split": split.value,
        "cases": [_semantic_case_payload(case) for case in selected_cases],
    }
    return _content_hash(payload)


def semantic_gold_dataset_hash(dataset: SemanticGoldDataset) -> ContentHash:
    """Hash semantic content and split assignment, independent of release identity."""

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


def _semantic_case_payload(case: GoldSemanticDocument) -> dict[str, object]:
    return {
        "schema_version": case.schema_version,
        "benchmark_version": case.benchmark_version,
        "document_id": case.document_id,
        "content_hash": case.content_hash,
        "element_snapshot_hash": case.element_snapshot_hash,
        "split": case.split.value,
        "language": case.language,
        "elements": [
            element.model_dump(mode="json")
            for element in sorted(case.elements, key=lambda item: item.order)
        ],
        "evaluation_scopes": [
            _scope_payload(scope)
            for scope in sorted(case.evaluation_scopes, key=_scope_sort_key)
        ],
        "annotations": [
            _annotation_payload(annotation)
            for annotation in sorted(case.annotations, key=_annotation_sort_key)
        ],
    }


def _scope_payload(scope: GoldSemanticEvaluationScope) -> dict[str, object]:
    return {
        "target": scope.target.model_dump(mode="json"),
        "evaluated_types": [
            annotation_type.value
            for annotation_type in sorted(
                scope.evaluated_types,
                key=lambda item: _ANNOTATION_TYPE_RANK[item],
            )
        ],
    }


def _annotation_payload(annotation: GoldSemanticAnnotation) -> dict[str, object]:
    return {
        "target": annotation.target.model_dump(mode="json"),
        "type": annotation.type.value,
        "value": annotation.value,
        "ontology": (
            annotation.ontology.model_dump(mode="json")
            if annotation.ontology is not None
            else None
        ),
        "evidence": [
            span.model_dump(mode="json")
            for span in sorted(annotation.evidence, key=_evidence_sort_key)
        ],
    }


def _scope_sort_key(
    scope: GoldSemanticEvaluationScope,
) -> tuple[object, ...]:
    return scope.target.kind.value, scope.target.element_orders


def _annotation_sort_key(
    annotation: GoldSemanticAnnotation,
) -> tuple[object, ...]:
    ontology_key = (
        annotation.ontology.key,
        annotation.ontology.version or "",
    ) if annotation.ontology is not None else ("", "")
    return (
        annotation.target.kind.value,
        annotation.target.element_orders,
        _ANNOTATION_TYPE_RANK[annotation.type],
        annotation.value or "",
        ontology_key,
        tuple(_evidence_sort_key(span) for span in annotation.evidence),
    )


def _evidence_sort_key(
    span: GoldSemanticEvidenceSpan,
) -> tuple[object, ...]:
    return (
        span.element_order,
        _TEXT_VIEW_RANK[span.text_view],
        span.start_char,
        span.end_char,
        span.quoted_text,
    )


_CONTENT_HASH_ADAPTER = TypeAdapter(ContentHash)
_ANNOTATION_TYPE_RANK = {
    annotation_type: index
    for index, annotation_type in enumerate(SemanticAnnotationType)
}
_TEXT_VIEW_RANK = {
    text_view: index for index, text_view in enumerate(SemanticTextView)
}
