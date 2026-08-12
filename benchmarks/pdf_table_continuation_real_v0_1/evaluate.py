from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BenchmarkContractError(ValueError):
    """The independent continuation benchmark contract is invalid."""


@dataclass(frozen=True)
class GoldCase:
    id: str
    source_id: str
    page_a: int
    page_b: int
    truth: str
    family: str
    rationale: str
    chain_id: str | None = None

    @property
    def key(self) -> tuple[str, int, int]:
        return self.source_id, self.page_a, self.page_b


@dataclass(frozen=True)
class ContinuationMetrics:
    case_count: int
    positive_count: int
    negative_count: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None
    recall: float | None
    f1: float | None
    zero_false_continuation_gate: bool
    chain_requirements_passed: bool
    promotion_gate_passed: bool


def load_gold(path: Path) -> tuple[GoldCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = tuple(
        GoldCase(
            id=item["id"],
            source_id=item["source_id"],
            page_a=item["page_a"],
            page_b=item["page_b"],
            truth=item["truth"],
            family=item["family"],
            rationale=item["rationale"],
            chain_id=item.get("chain_id"),
        )
        for item in payload["cases"]
    )
    _validate_gold(cases, payload.get("chain_requirements", ()))
    return cases


def evaluate(
    gold: tuple[GoldCase, ...],
    predicted: set[tuple[str, int, int]],
    chain_requirements: tuple[dict[str, Any], ...] = (),
) -> ContinuationMetrics:
    gold_keys = {case.key for case in gold}
    if len(gold_keys) != len(gold):
        raise BenchmarkContractError("gold continuation case keys must be unique")
    unknown_predictions = predicted - gold_keys
    if unknown_predictions:
        raise BenchmarkContractError(
            f"predictions contain unadjudicated page pairs: {sorted(unknown_predictions)!r}"
        )
    positives = {case.key for case in gold if case.truth == "CONTINUES"}
    negatives = {case.key for case in gold if case.truth == "NOT_CONTINUES"}
    tp = len(predicted & positives)
    fp = len(predicted & negatives)
    fn = len(positives - predicted)
    tn = len(negatives - predicted)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    chains_passed = _chains_pass(gold, predicted, chain_requirements)
    zero_fp = fp == 0
    return ContinuationMetrics(
        case_count=len(gold),
        positive_count=len(positives),
        negative_count=len(negatives),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        zero_false_continuation_gate=zero_fp,
        chain_requirements_passed=chains_passed,
        promotion_gate_passed=zero_fp and chains_passed and fn == 0,
    )


def _validate_gold(cases: tuple[GoldCase, ...], requirements: list[dict[str, Any]]) -> None:
    if len(cases) < 10 or len(cases) > 20:
        raise BenchmarkContractError("M2.7.1 requires 10-20 adjudicated page-pair cases")
    if any(case.page_b != case.page_a + 1 for case in cases):
        raise BenchmarkContractError("all gold cases must be adjacent page pairs")
    if any(case.truth not in {"CONTINUES", "NOT_CONTINUES"} for case in cases):
        raise BenchmarkContractError("gold truth must be CONTINUES or NOT_CONTINUES")
    if not any(case.truth == "CONTINUES" for case in cases):
        raise BenchmarkContractError("gold must contain at least one positive continuation")
    if not any(case.truth == "NOT_CONTINUES" for case in cases):
        raise BenchmarkContractError("gold must contain at least one hard negative")
    if not any(item.get("contains_three_page_chain") for item in requirements):
        raise BenchmarkContractError("gold must require a three-page continuation chain")


def _chains_pass(
    gold: tuple[GoldCase, ...],
    predicted: set[tuple[str, int, int]],
    requirements: tuple[dict[str, Any], ...],
) -> bool:
    for requirement in requirements:
        source_id = requirement["source_id"]
        pages = tuple(requirement["pages"])
        expected = {
            (source_id, left, left + 1)
            for left in pages[:-1]
        }
        available = {case.key for case in gold if case.key in expected and case.truth == "CONTINUES"}
        if len(available) != requirement["required_positive_edge_count"]:
            return False
        if not available <= predicted:
            return False
    return True
