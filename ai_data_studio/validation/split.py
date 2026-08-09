from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

from ai_data_studio.datasets.splits import (
    DatasetSplit,
    DatasetSplitManifest,
)
from ai_data_studio.schemas.working import SemanticWorkingRecord
from source_understanding.semantics.provider import SemanticTargetKind

from .issues import (
    ValidationIssue,
    ValidationIssueCode,
    ValidationReport,
    ValidationSeverity,
)


SourceTargetKey = tuple[str, SemanticTargetKind, tuple[int, ...]]


class InvalidDatasetSplitError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        codes = ", ".join(issue.code.value for issue in report.errors)
        super().__init__(f"dataset split validation failed: {codes}")


def working_source_target_key(record: SemanticWorkingRecord) -> SourceTargetKey:
    return (
        record.source.content_hash,
        record.target.target_kind,
        record.target.element_orders,
    )


class DatasetSplitValidator:
    def validate(
        self,
        *,
        records: Sequence[SemanticWorkingRecord],
        manifest: DatasetSplitManifest,
    ) -> ValidationReport:
        assignments = {
            assignment.split_group_id: assignment.split
            for assignment in manifest.assignments
        }
        records_by_group: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
        family_records: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
        content_records: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
        document_records: dict[str, list[SemanticWorkingRecord]] = defaultdict(list)
        target_records: dict[SourceTargetKey, list[SemanticWorkingRecord]] = (
            defaultdict(list)
        )
        for record in records:
            records_by_group[record.source.split_group_id].append(record)
            family_records[record.source.source_family_id].append(record)
            content_records[record.source.content_hash].append(record)
            document_records[record.source.document_id].append(record)
            target_records[working_source_target_key(record)].append(record)

        issues: list[ValidationIssue] = []
        issues.extend(self._validate_record_ids(records))
        issues.extend(
            self._validate_assignment_coverage(
                records_by_group=records_by_group,
                manifest=manifest,
                assignments=assignments,
            )
        )
        issues.extend(
            self._validate_identity_topology(
                records_by_identity=family_records,
                assignments=assignments,
                identity_name="source_family_id",
                path="records[*].source.source_family_id",
                group_code=(
                    ValidationIssueCode.SOURCE_FAMILY_CROSSES_SPLIT_GROUP
                ),
                split_code=ValidationIssueCode.SOURCE_FAMILY_CROSSES_SPLIT,
            )
        )
        issues.extend(
            self._validate_identity_topology(
                records_by_identity=content_records,
                assignments=assignments,
                identity_name="content_hash",
                path="records[*].source.content_hash",
                group_code=ValidationIssueCode.CONTENT_HASH_CROSSES_SPLIT_GROUP,
                split_code=ValidationIssueCode.CONTENT_HASH_CROSSES_SPLIT,
            )
        )
        issues.extend(
            self._validate_identity_topology(
                records_by_identity=document_records,
                assignments=assignments,
                identity_name="document_id",
                path="records[*].source.document_id",
                group_code=ValidationIssueCode.DOCUMENT_ID_CROSSES_SPLIT_GROUP,
                split_code=ValidationIssueCode.DOCUMENT_ID_CROSSES_SPLIT,
            )
        )
        issues.extend(
            self._validate_source_targets(
                target_records=target_records,
                assignments=assignments,
            )
        )
        return ValidationReport(issues=tuple(issues))

    @staticmethod
    def _validate_record_ids(
        records: Sequence[SemanticWorkingRecord],
    ) -> tuple[ValidationIssue, ...]:
        counts = Counter(record.record_id for record in records)
        return tuple(
            ValidationIssue(
                code=ValidationIssueCode.RECORD_ID_DUPLICATE,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Record ID {record_id!r} occurs {counts[record_id]} times "
                    "in the split input."
                ),
                record_id=record_id,
                path="records",
            )
            for record_id in sorted(counts)
            if counts[record_id] > 1
        )

    @staticmethod
    def _validate_assignment_coverage(
        *,
        records_by_group: Mapping[str, Sequence[SemanticWorkingRecord]],
        manifest: DatasetSplitManifest,
        assignments: Mapping[str, DatasetSplit],
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        record_groups = set(records_by_group)
        manifest_groups = set(assignments)
        for group_id in sorted(record_groups - manifest_groups):
            records = records_by_group[group_id]
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SPLIT_GROUP_UNASSIGNED,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"split_group_id={group_id!r} has records but no manifest "
                        "assignment."
                    ),
                    path="manifest.assignments",
                    related_ids=_unique_ids(
                        (group_id, *(record.record_id for record in records))
                    ),
                )
            )
        assignment_indexes = {
            assignment.split_group_id: index
            for index, assignment in enumerate(manifest.assignments)
        }
        for group_id in sorted(manifest_groups - record_groups):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.SPLIT_GROUP_UNKNOWN,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Manifest split_group_id={group_id!r} has no loaded records."
                    ),
                    path=(
                        f"manifest.assignments[{assignment_indexes[group_id]}]"
                        ".split_group_id"
                    ),
                    related_ids=(group_id,),
                )
            )
        return tuple(issues)

    @staticmethod
    def _validate_identity_topology(
        *,
        records_by_identity: Mapping[str, Sequence[SemanticWorkingRecord]],
        assignments: Mapping[str, DatasetSplit],
        identity_name: str,
        path: str,
        group_code: ValidationIssueCode,
        split_code: ValidationIssueCode,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        for identity in sorted(records_by_identity):
            records = records_by_identity[identity]
            groups = tuple(
                sorted({record.source.split_group_id for record in records})
            )
            record_ids = _unique_ids(record.record_id for record in records)
            if len(groups) > 1:
                issues.append(
                    ValidationIssue(
                        code=group_code,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"{identity_name}={identity!r} belongs to multiple "
                            f"split groups: {list(groups)!r}."
                        ),
                        path=path,
                        related_ids=record_ids,
                    )
                )
            splits = tuple(
                sorted(
                    {
                        assignments[record.source.split_group_id]
                        for record in records
                        if record.source.split_group_id in assignments
                    },
                    key=lambda split: split.value,
                )
            )
            if len(splits) > 1:
                issues.append(
                    ValidationIssue(
                        code=split_code,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"{identity_name}={identity!r} resolves to multiple "
                            f"splits {[split.value for split in splits]!r} via "
                            f"split groups {list(groups)!r}."
                        ),
                        path=path,
                        related_ids=record_ids,
                    )
                )
        return tuple(issues)

    @staticmethod
    def _validate_source_targets(
        *,
        target_records: Mapping[SourceTargetKey, Sequence[SemanticWorkingRecord]],
        assignments: Mapping[str, DatasetSplit],
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        ordered_keys = sorted(
            target_records,
            key=lambda key: (key[0], key[1].value, key[2]),
        )
        for key in ordered_keys:
            records = target_records[key]
            if len(records) < 2:
                continue
            splits = tuple(
                sorted(
                    {
                        assignments[record.source.split_group_id]
                        for record in records
                        if record.source.split_group_id in assignments
                    },
                    key=lambda split: split.value,
                )
            )
            record_ids = _unique_ids(record.record_id for record in records)
            content_hash, target_kind, element_orders = key
            if len(splits) > 1:
                code = ValidationIssueCode.SOURCE_TARGET_CROSSES_SPLIT
                message = (
                    "Physical source target "
                    f"({content_hash!r}, {target_kind.value}, {element_orders!r}) "
                    f"crosses splits {[split.value for split in splits]!r}."
                )
            else:
                code = ValidationIssueCode.SOURCE_TARGET_DUPLICATE
                message = (
                    "Physical source target "
                    f"({content_hash!r}, {target_kind.value}, {element_orders!r}) "
                    "occurs more than once."
                )
            issues.append(
                ValidationIssue(
                    code=code,
                    severity=ValidationSeverity.ERROR,
                    message=message,
                    path="records[*].target",
                    related_ids=record_ids,
                )
            )
        return tuple(issues)


def resolve_record_splits(
    *,
    records: Sequence[SemanticWorkingRecord],
    manifest: DatasetSplitManifest,
) -> Mapping[str, DatasetSplit]:
    report = DatasetSplitValidator().validate(records=records, manifest=manifest)
    if not report.is_valid:
        raise InvalidDatasetSplitError(report)
    assignments = {
        assignment.split_group_id: assignment.split
        for assignment in manifest.assignments
    }
    return {
        record.record_id: assignments[record.source.split_group_id]
        for record in sorted(records, key=lambda item: item.record_id)
    }


def _unique_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
