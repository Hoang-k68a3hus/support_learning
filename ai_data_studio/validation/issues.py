from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import Identifier, SchemaModel


class ValidationSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationIssueCode(StrEnum):
    SOURCE_DOCUMENT_ID_MISMATCH = "SOURCE_DOCUMENT_ID_MISMATCH"
    SOURCE_CONTENT_HASH_MISMATCH = "SOURCE_CONTENT_HASH_MISMATCH"
    SOURCE_ELEMENT_SNAPSHOT_HASH_MISMATCH = (
        "SOURCE_ELEMENT_SNAPSHOT_HASH_MISMATCH"
    )
    SOURCE_LANGUAGE_MISMATCH = "SOURCE_LANGUAGE_MISMATCH"
    SOURCE_LANGUAGE_UNAVAILABLE = "SOURCE_LANGUAGE_UNAVAILABLE"

    BATCH_ID_MISMATCH = "BATCH_ID_MISMATCH"
    BATCH_RECORD_NOT_DECLARED = "BATCH_RECORD_NOT_DECLARED"
    BATCH_EVALUATED_TYPES_MISMATCH = "BATCH_EVALUATED_TYPES_MISMATCH"
    BATCH_RECORD_MISSING = "BATCH_RECORD_MISSING"
    BATCH_UNEXPECTED_RECORD = "BATCH_UNEXPECTED_RECORD"
    BATCH_DUPLICATE_RECORD = "BATCH_DUPLICATE_RECORD"

    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_KIND_MISMATCH = "TARGET_KIND_MISMATCH"
    TARGET_ELEMENT_IDS_MISMATCH = "TARGET_ELEMENT_IDS_MISMATCH"
    TARGET_ELEMENT_ORDERS_MISMATCH = "TARGET_ELEMENT_ORDERS_MISMATCH"
    TARGET_LOGICAL_UNIT_TYPE_MISMATCH = "TARGET_LOGICAL_UNIT_TYPE_MISMATCH"
    TARGET_RAW_TEXT_MISMATCH = "TARGET_RAW_TEXT_MISMATCH"
    TARGET_NORMALIZED_TEXT_MISMATCH = "TARGET_NORMALIZED_TEXT_MISMATCH"

    EVIDENCE_ELEMENT_UNKNOWN = "EVIDENCE_ELEMENT_UNKNOWN"
    EVIDENCE_OUTSIDE_TARGET = "EVIDENCE_OUTSIDE_TARGET"
    EVIDENCE_TEXT_VIEW_MISSING = "EVIDENCE_TEXT_VIEW_MISSING"
    EVIDENCE_RANGE_OUT_OF_BOUNDS = "EVIDENCE_RANGE_OUT_OF_BOUNDS"
    EVIDENCE_QUOTE_MISMATCH = "EVIDENCE_QUOTE_MISMATCH"

    REVIEW_CHAIN_BROKEN = "REVIEW_CHAIN_BROKEN"
    REVIEW_FINAL_HASH_MISMATCH = "REVIEW_FINAL_HASH_MISMATCH"
    REVIEW_GUIDELINE_MISMATCH = "REVIEW_GUIDELINE_MISMATCH"

    SPLIT_GROUP_DUPLICATE_ASSIGNMENT = "SPLIT_GROUP_DUPLICATE_ASSIGNMENT"
    SPLIT_GROUP_UNASSIGNED = "SPLIT_GROUP_UNASSIGNED"
    SPLIT_GROUP_UNKNOWN = "SPLIT_GROUP_UNKNOWN"
    SOURCE_FAMILY_CROSSES_SPLIT_GROUP = "SOURCE_FAMILY_CROSSES_SPLIT_GROUP"
    SOURCE_FAMILY_CROSSES_SPLIT = "SOURCE_FAMILY_CROSSES_SPLIT"
    CONTENT_HASH_CROSSES_SPLIT_GROUP = "CONTENT_HASH_CROSSES_SPLIT_GROUP"
    CONTENT_HASH_CROSSES_SPLIT = "CONTENT_HASH_CROSSES_SPLIT"
    DOCUMENT_ID_CROSSES_SPLIT_GROUP = "DOCUMENT_ID_CROSSES_SPLIT_GROUP"
    DOCUMENT_ID_CROSSES_SPLIT = "DOCUMENT_ID_CROSSES_SPLIT"
    RECORD_ID_DUPLICATE = "RECORD_ID_DUPLICATE"
    SOURCE_TARGET_DUPLICATE = "SOURCE_TARGET_DUPLICATE"
    SOURCE_TARGET_CROSSES_SPLIT = "SOURCE_TARGET_CROSSES_SPLIT"


class ValidationIssue(SchemaModel):
    code: ValidationIssueCode
    severity: ValidationSeverity
    message: str = Field(min_length=1, max_length=4096)
    record_id: Identifier | None = None
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    related_ids: tuple[Identifier, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_issue(self) -> "ValidationIssue":
        if not self.message.strip() or self.message.strip() != self.message:
            raise ValueError("validation issue message must be non-blank and trimmed")
        if self.path is not None and (
            not self.path.strip() or self.path.strip() != self.path
        ):
            raise ValueError("validation issue path must be non-blank and trimmed")
        if len(self.related_ids) != len(set(self.related_ids)):
            raise ValueError("validation issue related_ids must be unique")
        return self


class ValidationReport(SchemaModel):
    issues: tuple[ValidationIssue, ...] = Field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not any(
            issue.severity == ValidationSeverity.ERROR for issue in self.issues
        )

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == ValidationSeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == ValidationSeverity.WARNING
        )
