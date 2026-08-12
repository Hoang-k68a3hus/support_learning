from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any


class BenchmarkContractError(ValueError):
    """The independent continuation benchmark contract is invalid."""


CONTINUES = "CONTINUES"
NOT_CONTINUES = "NOT_CONTINUES"
COVERAGE_BENCHMARK = "pdf_table_continuation_real_v0_1"
COVERAGE_SCHEMA_VERSION = "0.1"


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
class CoverageAdjudication:
    id: str
    source_id: str
    page_a: int
    page_b: int
    truth: str
    family: str
    rationale: str
    review_method: str

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


@dataclass(frozen=True)
class CoverageMetrics:
    adjudicated_count: int
    currently_predicted_adjudicated_count: int
    confirmed_true_continuation_count: int
    confirmed_false_continuation_count: int
    adjudicated_not_currently_predicted_count: int
    zero_confirmed_false_continuation_gate: bool


@dataclass(frozen=True)
class PredictionClassification:
    core: frozenset[tuple[str, int, int]]
    coverage: frozenset[tuple[str, int, int]]
    unknown: frozenset[tuple[str, int, int]]


def load_gold(path: Path) -> tuple[GoldCase, ...]:
    try:
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
        requirements = payload.get("chain_requirements", ())
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError("gold contract has an invalid JSON shape") from exc
    _validate_gold(cases, requirements)
    return cases


