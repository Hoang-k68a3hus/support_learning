from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks.pdf_table_continuation_real_v0_1.evaluate import (
    BenchmarkContractError,
    evaluate,
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
