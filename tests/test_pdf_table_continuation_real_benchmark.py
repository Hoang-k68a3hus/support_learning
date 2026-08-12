from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmarks.pdf_table_continuation_real_v0_1.evaluate import (
    BenchmarkContractError,
    evaluate,
    load_gold,
)

ROOT = Path(__file__).parents[1] / "benchmarks" / "pdf_table_continuation_real_v0_1"


class PdfTableContinuationRealBenchmarkTests(unittest.TestCase):
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
