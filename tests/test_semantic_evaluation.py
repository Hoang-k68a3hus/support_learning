from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from source_understanding.evaluation.semantic import (
    GoldSemanticAnnotation,
    GoldSemanticDocument,
    GoldSemanticElement,
    GoldSemanticEvaluationScope,
    GoldSemanticEvidenceSpan,
    GoldSemanticTarget,
    SemanticEvaluationError,
    SemanticRoleEvaluator,
    aggregate_semantic_reports,
    semantic_element_snapshot_hash,
)
from source_understanding.evaluation.schemas import BenchmarkSplit
from source_understanding.evaluation.metrics import prf_counts
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import (
    CanonicalDocument,
    ProcessingManifest,
    SemanticAnnotation,
    SemanticAnnotationType,
    SemanticTextView,
)
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.semantics.provider import SemanticTargetKind
from benchmarks.semantic_roles_v0_1.run_benchmark import (
    evaluate_heuristic,
    evaluate_heuristic_benchmark,
    heuristic_annotator_policy,
    heuristic_provider,
    heuristic_quality_gate,
)
from source_understanding.retrieval_units import (
    SemanticRetrievalEnrichmentError,
    SemanticQualityGateStatus,
    quality_gate_from_semantic_benchmark,
)
from source_understanding.semantics import HeuristicSemanticProvider


def gold_document() -> GoldSemanticDocument:
    elements = (
        GoldSemanticElement(
            order=0,
            raw_text="Definition: A queue follows FIFO.",
            normalized_text="Definition: A queue follows FIFO.",
        ),
        GoldSemanticElement(
            order=1,
            raw_text="Example: enqueue A then B.",
            normalized_text="Example: enqueue A then B.",
        ),
    )
    return GoldSemanticDocument(
        document_id="semantic-case",
        content_hash="sha256:" + "a" * 64,
        element_snapshot_hash=semantic_element_snapshot_hash(elements),
        split=BenchmarkSplit.DEV,
        language="en",
        elements=elements,
        evaluation_scopes=tuple(
            GoldSemanticEvaluationScope(
                target=GoldSemanticTarget(
                    kind=SemanticTargetKind.ELEMENT,
                    element_orders=(order,),
                ),
                evaluated_types=(
                    SemanticAnnotationType.DEFINITION,
                    SemanticAnnotationType.EXAMPLE,
                ),
            )
            for order in (0, 1)
        ),
        annotations=(
            GoldSemanticAnnotation(
                target=GoldSemanticTarget(
                    kind=SemanticTargetKind.ELEMENT,
                    element_orders=(0,),
                ),
                type=SemanticAnnotationType.DEFINITION,
            ),
            GoldSemanticAnnotation(
                target=GoldSemanticTarget(
                    kind=SemanticTargetKind.ELEMENT,
                    element_orders=(1,),
                ),
                type=SemanticAnnotationType.EXAMPLE,
            ),
        ),
    )