def load_coverage_adjudications(
    path: Path,
    *,
    core_gold: tuple[GoldCase, ...],
) -> tuple[CoverageAdjudication, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise BenchmarkContractError("coverage contract must be a JSON object")
        if payload.get("benchmark") != COVERAGE_BENCHMARK:
            raise BenchmarkContractError("coverage contract benchmark name is invalid")
        if payload.get("schema_version") != COVERAGE_SCHEMA_VERSION:
            raise BenchmarkContractError("coverage contract schema_version is unsupported")
        raw_adjudications = payload.get("adjudications")
        if not isinstance(raw_adjudications, list):
            raise BenchmarkContractError("coverage adjudications must be a list")
        adjudications = tuple(
            CoverageAdjudication(
                id=item["id"],
                source_id=item["source_id"],
                page_a=item["page_a"],
                page_b=item["page_b"],
                truth=item["truth"],
                family=item["family"],
                rationale=item["rationale"],
                review_method=item["review_method"],
            )
            for item in raw_adjudications
        )
    except BenchmarkContractError:
        raise
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError("coverage contract has an invalid JSON shape") from exc
    _validate_coverage_adjudications(adjudications, core_gold)
    return adjudications


def evaluate_coverage(
    adjudications: tuple[CoverageAdjudication, ...],
    predicted: set[tuple[str, int, int]],
) -> CoverageMetrics:
    _validate_coverage_adjudication_identity(adjudications)
    adjudicated_keys = {item.key for item in adjudications}
    currently_predicted = predicted & adjudicated_keys
    true_keys = {item.key for item in adjudications if item.truth == CONTINUES}
    false_keys = {item.key for item in adjudications if item.truth == NOT_CONTINUES}
    confirmed_true = currently_predicted & true_keys
    confirmed_false = currently_predicted & false_keys
    not_currently_predicted = adjudicated_keys - predicted
    return CoverageMetrics(
        adjudicated_count=len(adjudications),
        currently_predicted_adjudicated_count=len(currently_predicted),
        confirmed_true_continuation_count=len(confirmed_true),
        confirmed_false_continuation_count=len(confirmed_false),
        adjudicated_not_currently_predicted_count=len(not_currently_predicted),
        zero_confirmed_false_continuation_gate=not confirmed_false,
    )


def classify_predictions(
    predicted: set[tuple[str, int, int]],
    core_gold: tuple[GoldCase, ...],
    coverage_adjudications: tuple[CoverageAdjudication, ...],
) -> PredictionClassification:
    core_keys = {case.key for case in core_gold}
    coverage_keys = {item.key for item in coverage_adjudications}
    overlap = core_keys & coverage_keys
    if overlap:
        raise BenchmarkContractError(
            f"core gold and coverage ledger overlap on page pairs: {sorted(overlap)!r}"
        )
    return PredictionClassification(
        core=frozenset(predicted & core_keys),
        coverage=frozenset(predicted & coverage_keys),
        unknown=frozenset(predicted - core_keys - coverage_keys),
    )


def _validate_coverage_adjudications(
    adjudications: tuple[CoverageAdjudication, ...],
    core_gold: tuple[GoldCase, ...],
) -> None:
    _validate_coverage_adjudication_identity(adjudications)
    core_keys = {case.key for case in core_gold}
    coverage_keys = {item.key for item in adjudications}
    overlap = core_keys & coverage_keys
    if overlap:
        raise BenchmarkContractError(
            f"coverage ledger overlaps core gold page pairs: {sorted(overlap)!r}"
        )


def _validate_coverage_adjudication_identity(
    adjudications: tuple[CoverageAdjudication, ...],
) -> None:
    for item in adjudications:
        if (
            not isinstance(item.id, str)
            or not item.id.strip()
            or not isinstance(item.source_id, str)
            or not item.source_id.strip()
            or not isinstance(item.page_a, int)
            or isinstance(item.page_a, bool)
            or not isinstance(item.page_b, int)
            or isinstance(item.page_b, bool)
            or not isinstance(item.truth, str)
            or not isinstance(item.family, str)
            or not item.family.strip()
            or not isinstance(item.rationale, str)
            or not item.rationale.strip()
            or not isinstance(item.review_method, str)
            or not item.review_method.strip()
        ):
            raise BenchmarkContractError(
                "coverage adjudication identity, truth, and review fields are invalid"
            )
        if item.page_b != item.page_a + 1:
            raise BenchmarkContractError(
                f"coverage adjudication {item.id!r} must use adjacent page pairs"
            )
        if item.truth not in {CONTINUES, NOT_CONTINUES}:
            raise BenchmarkContractError(
                f"coverage adjudication {item.id!r} has invalid truth"
            )
    ids = [item.id for item in adjudications]
    if len(ids) != len(set(ids)):
        raise BenchmarkContractError("coverage adjudication ids must be unique")
    keys = [item.key for item in adjudications]
    if len(keys) != len(set(keys)):
        raise BenchmarkContractError("coverage adjudication page-pair keys must be unique")


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
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
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
    if any(
        not isinstance(case.id, str)
        or not case.id.strip()
        or not isinstance(case.source_id, str)
        or not case.source_id.strip()
        or not isinstance(case.page_a, int)
        or isinstance(case.page_a, bool)
        or not isinstance(case.page_b, int)
        or isinstance(case.page_b, bool)
        or not isinstance(case.truth, str)
        for case in cases
    ):
        raise BenchmarkContractError("gold case identity and page fields have invalid types")
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkContractError("gold case ids must be unique")
    case_keys = [case.key for case in cases]
    if len(case_keys) != len(set(case_keys)):
        raise BenchmarkContractError("gold continuation case keys must be unique")
    if any(case.page_b != case.page_a + 1 for case in cases):
        raise BenchmarkContractError("all gold cases must be adjacent page pairs")
    if any(case.truth not in {"CONTINUES", "NOT_CONTINUES"} for case in cases):
        raise BenchmarkContractError("gold truth must be CONTINUES or NOT_CONTINUES")
    if not any(case.truth == "CONTINUES" for case in cases):
        raise BenchmarkContractError("gold must contain at least one positive continuation")
    if not any(case.truth == "NOT_CONTINUES" for case in cases):
        raise BenchmarkContractError("gold must contain at least one hard negative")
    if not isinstance(requirements, list):
        raise BenchmarkContractError("chain_requirements must be a list")
    chain_by_id = _validate_chain_requirements(requirements)
    if not any(item["contains_three_page_chain"] for item in chain_by_id.values()):
        raise BenchmarkContractError("gold must require a three-page continuation chain")
    gold_by_key = {case.key: case for case in cases}
    for case in cases:
        if case.chain_id is None:
            continue
        if not isinstance(case.chain_id, str) or not case.chain_id.strip():
            raise BenchmarkContractError("gold case chain_id must be a non-empty string")
        requirement = chain_by_id.get(case.chain_id)
        if requirement is None:
            raise BenchmarkContractError(
                f"gold case {case.id!r} references an unknown chain_id {case.chain_id!r}"
            )
        expected_edges = {
            (requirement["source_id"], page, page + 1)
            for page in requirement["pages"][:-1]
        }
        if case.key not in expected_edges:
            raise BenchmarkContractError(
                f"gold case {case.id!r} is outside its required chain {case.chain_id!r}"
            )
    for chain_id, requirement in chain_by_id.items():
        expected_edges = {
            (requirement["source_id"], page, page + 1)
            for page in requirement["pages"][:-1]
        }
        for key in expected_edges:
            case = gold_by_key.get(key)
            if case is None:
                raise BenchmarkContractError(
                    f"required chain {chain_id!r} is missing gold edge {key!r}"
                )
            if case.truth != "CONTINUES":
                raise BenchmarkContractError(
                    f"required chain {chain_id!r} edge {key!r} must be CONTINUES"
                )
            if case.chain_id != chain_id:
                raise BenchmarkContractError(
                    f"gold edge {key!r} must carry chain_id {chain_id!r}"
                )


def _validate_chain_requirements(
    requirements: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    chain_by_id: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise BenchmarkContractError("each chain requirement must be an object")
        chain_id = requirement.get("chain_id")
        source_id = requirement.get("source_id")
        pages = requirement.get("pages")
        required_count = requirement.get("required_positive_edge_count")
        contains_three_page_chain = requirement.get("contains_three_page_chain")
        if not isinstance(chain_id, str) or not chain_id.strip():
            raise BenchmarkContractError("chain_id must be a non-empty string")
        if chain_id in chain_by_id:
            raise BenchmarkContractError("chain requirement ids must be unique")
        if not isinstance(source_id, str) or not source_id.strip():
            raise BenchmarkContractError("chain source_id must be a non-empty string")
        if not isinstance(pages, list) or any(
            not isinstance(page, int) or isinstance(page, bool) for page in pages
        ):
            raise BenchmarkContractError("chain pages must be a list of integers")
        if len(pages) < 2:
            raise BenchmarkContractError("chain pages must contain at least two pages")
        if len(pages) != len(set(pages)):
            raise BenchmarkContractError("chain pages must not contain duplicates")
        if pages != sorted(pages):
            raise BenchmarkContractError("chain pages must be strictly ascending")
        if any(right != left + 1 for left, right in pairwise(pages)):
            raise BenchmarkContractError("chain pages must be contiguous")
        if not isinstance(contains_three_page_chain, bool):
            raise BenchmarkContractError("contains_three_page_chain must be boolean")
        if contains_three_page_chain and len(pages) < 3:
            raise BenchmarkContractError(
                "a three-page chain requirement must contain at least three pages"
            )
        if not isinstance(required_count, int) or isinstance(required_count, bool):
            raise BenchmarkContractError("required_positive_edge_count must be an integer")
        if required_count != len(pages) - 1:
            raise BenchmarkContractError(
                "required_positive_edge_count must equal chain edge count"
            )
        chain_by_id[chain_id] = requirement
    return chain_by_id


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
