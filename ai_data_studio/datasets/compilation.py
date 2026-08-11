from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from ai_data_studio.schemas import SemanticWorkingRecord, WorkingBatch
from ai_data_studio.validation import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationReport,
    ValidationSeverity,
    WorkingBatchValidator,
    WorkingRecordValidator,
    working_element_snapshot_hash,
)
from source_understanding.evaluation import SemanticGoldDataset
from source_understanding.schemas.context import ContentHash, Identifier
from source_understanding.schemas.document import CanonicalDocument

from .compiler import SemanticGoldCompiler as _ProjectionSemanticGoldCompiler
from .eligibility import GoldEligibilityPolicy, gold_eligibility_policy_hash
from .errors import GoldValidationError
from .splits import DatasetSplit, DatasetSplitManifest, dataset_split_manifest_hash


SEMANTIC_GOLD_COMPILER_VERSION = "2"
VALIDATED_WORKING_SET_HASH_VERSION = "1"


class SemanticGoldCompiler(_ProjectionSemanticGoldCompiler):
    """Fail-closed public compiler around the pure gold projection implementation."""

    version = SEMANTIC_GOLD_COMPILER_VERSION

    def __init__(self) -> None:
        super().__init__()
        self._record_validator = WorkingRecordValidator()
        self._batch_validator = WorkingBatchValidator()

    def compile_document(
        self,
        *,
        document: CanonicalDocument,
        records: Sequence[SemanticWorkingRecord],
        batches: Mapping[Identifier, WorkingBatch] | None = None,
        split: DatasetSplit,
        policy: GoldEligibilityPolicy,
    ):
        effective_batches = _resolve_batches(records=records, batches=batches)
        self._validate_working_inputs(
            documents={document.document_id: document},
            records=records,
            batches=effective_batches,
            require_complete_batches=False,
        )
        return _ProjectionSemanticGoldCompiler.compile_document(
            self,
            document=document,
            records=records,
            split=split,
            policy=policy,
        )

    def compile_dataset(
        self,
        *,
        name: str,
        documents: Mapping[Identifier, CanonicalDocument],
        records: Sequence[SemanticWorkingRecord],
        batches: Mapping[Identifier, WorkingBatch] | None = None,
        split_manifest: DatasetSplitManifest,
        policy: GoldEligibilityPolicy,
    ) -> SemanticGoldDataset:
        effective_batches = _resolve_batches(records=records, batches=batches)
        guideline_version = self._validate_working_inputs(
            documents=documents,
            records=records,
            batches=effective_batches,
            require_complete_batches=True,
        )
        compiled = _ProjectionSemanticGoldCompiler.compile_dataset(
            self,
            name=name,
            documents=documents,
            records=records,
            split_manifest=split_manifest,
            policy=policy,
        )
        metadata = dict(compiled.metadata)
        metadata.update(
            {
                "compiler_version": self.version,
                "guideline_version": guideline_version,
                "eligibility_policy_name": policy.name,
                "eligibility_policy_version": policy.version,
                "eligibility_policy_hash": gold_eligibility_policy_hash(policy),
                "validated_working_set_hash": _validated_working_set_hash(
                    documents=documents,
                    records=records,
                    batches=effective_batches,
                    split_manifest=split_manifest,
                ),
            }
        )
        return compiled.model_copy(update={"metadata": metadata})

    def _validate_working_inputs(
        self,
        *,
        documents: Mapping[Identifier, CanonicalDocument],
        records: Sequence[SemanticWorkingRecord],
        batches: Mapping[Identifier, WorkingBatch],
        require_complete_batches: bool,
    ) -> str:
        issues: list[ValidationIssue] = []
        for document_id, document in documents.items():
            if document_id != document.document_id:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.CANONICAL_DOCUMENT_MAPPING_MISMATCH,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Canonical document mapping key {document_id!r} does not "
                            f"match document_id {document.document_id!r}."
                        ),
                        path="documents",
                        related_ids=(document_id, document.document_id),
                    )
                )
        for batch_id, batch in batches.items():
            if batch_id != batch.batch_id:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.WORKING_BATCH_MAPPING_MISMATCH,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Working batch mapping key {batch_id!r} does not match "
                            f"batch_id {batch.batch_id!r}."
                        ),
                        path="batches",
                        related_ids=(batch_id, batch.batch_id),
                    )
                )

        records_by_batch: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
        for record in records:
            records_by_batch[record.batch_id].append(record)
            document = documents.get(record.source.document_id)
            if document is None:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.CANONICAL_DOCUMENT_MISSING,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"CanonicalDocument {record.source.document_id!r} is missing "
                            f"for record {record.record_id!r}."
                        ),
                        record_id=record.record_id,
                        path="documents",
                        related_ids=(record.source.document_id,),
                    )
                )
            batch = batches.get(record.batch_id)
            if batch is None:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.WORKING_BATCH_MISSING,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"WorkingBatch {record.batch_id!r} is missing for record "
                            f"{record.record_id!r}."
                        ),
                        record_id=record.record_id,
                        path="batches",
                        related_ids=(record.batch_id,),
                    )
                )
            if document is not None and batch is not None:
                issues.extend(
                    self._record_validator.validate(
                        record=record,
                        document=document,
                        batch=batch,
                    ).issues
                )

        if require_complete_batches:
            for batch_id in sorted(records_by_batch):
                batch = batches.get(batch_id)
                if batch is not None:
                    issues.extend(
                        self._batch_validator.validate(
                            batch=batch,
                            records=records_by_batch[batch_id],
                        ).issues
                    )

        referenced_guidelines = {
            batches[batch_id].guideline_version
            for batch_id in records_by_batch
            if batch_id in batches
        }
        if len(referenced_guidelines) > 1:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.DATASET_MULTIPLE_GUIDELINE_VERSIONS,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        "Gold compilation requires one guideline version per dataset; "
                        f"found {sorted(referenced_guidelines)!r}."
                    ),
                    path="batches[*].guideline_version",
                )
            )

        report = ValidationReport(issues=tuple(issues))
        if not report.is_valid:
            raise GoldValidationError(report)
        if not referenced_guidelines:
            raise GoldValidationError(
                ValidationReport(
                    issues=(
                        ValidationIssue(
                            code=ValidationIssueCode.WORKING_BATCH_MISSING,
                            severity=ValidationSeverity.ERROR,
                            message="Gold compilation requires at least one validated WorkingBatch.",
                            path="batches",
                        ),
                    )
                )
            )
        return next(iter(referenced_guidelines))


