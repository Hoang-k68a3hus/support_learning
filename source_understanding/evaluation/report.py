from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from source_understanding.schemas.context import Identifier, JsonObject, SchemaModel

from .alignment import ElementAlignmentResult
from .metrics import AccuracyScore, LabelPRF, PRFScore


class EvaluationErrorType(StrEnum):
    ADAPTER_MISSING_ELEMENT = "ADAPTER_MISSING_ELEMENT"
    ADAPTER_EXTRA_ELEMENT = "ADAPTER_EXTRA_ELEMENT"
    ELEMENT_TYPE_MISMATCH = "ELEMENT_TYPE_MISMATCH"
    HEADING_MISSED = "HEADING_MISSED"
    HEADING_FALSE_POSITIVE = "HEADING_FALSE_POSITIVE"
    HEADING_LEVEL_MISMATCH = "HEADING_LEVEL_MISMATCH"
    LOGICAL_UNIT_OVER_MERGE = "LOGICAL_UNIT_OVER_MERGE"
    LOGICAL_UNIT_OVER_SPLIT = "LOGICAL_UNIT_OVER_SPLIT"
    INTEGRITY_BLOCK_BROKEN = "INTEGRITY_BLOCK_BROKEN"
    HIERARCHY_WRONG_PARENT = "HIERARCHY_WRONG_PARENT"
    HIERARCHY_WRONG_LEVEL = "HIERARCHY_WRONG_LEVEL"
    REGION_BOUNDARY_MISSING = "REGION_BOUNDARY_MISSING"
    REGION_BOUNDARY_EXTRA = "REGION_BOUNDARY_EXTRA"
    REGION_WRONG_CATEGORY = "REGION_WRONG_CATEGORY"
    STRUCTURE_MODE_MISMATCH = "STRUCTURE_MODE_MISMATCH"
    RELATION_MISSING = "RELATION_MISSING"
    RELATION_EXTRA = "RELATION_EXTRA"
    RELATION_WRONG_TYPE = "RELATION_WRONG_TYPE"
    SOURCE_TEXT_LOSS = "SOURCE_TEXT_LOSS"
    EXPECTED_DIAGNOSTIC_MISSING = "EXPECTED_DIAGNOSTIC_MISSING"
    UNEXPECTED_STRUCTURAL_DIAGNOSTIC = "UNEXPECTED_STRUCTURAL_DIAGNOSTIC"
    STRUCTURAL_READY_MISMATCH = "STRUCTURAL_READY_MISMATCH"
    ALIGNMENT_AMBIGUOUS = "ALIGNMENT_AMBIGUOUS"


class EvaluationError(SchemaModel):
    type: EvaluationErrorType
    message: str = Field(min_length=1, max_length=8192)
    gold_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    predicted_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    metadata: JsonObject = Field(default_factory=dict)


class DocumentEvaluationMetrics(SchemaModel):
    gold_element_count: int = Field(ge=0)
    predicted_element_count: int = Field(ge=0)
    aligned_element_count: int = Field(ge=0)

    element_detection: PRFScore
    element_type_accuracy: AccuracyScore
    element_type_macro_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    element_type_per_label: tuple[LabelPRF, ...] = Field(default_factory=tuple)

    heading_detection: PRFScore
    heading_level_accuracy: AccuracyScore

    hierarchy_parent_edges: PRFScore

    logical_unit_pairwise: PRFScore
    integrity_exact_match: PRFScore

    region_boundary: PRFScore
    region_category_accuracy: AccuracyScore

    structural_relations: PRFScore
    relation_per_label: tuple[LabelPRF, ...] = Field(default_factory=tuple)

    source_text_exact: AccuracyScore
    source_text_preservation_ratio: float | None = Field(default=None, ge=0.0, le=1.0)

    expected_diagnostic_recall: AccuracyScore
    unexpected_structural_diagnostic_count: int = Field(ge=0)

    predicted_structure_mode: str | None = None
    expected_structure_mode: str | None = None
    structure_mode_matches: bool | None = None

    predicted_structural_ready: bool | None = None
    expected_structural_ready: bool | None = None
    structural_ready_matches: bool | None = None


class DocumentEvaluationReport(SchemaModel):
    schema_version: str = "0.1"
    document_id: Identifier
    metrics: DocumentEvaluationMetrics
    alignment: ElementAlignmentResult
    errors: tuple[EvaluationError, ...] = Field(default_factory=tuple)
    diagnostics: JsonObject = Field(default_factory=dict)


class AggregateMetric(SchemaModel):
    name: str = Field(min_length=1, max_length=256)
    mean: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum: float | None = Field(default=None, ge=0.0, le=1.0)
    maximum: float | None = Field(default=None, ge=0.0, le=1.0)
    document_count: int = Field(ge=0)


class BenchmarkEvaluationReport(SchemaModel):
    benchmark_name: str = Field(min_length=1, max_length=256)
    benchmark_version: str = Field(min_length=1, max_length=64)
    document_reports: tuple[DocumentEvaluationReport, ...]
    aggregate: tuple[AggregateMetric, ...] = Field(default_factory=tuple)
    total_error_count: int = Field(ge=0)
    error_type_counts: JsonObject = Field(default_factory=dict)
