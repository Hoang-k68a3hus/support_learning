from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ai_data_studio.schemas.batch import WorkingBatch
from ai_data_studio.schemas.working import SemanticWorkingRecord

from .issues import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationReport,
    ValidationSeverity,
)


def validate_record_batch_membership(
    *,
    record: SemanticWorkingRecord,
    batch: WorkingBatch,
    path_prefix: str = "",
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if record.batch_id != batch.batch_id:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.BATCH_ID_MISMATCH,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Record batch_id {record.batch_id!r} does not match batch "
                    f"{batch.batch_id!r}."
                ),
                record_id=record.record_id,
                path=f"{path_prefix}batch_id",
                related_ids=(batch.batch_id,),
            )
        )
    if record.record_id not in batch.record_ids:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.BATCH_RECORD_NOT_DECLARED,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Record {record.record_id!r} is not declared by batch "
                    f"{batch.batch_id!r}."
                ),
                record_id=record.record_id,
                path=f"{path_prefix}record_id",
                related_ids=(batch.batch_id,),
            )
        )
    if record.evaluated_types != batch.evaluated_types:
        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.BATCH_EVALUATED_TYPES_MISMATCH,
                severity=ValidationSeverity.ERROR,
                message=(
                    "Record evaluated_types do not exactly match the batch "
                    "evaluated_types."
                ),
                record_id=record.record_id,
                path=f"{path_prefix}evaluated_types",
                related_ids=(batch.batch_id,),
            )
        )
    return tuple(issues)


class WorkingBatchValidator:
    def validate(
        self,
        *,
        batch: WorkingBatch,
        records: Sequence[SemanticWorkingRecord],
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        actual_ids = tuple(record.record_id for record in records)
        duplicate_ids = tuple(
            sorted(
                record_id
                for record_id, count in Counter(actual_ids).items()
                if count > 1
            )
        )
        for record_id in duplicate_ids:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.BATCH_DUPLICATE_RECORD,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Record {record_id!r} occurs more than once in the "
                        "batch validation input."
                    ),
                    record_id=record_id,
                    path="records",
                    related_ids=(batch.batch_id,),
                )
            )

        expected = set(batch.record_ids)
        actual = set(actual_ids)
        for record_id in sorted(expected - actual):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.BATCH_RECORD_MISSING,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Batch-declared record {record_id!r} is missing from "
                        "the validation input."
                    ),
                    record_id=record_id,
                    path="records",
                    related_ids=(batch.batch_id,),
                )
            )
        for record_id in sorted(actual - expected):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.BATCH_UNEXPECTED_RECORD,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Record {record_id!r} is not declared by batch "
                        f"{batch.batch_id!r}."
                    ),
                    record_id=record_id,
                    path="records",
                    related_ids=(batch.batch_id,),
                )
            )
        for index, record in enumerate(records):
            issues.extend(
                validate_record_batch_membership(
                    record=record,
                    batch=batch,
                    path_prefix=f"records[{index}].",
                )
            )
        return ValidationReport(issues=tuple(issues))
