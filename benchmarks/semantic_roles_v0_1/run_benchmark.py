from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from source_understanding.evaluation.semantic import (
    GoldSemanticDocument,
    SemanticEvaluationReport,
    SemanticBenchmarkEvaluationReport,
    SemanticRoleEvaluator,
    aggregate_semantic_reports,
    load_semantic_gold_dataset,
)
from source_understanding.evaluation.schemas import BenchmarkSplit
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import (
    CanonicalDocument,
    DocumentMetadata,
    ProcessingManifest,
)
from source_understanding.schemas.element import Element, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.retrieval_units import (
    SemanticRetrievalQualityGate,
    quality_gate_from_semantic_benchmark,
)
from source_understanding.semantics import (
    HeuristicSemanticPolicy,
    HeuristicSemanticProvider,
    LanguageRoutingMode,
    SemanticAnnotationPolicy,
    SemanticAnnotator,
)


GOLD_PATH = Path(__file__).with_name("gold.json")


def heuristic_provider() -> HeuristicSemanticProvider:
    return HeuristicSemanticProvider(
        policy=HeuristicSemanticPolicy(
            language_routing=LanguageRoutingMode.REQUEST_PRIMARY,
        )
    )


def heuristic_annotator_policy() -> SemanticAnnotationPolicy:
    return SemanticAnnotationPolicy()


def materialize_case(case: GoldSemanticDocument) -> CanonicalDocument:
    elements = tuple(
        Element(
            id=f"gold_el_{element.order}",
            order=element.order,
            type=element.type,
            raw_text=element.raw_text,
            normalized_text=element.normalized_text,
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="semantic-gold",
                extractor_version=case.benchmark_version,
            ),
        )
        for element in case.elements
    )
    logical_units = (
        LogicalUnit(
            id="gold_lu_all",
            type=LogicalUnitType.TEXT_BLOCK,
            element_ids=tuple(element.id for element in elements),
            source=StructureSource.DERIVED,
            confidence=1.0,
            metadata={"benchmark_materialization": True},
        ),
    )
    return CanonicalDocument(
        document_id=case.document_id,
        content_hash=case.content_hash,
        processing=ProcessingManifest(
            adapter_name="semantic-gold",
            adapter_version=case.benchmark_version,
            processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        metadata=DocumentMetadata(language=case.language),
        elements=elements,
        logical_units=logical_units,
    )


def evaluate_heuristic(
    split: BenchmarkSplit = BenchmarkSplit.DEV,
) -> tuple[SemanticEvaluationReport, ...]:
    dataset = load_semantic_gold_dataset(GOLD_PATH)
    provider = heuristic_provider()
    annotator_policy = heuristic_annotator_policy()
    evaluator = SemanticRoleEvaluator()
    reports: list[SemanticEvaluationReport] = []
    for case in dataset.cases:
        if case.split != split:
            continue
        document = materialize_case(case)
        enriched = SemanticAnnotator(
            provider,
            annotator_policy,
        ).annotate(document).document
        reports.append(evaluator.evaluate(case, enriched))
    return tuple(reports)


def evaluate_heuristic_benchmark(
    split: BenchmarkSplit = BenchmarkSplit.DEV,
) -> SemanticBenchmarkEvaluationReport:
    dataset = load_semantic_gold_dataset(GOLD_PATH)
    return aggregate_semantic_reports(
        dataset,
        evaluate_heuristic(split),
        split=split,
    )


def heuristic_quality_gate(
    *,
    minimum_role_f1: float = 0.95,
) -> SemanticRetrievalQualityGate:
    provider = heuristic_provider()
    return quality_gate_from_semantic_benchmark(
        evaluate_heuristic_benchmark(BenchmarkSplit.TEST),
        semantic_version="semantic-annotations:3",
        provider_versions={
            HeuristicSemanticProvider.name: HeuristicSemanticProvider.version,
        },
        provider_capabilities={
            HeuristicSemanticProvider.name: provider.capabilities,
        },
        provider_configurations={
            HeuristicSemanticProvider.name: provider.configuration,
        },
        provider_annotator_policies={
            HeuristicSemanticProvider.name: heuristic_annotator_policy().model_dump(
                mode="json"
            ),
        },
        minimum_role_f1=minimum_role_f1,
    )


if __name__ == "__main__":
    print(
        json.dumps(
            {
                split.value: evaluate_heuristic_benchmark(split).model_dump(
                    mode="json"
                )
                for split in (BenchmarkSplit.DEV, BenchmarkSplit.TEST)
            },
            ensure_ascii=False,
            indent=2,
        )
    )