def _resolve_batches(
    *,
    records: Sequence[SemanticWorkingRecord],
    batches: Mapping[Identifier, WorkingBatch] | None,
) -> Mapping[Identifier, WorkingBatch]:
    if batches is not None:
        return batches

    grouped: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
    for record in records:
        grouped[record.batch_id].append(record)
    inferred: dict[str, WorkingBatch] = {}
    for batch_id in sorted(grouped):
        batch_records = tuple(sorted(grouped[batch_id], key=lambda item: item.record_id))
        evaluated_types = {record.evaluated_types for record in batch_records}
        review_guidelines = {
            record.reviews[-1].guideline_version
            for record in batch_records
            if record.reviews
        }
        if (
            len(evaluated_types) != 1
            or len(review_guidelines) != 1
            or any(not record.reviews for record in batch_records)
        ):
            raise GoldValidationError(
                ValidationReport(
                    issues=(
                        ValidationIssue(
                            code=ValidationIssueCode.WORKING_BATCH_MISSING,
                            severity=ValidationSeverity.ERROR,
                            message=(
                                f"Cannot infer WorkingBatch {batch_id!r} from an "
                                "ambiguous or unreviewed record set; supply the "
                                "authoritative batch mapping."
                            ),
                            path="batches",
                            related_ids=tuple(
                                record.record_id for record in batch_records
                            ),
                        ),
                    )
                )
            )
        inferred[batch_id] = WorkingBatch(
            batch_id=batch_id,
            name=f"Inferred gold batch {batch_id}",
            guideline_version=next(iter(review_guidelines)),
            created_by="compiler-inferred",
            created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
            evaluated_types=batch_records[0].evaluated_types,
            record_ids=tuple(record.record_id for record in batch_records),
        )
    return inferred


def _validated_working_set_hash(
    *,
    documents: Mapping[Identifier, CanonicalDocument],
    records: Sequence[SemanticWorkingRecord],
    batches: Mapping[Identifier, WorkingBatch],
    split_manifest: DatasetSplitManifest,
) -> ContentHash:
    referenced_document_ids = {record.source.document_id for record in records}
    referenced_batch_ids = {record.batch_id for record in records}
    payload = {
        "hash_version": VALIDATED_WORKING_SET_HASH_VERSION,
        "split_manifest_hash": dataset_split_manifest_hash(split_manifest),
        "documents": [
            {
                "document_id": document_id,
                "content_hash": documents[document_id].content_hash,
                "element_snapshot_hash": working_element_snapshot_hash(
                    documents[document_id]
                ),
            }
            for document_id in sorted(referenced_document_ids)
        ],
        "batches": [
            {
                "batch_id": batch_id,
                "guideline_version": batches[batch_id].guideline_version,
                "evaluated_types": [
                    item.value for item in batches[batch_id].evaluated_types
                ],
                "record_ids": list(batches[batch_id].record_ids),
            }
            for batch_id in sorted(referenced_batch_ids)
        ],
        "records": [
            {
                "record_id": record.record_id,
                "batch_id": record.batch_id,
                "document_id": record.source.document_id,
                "content_hash": record.source.content_hash,
                "element_snapshot_hash": record.source.element_snapshot_hash,
                "target_kind": record.target.target_kind.value,
                "target_id": record.target.target_id,
                "element_ids": list(record.target.element_ids),
                "element_orders": list(record.target.element_orders),
                "evaluated_types": [item.value for item in record.evaluated_types],
                "status": record.status.value,
                "decision_hash": record.decision_hash,
                "final_review": (
                    {
                        "guideline_version": record.reviews[-1].guideline_version,
                        "outcome": record.reviews[-1].outcome.value,
                        "decision_hash_after": record.reviews[-1].decision_hash_after,
                    }
                    if record.reviews
                    else None
                ),
            }
            for record in sorted(records, key=lambda item: item.record_id)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
