"""Document-structure benchmark and evaluation utilities.

This package is downstream of canonical source understanding. It measures
structural output quality; it never changes parsing behavior.
"""

from .alignment import (
    AlignmentMethod,
    AlignmentStatus,
    ElementAligner,
    ElementAlignmentResult,
    ElementMatch,
)
from .benchmark import BenchmarkEvaluator
from .evaluator import DocumentStructureEvaluator
from .loader import (
    EvaluationLoadError,
    LoadedBenchmark,
    LoadedBenchmarkCase,
    load_benchmark_manifest,
    load_gold_document,
    load_materialized_benchmark,
)
from .metrics import AccuracyScore, LabelPRF, PRFScore
from .report import (
    AggregateMetric,
    BenchmarkEvaluationReport,
    BenchmarkPooledMetrics,
    DocumentEvaluationMetrics,
    DocumentEvaluationReport,
    EvaluationError,
    EvaluationErrorType,
)
from .schemas import (
    DOCUMENT_STRUCTURE_EVAL_SCHEMA_VERSION,
    DOCX_GOLD_BENCHMARK_VERSION,
    BenchmarkCase,
    BenchmarkManifest,
    BenchmarkSourceKind,
    BenchmarkSplit,
    ExpectedAdapterDiagnostic,
    GoldContextNode,
    GoldDocumentStructure,
    GoldElement,
    GoldLogicalUnit,
    GoldRegion,
    GoldRegionCategory,
    GoldRelation,
    GoldSourceAnchor,
    GoldSourceDescriptor,
    UnsupportedConstruct,
)

__all__ = [
    "AccuracyScore",
    "AggregateMetric",
    "AlignmentMethod",
    "AlignmentStatus",
    "BenchmarkCase",
    "BenchmarkEvaluationReport",
    "BenchmarkEvaluator",
    "BenchmarkManifest",
    "BenchmarkPooledMetrics",
    "BenchmarkSourceKind",
    "BenchmarkSplit",
    "DOCUMENT_STRUCTURE_EVAL_SCHEMA_VERSION",
    "DOCX_GOLD_BENCHMARK_VERSION",
    "DocumentEvaluationMetrics",
    "DocumentEvaluationReport",
    "DocumentStructureEvaluator",
    "ElementAligner",
    "ElementAlignmentResult",
    "ElementMatch",
    "EvaluationError",
    "EvaluationErrorType",
    "EvaluationLoadError",
    "ExpectedAdapterDiagnostic",
    "GoldContextNode",
    "GoldDocumentStructure",
    "GoldElement",
    "GoldLogicalUnit",
    "GoldRegion",
    "GoldRegionCategory",
    "GoldRelation",
    "GoldSourceAnchor",
    "GoldSourceDescriptor",
    "LabelPRF",
    "LoadedBenchmark",
    "LoadedBenchmarkCase",
    "PRFScore",
    "UnsupportedConstruct",
    "load_benchmark_manifest",
    "load_gold_document",
    "load_materialized_benchmark",
]