def predicted_document(
    gold: GoldSemanticDocument,
    labels: tuple[tuple[str, SemanticAnnotationType], ...],
) -> CanonicalDocument:
    elements = tuple(
        Element(
            id=f"e{item.order}",
            order=item.order,
            type=item.type,
            raw_text=item.raw_text,
            normalized_text=item.normalized_text,
            provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
        )
        for item in gold.elements
    )
    unit = LogicalUnit(
        id="lu0",
        type=LogicalUnitType.TEXT_BLOCK,
        element_ids=tuple(element.id for element in elements),
        source=StructureSource.DERIVED,
        confidence=0.8,
    )
    annotations = tuple(
        SemanticAnnotation(
            id=f"a{index}",
            target_id=target_id,
            type=annotation_type,
            value=annotation_type.value,
            source=StructureSource.INFERRED,
            confidence=0.9,
        )
        for index, (target_id, annotation_type) in enumerate(labels)
    )
    return CanonicalDocument(
        document_id=gold.document_id,
        content_hash=gold.content_hash,
        processing=ProcessingManifest(
            adapter_name="semantic-gold",
            processed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        elements=elements,
        logical_units=(unit,),
        semantic_annotations=annotations,
    )


class SemanticEvaluationTests(unittest.TestCase):
    def test_repository_gold_dataset_is_valid_and_baseline_is_reproducible(self) -> None:
        reports = evaluate_heuristic(BenchmarkSplit.DEV)

        from benchmarks.semantic_roles_v0_1.run_benchmark import GOLD_PATH
        from source_understanding.evaluation import load_semantic_gold_dataset

        dataset = load_semantic_gold_dataset(GOLD_PATH)
        self.assertEqual(
            {case.split for case in dataset.cases},
            {BenchmarkSplit.DEV, BenchmarkSplit.TEST},
        )

        self.assertEqual(len(reports), 1)
        self.assertTrue(all(report.overall.f1 == 1.0 for report in reports))
        aggregate = evaluate_heuristic_benchmark(BenchmarkSplit.DEV)
        test_aggregate = evaluate_heuristic_benchmark(BenchmarkSplit.TEST)
        self.assertEqual(aggregate.pooled.f1, 1.0)
        self.assertEqual(test_aggregate.pooled.f1, 1.0)
        self.assertEqual(test_aggregate.split, BenchmarkSplit.TEST)
        self.assertNotEqual(aggregate.dataset_hash, test_aggregate.dataset_hash)
        self.assertEqual(aggregate.macro_type_f1, 1.0)
        self.assertEqual(aggregate.macro_target_f1, 1.0)
        self.assertEqual(aggregate.macro_target_kind_f1, 1.0)
        gate = heuristic_quality_gate()
        self.assertEqual(gate.benchmark_name, "semantic-roles-pilot")
        self.assertEqual(gate.benchmark_split, "test")
        self.assertTrue(all(item.role_f1 == 1.0 for item in gate.decisions))
        self.assertEqual(
            {item.target_kind for item in gate.decisions},
            {SemanticTargetKind.ELEMENT},
        )
        self.assertEqual(
            {item.language for item in gate.decisions},
            {"en", "vi"},
        )

    def test_dev_report_cannot_authorize_retrieval_enrichment(self) -> None:
        provider = heuristic_provider()

        with self.assertRaisesRegex(
            SemanticRetrievalEnrichmentError,
            "held-out TEST",
        ):
            quality_gate_from_semantic_benchmark(
                evaluate_heuristic_benchmark(BenchmarkSplit.DEV),
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
                    HeuristicSemanticProvider.name: (
                        heuristic_annotator_policy().model_dump(mode="json")
                    ),
                },
                minimum_role_f1=0.95,
            )

    def test_aggregate_rejects_reports_from_a_different_split(self) -> None:
        from benchmarks.semantic_roles_v0_1.run_benchmark import GOLD_PATH
        from source_understanding.evaluation import load_semantic_gold_dataset

        dataset = load_semantic_gold_dataset(GOLD_PATH)
        dev_reports = evaluate_heuristic(BenchmarkSplit.DEV)

        with self.assertRaisesRegex(SemanticEvaluationError, "cannot mix"):
            aggregate_semantic_reports(
                dataset,
                dev_reports,
                split=BenchmarkSplit.TEST,
            )

    def test_quality_gate_rejects_only_the_failing_capability_slice(self) -> None:
        report = evaluate_heuristic_benchmark(BenchmarkSplit.TEST)
        first = next(
            item
            for item in report.capability_slices
            if item.provider_name != "SYSTEM_FUSED" and item.role.support > 0
        )
        rest = [item for item in report.capability_slices if item is not first]
        degraded = report.model_copy(
            update={
                "capability_slices": (
                    first.model_copy(update={"role": prf_counts(1, 2, 0)}),
                    *rest,
                )
            }
        )
        provider = heuristic_provider()

        gate = quality_gate_from_semantic_benchmark(
            degraded,
            semantic_version="semantic-annotations:3",
            provider_versions={provider.name: provider.version},
            provider_capabilities={provider.name: provider.capabilities},
            provider_configurations={provider.name: provider.configuration},
            provider_annotator_policies={
                provider.name: heuristic_annotator_policy().model_dump(mode="json")
            },
            minimum_role_f1=0.95,
        )

        rejected = tuple(
            item
            for item in gate.decisions
            if item.status == SemanticQualityGateStatus.REJECTED
        )
        approved = tuple(
            item
            for item in gate.decisions
            if item.status == SemanticQualityGateStatus.APPROVED
        )
        self.assertGreaterEqual(len(rejected), 2)
        self.assertTrue(
            any("ROLE_F1_BELOW_THRESHOLD" in item.reasons for item in rejected)
        )
        self.assertTrue(approved)

    def test_scores_precision_recall_f1_by_type_and_target(self) -> None:
        gold = gold_document()
        predicted = predicted_document(
            gold,
            (
                ("e0", SemanticAnnotationType.DEFINITION),
                ("e1", SemanticAnnotationType.WARNING),
            ),
        )

        report = SemanticRoleEvaluator().evaluate(gold, predicted)

        self.assertEqual(report.overall.true_positive, 1)
        self.assertEqual(report.overall.false_negative, 1)
        self.assertEqual(report.overall.false_positive, 0)
        self.assertEqual(report.overall.f1, 2 / 3)
        self.assertEqual(
            {item.label: item.score.f1 for item in report.by_type},
            {"DEFINITION": 1.0, "EXAMPLE": 0.0},
        )
        self.assertEqual(len(report.by_target), 2)
        self.assertEqual(
            {item.label: item.score.f1 for item in report.by_target_kind},
            {"ELEMENT": 2 / 3},
        )

    def test_logical_unit_targets_align_by_member_orders_not_runtime_id(self) -> None:
        payload = gold_document().model_dump(mode="json")
        logical_target = GoldSemanticTarget(
            kind=SemanticTargetKind.LOGICAL_UNIT,
            element_orders=(0, 1),
        )
        payload["evaluation_scopes"] = [
            GoldSemanticEvaluationScope(
                target=logical_target,
                evaluated_types=(SemanticAnnotationType.DEFINITION,),
            ).model_dump(mode="json")
        ]
        payload["annotations"] = [
            GoldSemanticAnnotation(
                target=logical_target,
                type=SemanticAnnotationType.DEFINITION,
            ).model_dump(mode="json")
        ]
        gold = GoldSemanticDocument.model_validate(payload)
        predicted = predicted_document(
            gold,
            (("lu0", SemanticAnnotationType.DEFINITION),),
        )

        report = SemanticRoleEvaluator().evaluate(gold, predicted)

        self.assertEqual(report.overall.f1, 1.0)
        self.assertEqual(report.by_target[0].label, "LOGICAL_UNIT:0,1")
        self.assertEqual(report.by_target_kind[0].score.f1, 1.0)

    def test_prediction_outside_target_scope_is_ignored_not_false_positive(self) -> None:
        original = gold_document()
        payload = original.model_dump(mode="json")
        target = GoldSemanticTarget(
            kind=SemanticTargetKind.ELEMENT,
            element_orders=(0,),
        )
        payload["evaluation_scopes"] = [
            GoldSemanticEvaluationScope(
                target=target,
                evaluated_types=(SemanticAnnotationType.DEFINITION,),
            ).model_dump(mode="json"),
            GoldSemanticEvaluationScope(
                target=GoldSemanticTarget(
                    kind=SemanticTargetKind.ELEMENT,
                    element_orders=(1,),
                ),
                evaluated_types=(SemanticAnnotationType.EXAMPLE,),
            ).model_dump(mode="json"),
        ]
        payload["annotations"] = [
            GoldSemanticAnnotation(
                target=target,
                type=SemanticAnnotationType.DEFINITION,
            ).model_dump(mode="json")
        ]
        gold = GoldSemanticDocument.model_validate(payload)
        predicted = predicted_document(
            gold,
            (
                ("e0", SemanticAnnotationType.DEFINITION),
                ("e0", SemanticAnnotationType.EXAMPLE),
                ("e1", SemanticAnnotationType.DEFINITION),
            ),
        )

        report = SemanticRoleEvaluator().evaluate(gold, predicted)

        self.assertEqual(report.overall.true_positive, 1)
        self.assertEqual(report.overall.false_positive, 0)
        self.assertEqual(report.predicted_annotation_count, 1)
        self.assertEqual(report.overall.f1, 1.0)

    def test_v2_gold_is_rejected_instead_of_silently_changing_semantics(self) -> None:
        payload = gold_document().model_dump(mode="json")
        payload["schema_version"] = "2"
        payload["benchmark_version"] = "semantic-roles-v0.2"

        with self.assertRaisesRegex(ValidationError, "unsupported semantic gold"):
            GoldSemanticDocument.model_validate(payload)

    def test_gold_evidence_uses_the_selected_raw_or_normalized_view(self) -> None:
        elements = (
            GoldSemanticElement(
                order=0,
                raw_text="Definition: A  queue.",
                normalized_text="Definition: A queue.",
            ),
        )
        target = GoldSemanticTarget(
            kind=SemanticTargetKind.ELEMENT,
            element_orders=(0,),
        )
        evidence = GoldSemanticEvidenceSpan(
            element_order=0,
            start_char=12,
            end_char=20,
            quoted_text="A queue.",
            text_view=SemanticTextView.NORMALIZED_TEXT,
        )
        gold = GoldSemanticDocument(
            document_id="semantic-views",
            content_hash="sha256:" + "b" * 64,
            element_snapshot_hash=semantic_element_snapshot_hash(elements),
            split=BenchmarkSplit.DEV,
            language="en",
            elements=elements,
            evaluation_scopes=(
                GoldSemanticEvaluationScope(
                    target=target,
                    evaluated_types=(SemanticAnnotationType.DEFINITION,),
                ),
            ),
            annotations=(
                GoldSemanticAnnotation(
                    target=target,
                    type=SemanticAnnotationType.DEFINITION,
                    value="A queue.",
                    evidence=(evidence,),
                ),
            ),
        )

        invalid_payload = gold.model_dump(mode="json")
        invalid_payload["annotations"][0]["evidence"][0]["text_view"] = "RAW_TEXT"
        with self.assertRaisesRegex(ValidationError, "quote does not match"):
            GoldSemanticDocument.model_validate(invalid_payload)

    def test_source_revision_validation_compares_both_text_views_exactly(self) -> None:
        gold = gold_document()
        predicted = predicted_document(gold, ())
        changed_element = predicted.elements[0].model_copy(
            update={"normalized_text": "Definition: A changed queue."}
        )
        changed = predicted.model_copy(
            update={"elements": (changed_element, *predicted.elements[1:])}
        )

        with self.assertRaisesRegex(SemanticEvaluationError, "disagrees"):
            SemanticRoleEvaluator().evaluate(gold, changed)

    def test_refuses_to_score_a_different_source_revision(self) -> None:
        gold = gold_document()
        predicted = predicted_document(
            gold,
            (("e0", SemanticAnnotationType.DEFINITION),),
        ).model_copy(update={"content_hash": "sha256:" + "f" * 64})

        with self.assertRaisesRegex(SemanticEvaluationError, "content_hash"):
            SemanticRoleEvaluator().evaluate(gold, predicted)


if __name__ == "__main__":
    unittest.main()
