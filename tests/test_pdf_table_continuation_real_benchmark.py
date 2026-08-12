from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks.pdf_table_continuation_real_v0_1.evaluate import (
    BenchmarkContractError,
    CoverageAdjudication,
    classify_predictions,
    evaluate,
    evaluate_coverage,
    load_coverage_adjudications,
    load_gold,
)

ROOT = Path(__file__).parents[1] / "benchmarks" / "pdf_table_continuation_real_v0_1"


class PdfTableContinuationRealBenchmarkTests(unittest.TestCase):
    def _load_mutated_gold(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        payload = json.loads((ROOT / "gold_contracts.json").read_text(encoding="utf-8"))
        mutate(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gold.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            load_gold(path)

    def _assert_malformed_gold(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        with self.assertRaises(BenchmarkContractError):
            self._load_mutated_gold(mutate)

    def _coverage_payload(self) -> dict[str, Any]:
        return {
            "benchmark": "pdf_table_continuation_real_v0_1",
            "schema_version": "0.1",
            "provenance": "INDEPENDENT_VISUAL_LAYOUT_ADJUDICATION",
            "review_policy": "Independent review",
            "adjudications": [
                {
                    "id": "coverage-p06-p07",
                    "source_id": "hien-990-vocabulary-2026",
                    "page_a": 6,
                    "page_b": 7,
                    "truth": "CONTINUES",
                    "family": "VOCABULARY_TABLE_CHAIN",
                    "rationale": "The same table continues.",
                    "review_method": "VISUAL_LAYOUT_AND_SOURCE_CONTENT",
                }
            ],
        }

    def _load_mutated_coverage(
        self,
        mutate: Callable[[dict[str, Any]], None],
    ) -> None:
        payload = self._coverage_payload()
        mutate(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            load_coverage_adjudications(
                path,
                core_gold=load_gold(ROOT / "gold_contracts.json"),
            )

    def _assert_malformed_coverage(
        self,
        mutate: Callable[[dict[str, Any]], None],
    ) -> None:
        with self.assertRaises(BenchmarkContractError):
            self._load_mutated_coverage(mutate)

    def _coverage_case(
        self,
        *,
        page_a: int = 6,
        truth: str = "CONTINUES",
    ) -> CoverageAdjudication:
        return CoverageAdjudication(
            id=f"coverage-p{page_a:02d}-p{page_a + 1:02d}",
            source_id="hien-990-vocabulary-2026",
            page_a=page_a,
            page_b=page_a + 1,
            truth=truth,
            family="VOCABULARY_TABLE_CHAIN",
            rationale="Independent layout review.",
            review_method="VISUAL_LAYOUT_AND_SOURCE_CONTENT",
        )

    def test_gold_has_positive_negative_and_three_page_chain(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        self.assertGreaterEqual(len(gold), 10)
        self.assertLessEqual(len(gold), 20)
        self.assertTrue(any(case.truth == "CONTINUES" for case in gold))
        self.assertTrue(any(case.truth == "NOT_CONTINUES" for case in gold))
        payload = json.loads((ROOT / "gold_contracts.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["contains_three_page_chain"] for item in payload["chain_requirements"]))

    def test_evaluator_requires_zero_false_continuation_links(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        positive = {case.key for case in gold if case.truth == "CONTINUES"}
        negative = next(case.key for case in gold if case.truth == "NOT_CONTINUES")
        metrics = evaluate(gold, positive | {negative})
        self.assertEqual(metrics.false_positive, 1)
        self.assertFalse(metrics.zero_false_continuation_gate)
        self.assertFalse(metrics.promotion_gate_passed)

    def test_evaluator_rejects_unadjudicated_prediction(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        with self.assertRaises(BenchmarkContractError):
            evaluate(gold, {(gold[0].source_id, 999, 1000)})

    def test_gold_rejects_duplicate_case_ids(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            cases = payload["cases"]
            assert isinstance(cases, list)
            cases[1]["id"] = cases[0]["id"]

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_duplicate_page_pair_keys(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            cases = payload["cases"]
            assert isinstance(cases, list)
            cases[1]["page_a"] = cases[0]["page_a"]
            cases[1]["page_b"] = cases[0]["page_b"]

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_duplicate_chain_ids(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            requirements = payload["chain_requirements"]
            assert isinstance(requirements, list)
            requirements.append(dict(requirements[0]))

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_short_three_page_chain(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            requirements = payload["chain_requirements"]
            assert isinstance(requirements, list)
            requirements[0]["pages"] = [1, 2]
            requirements[0]["required_positive_edge_count"] = 1

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_non_contiguous_chain_pages(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            requirements = payload["chain_requirements"]
            assert isinstance(requirements, list)
            requirements[0]["pages"] = [1, 2, 4, 5, 6, 7]

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_duplicate_chain_pages(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            requirements = payload["chain_requirements"]
            assert isinstance(requirements, list)
            requirements[0]["pages"] = [1, 2, 2, 3, 4, 5]

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_wrong_required_positive_edge_count(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            requirements = payload["chain_requirements"]
            assert isinstance(requirements, list)
            requirements[0]["required_positive_edge_count"] = 3

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_unknown_case_chain_id(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            cases = payload["cases"]
            assert isinstance(cases, list)
            cases[0]["chain_id"] = "unknown-chain"

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_chain_edge_without_chain_id(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            cases = payload["cases"]
            assert isinstance(cases, list)
            cases[0]["chain_id"] = None

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_negative_inside_required_chain(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            cases = payload["cases"]
            assert isinstance(cases, list)
            cases[1]["truth"] = "NOT_CONTINUES"

        self._assert_malformed_gold(mutate)

    def test_gold_rejects_missing_required_chain_edge(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            cases = payload["cases"]
            assert isinstance(cases, list)
            del cases[0]

        self._assert_malformed_gold(mutate)

    def test_f1_is_zero_for_zero_precision_and_recall(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        negative = next(case.key for case in gold if case.truth == "NOT_CONTINUES")
        metrics = evaluate(gold, {negative})
        self.assertEqual(metrics.precision, 0.0)
        self.assertEqual(metrics.recall, 0.0)
        self.assertEqual(metrics.f1, 0.0)

    def test_f1_is_none_when_precision_is_undefined(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        metrics = evaluate(gold, set())
        self.assertIsNone(metrics.precision)
        self.assertEqual(metrics.recall, 0.0)
        self.assertIsNone(metrics.f1)

    def test_coverage_accepts_empty_ledger(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        coverage = load_coverage_adjudications(
            ROOT / "coverage_adjudications.json",
            core_gold=gold,
        )
        self.assertEqual(coverage, ())

    def test_coverage_rejects_wrong_benchmark_name(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["benchmark"] = "other-benchmark"

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_unsupported_schema_version(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["schema_version"] = "9.9"

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_duplicate_ids(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            adjudications = payload["adjudications"]
            assert isinstance(adjudications, list)
            duplicate = dict(adjudications[0])
            duplicate["page_a"] = 7
            duplicate["page_b"] = 8
            adjudications.append(duplicate)

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_duplicate_page_pair_keys(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            adjudications = payload["adjudications"]
            assert isinstance(adjudications, list)
            duplicate = dict(adjudications[0])
            duplicate["id"] = "coverage-duplicate-key"
            adjudications.append(duplicate)

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_non_adjacent_pair(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            adjudications = payload["adjudications"]
            assert isinstance(adjudications, list)
            adjudications[0]["page_b"] = 8

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_invalid_truth(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            adjudications = payload["adjudications"]
            assert isinstance(adjudications, list)
            adjudications[0]["truth"] = "PENDING"

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_empty_rationale(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            adjudications = payload["adjudications"]
            assert isinstance(adjudications, list)
            adjudications[0]["rationale"] = "  "

        self._assert_malformed_coverage(mutate)

    def test_coverage_rejects_core_gold_overlap(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            adjudications = payload["adjudications"]
            assert isinstance(adjudications, list)
            adjudications[0]["id"] = "coverage-core-overlap"
            adjudications[0]["page_a"] = 1
            adjudications[0]["page_b"] = 2

        self._assert_malformed_coverage(mutate)

    def test_coverage_true_prediction_does_not_block_gate(self) -> None:
        case = self._coverage_case(truth="CONTINUES")
        metrics = evaluate_coverage((case,), {case.key})
        self.assertEqual(metrics.confirmed_true_continuation_count, 1)
        self.assertEqual(metrics.confirmed_false_continuation_count, 0)
        self.assertTrue(metrics.zero_confirmed_false_continuation_gate)

    def test_coverage_false_prediction_blocks_gate(self) -> None:
        case = self._coverage_case(truth="NOT_CONTINUES")
        metrics = evaluate_coverage((case,), {case.key})
        self.assertEqual(metrics.confirmed_false_continuation_count, 1)
        self.assertFalse(metrics.zero_confirmed_false_continuation_gate)

    def test_coverage_adjudicated_but_not_currently_predicted_is_reported(self) -> None:
        case = self._coverage_case(truth="CONTINUES")
        metrics = evaluate_coverage((case,), set())
        self.assertEqual(metrics.adjudicated_count, 1)
        self.assertEqual(metrics.currently_predicted_adjudicated_count, 0)
        self.assertEqual(metrics.adjudicated_not_currently_predicted_count, 1)
        self.assertTrue(metrics.zero_confirmed_false_continuation_gate)

    def test_classify_predictions_separates_core_coverage_and_unknown(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        core_key = next(case.key for case in gold if case.truth == "CONTINUES")
        coverage = (self._coverage_case(),)
        unknown = ("not-in-any-ledger", 1, 2)
        classified = classify_predictions(
            {core_key, coverage[0].key, unknown},
            gold,
            coverage,
        )
        self.assertEqual(set(classified.core), {core_key})
        self.assertEqual(set(classified.coverage), {coverage[0].key})
        self.assertEqual(set(classified.unknown), {unknown})

    def test_coverage_does_not_change_core_metrics(self) -> None:
        gold = load_gold(ROOT / "gold_contracts.json")
        gold_payload = json.loads((ROOT / "gold_contracts.json").read_text(encoding="utf-8"))
        positive_keys = [case.key for case in gold if case.truth == "CONTINUES"]
        predicted_core = set(positive_keys[:5])
        coverage = tuple(self._coverage_case(page_a=page) for page in range(6, 26))
        classified = classify_predictions(
            predicted_core | {case.key for case in coverage},
            gold,
            coverage,
        )
        metrics = evaluate(
            gold,
            set(classified.core),
            tuple(gold_payload["chain_requirements"]),
        )
        self.assertEqual(metrics.case_count, 19)
        self.assertEqual(metrics.positive_count, 7)
        self.assertEqual(metrics.true_positive, 5)
        self.assertEqual(metrics.false_negative, 2)
        self.assertEqual(metrics.recall, 5 / 7)
