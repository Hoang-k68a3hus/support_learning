from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parent
_ALLOWED_CAPABILITIES = {
    "OBSERVE",
    "SUPPORTED_REQUIRED",
    "MUST_PRESERVE_UNSTRUCTURED",
}
_ALLOWED_SPAN_KINDS = {"ROW_SPAN", "COLUMN_SPAN"}


@dataclass(frozen=True, slots=True)
class CellAnchor:
    row: int
    column: int
    text: str


@dataclass(frozen=True, slots=True)
class CellSpanPrediction:
    row: int
    column: int
    row_span: int
    column_span: int


@dataclass(frozen=True, slots=True)
class TableContract:
    row_count: int
    column_count: int
    anchors: tuple[CellAnchor, ...] = ()
    required_span_kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldCase:
    source_id: str
    page: int
    source_truth_table_count: int | None
    capability_expectation: str
    oracle_evidence: str
    tables: tuple[TableContract, ...]


@dataclass(frozen=True, slots=True)
class TablePrediction:
    row_count: int
    column_count: int
    cells: tuple[tuple[str, ...], ...]
    spans: tuple[CellSpanPrediction, ...] = ()

    def cell(self, row: int, column: int) -> str | None:
        if row < 0 or column < 0 or row >= len(self.cells):
            return None
        current = self.cells[row]
        if column >= len(current):
            return None
        return current[column]


@dataclass(frozen=True, slots=True)
class PagePrediction:
    source_id: str
    page: int
    tables: tuple[TablePrediction, ...]


@dataclass(frozen=True, slots=True)
class CaseResult:
    source_id: str
    page: int
    source_truth_table_count: int | None
    predicted_table_count: int
    capability_expectation: str
    structural_contracts: int
    structural_matches: int
    source_truth_count_match: bool | None
    capability_passed: bool | None


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    cases: tuple[CaseResult, ...]
    known_count_cases: int
    known_count_expected_tables: int
    known_count_predicted_tables: int
    known_count_false_positive_tables: int
    known_count_missed_source_truth_tables: int
    known_count_source_truth_precision: float
    known_count_source_truth_recall: float
    structural_contracts: int
    structural_matches: int
    capability_checked_cases: int
    capability_passed_cases: int
    quality_gate_passed: bool


def load_gold_cases() -> tuple[GoldCase, ...]:
    payload = json.loads((_ROOT / "gold_contracts.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported real-PDF gold schema")
    cases = tuple(_parse_case(item) for item in payload["cases"])
    identities = [(item.source_id, item.page) for item in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate source/page in real-PDF gold")
    return cases


def evaluate(
    gold_cases: Iterable[GoldCase],
    predictions: Iterable[PagePrediction],
) -> BenchmarkResult:
    gold = tuple(gold_cases)
    predicted = tuple(predictions)
    predicted_by_key = {(item.source_id, item.page): item for item in predicted}
    if len(predicted_by_key) != len(predicted):
        raise ValueError("duplicate source/page prediction")

    known_count_cases = 0
    expected_tables = 0
    predicted_tables = 0
    false_positive_tables = 0
    missed_tables = 0
    true_positive_tables = 0
    structural_contracts = 0
    structural_matches = 0
    checked = 0
    passed = 0
    results: list[CaseResult] = []

    gold_keys = {(item.source_id, item.page) for item in gold}
    unknown = sorted(set(predicted_by_key) - gold_keys)
    if unknown:
        raise ValueError(f"prediction outside gold scope: {unknown}")

    for case in gold:
        prediction = predicted_by_key.get(
            (case.source_id, case.page),
            PagePrediction(source_id=case.source_id, page=case.page, tables=()),
        )
        actual_count = len(prediction.tables)
        if case.source_truth_table_count is None:
            count_match = None
        else:
            expected_count = case.source_truth_table_count
            count_match = actual_count == expected_count
            known_count_cases += 1
            expected_tables += expected_count
            predicted_tables += actual_count
            false_positive_tables += max(0, actual_count - expected_count)
            missed_tables += max(0, expected_count - actual_count)
            true_positive_tables += min(actual_count, expected_count)

        matched = _match_structural_contracts(case.tables, prediction.tables)
        structural_contracts += len(case.tables)
        structural_matches += matched

        capability_passed: bool | None
        if case.capability_expectation == "OBSERVE":
            capability_passed = None
        elif case.capability_expectation == "SUPPORTED_REQUIRED":
            has_oracle = case.source_truth_table_count is not None or bool(case.tables)
            capability_passed = (
                has_oracle
                and matched == len(case.tables)
                and count_match is not False
            )
        else:
            capability_passed = actual_count == 0
        if capability_passed is not None:
            checked += 1
            if capability_passed:
                passed += 1

        results.append(
            CaseResult(
                source_id=case.source_id,
                page=case.page,
                source_truth_table_count=case.source_truth_table_count,
                predicted_table_count=actual_count,
                capability_expectation=case.capability_expectation,
                structural_contracts=len(case.tables),
                structural_matches=matched,
                source_truth_count_match=count_match,
                capability_passed=capability_passed,
            )
        )

    precision = (
        true_positive_tables / predicted_tables
        if predicted_tables
        else (1.0 if not expected_tables else 0.0)
    )
    recall = true_positive_tables / expected_tables if expected_tables else 1.0
    quality_gate = checked > 0 and checked == passed
    return BenchmarkResult(
        cases=tuple(results),
        known_count_cases=known_count_cases,
        known_count_expected_tables=expected_tables,
        known_count_predicted_tables=predicted_tables,
        known_count_false_positive_tables=false_positive_tables,
        known_count_missed_source_truth_tables=missed_tables,
        known_count_source_truth_precision=precision,
        known_count_source_truth_recall=recall,
        structural_contracts=structural_contracts,
        structural_matches=structural_matches,
        capability_checked_cases=checked,
        capability_passed_cases=passed,
        quality_gate_passed=quality_gate,
    )


def _parse_case(value: dict[str, object]) -> GoldCase:
    capability = str(value["capability_expectation"])
    if capability not in _ALLOWED_CAPABILITIES:
        raise ValueError(f"unsupported capability expectation: {capability}")
    raw_count = value.get("source_truth_table_count")
    count = None if raw_count is None else int(raw_count)
    if count is not None and count < 0:
        raise ValueError("source-truth table count cannot be negative")
    tables = tuple(_parse_table(item) for item in value.get("tables", []))
    if count is not None and len(tables) > count:
        raise ValueError("structural table contracts exceed source-truth table count")
    if capability == "SUPPORTED_REQUIRED" and count is None and not tables:
        raise ValueError("SUPPORTED_REQUIRED needs a count or structural oracle")
    oracle_evidence = str(value["oracle_evidence"])
    if not oracle_evidence.strip():
        raise ValueError("gold case requires oracle evidence")
    return GoldCase(
        source_id=str(value["source_id"]),
        page=int(value["page"]),
        source_truth_table_count=count,
        capability_expectation=capability,
        oracle_evidence=oracle_evidence,
        tables=tables,
    )


def _parse_table(value: dict[str, object]) -> TableContract:
    anchors = tuple(
        CellAnchor(row=int(item["row"]), column=int(item["column"]), text=str(item["text"]))
        for item in value.get("anchors", [])
    )
    raw_span_kinds = tuple(str(item) for item in value.get("required_span_kinds", []))
    if len(raw_span_kinds) != len(set(raw_span_kinds)):
        raise ValueError("duplicate required table span kind")
    unsupported = sorted(set(raw_span_kinds) - _ALLOWED_SPAN_KINDS)
    if unsupported:
        raise ValueError(f"unsupported required table span kinds: {unsupported}")
    contract = TableContract(
        row_count=int(value["row_count"]),
        column_count=int(value["column_count"]),
        anchors=anchors,
        required_span_kinds=tuple(sorted(raw_span_kinds)),
    )
    if contract.row_count <= 0 or contract.column_count <= 0:
        raise ValueError("table shape must be positive")
    for anchor in anchors:
        if not (0 <= anchor.row < contract.row_count and 0 <= anchor.column < contract.column_count):
            raise ValueError("cell anchor outside table shape")
    return contract


def _match_structural_contracts(
    contracts: tuple[TableContract, ...],
    predictions: tuple[TablePrediction, ...],
) -> int:
    unused = set(range(len(predictions)))
    matched = 0
    for contract in contracts:
        match_index = next(
            (
                index
                for index in sorted(unused)
                if _table_matches(contract, predictions[index])
            ),
            None,
        )
        if match_index is None:
            continue
        unused.remove(match_index)
        matched += 1
    return matched


def _table_matches(contract: TableContract, prediction: TablePrediction) -> bool:
    if (contract.row_count, contract.column_count) != (
        prediction.row_count,
        prediction.column_count,
    ):
        return False
    if any(not _valid_prediction_span(prediction, item) for item in prediction.spans):
        return False
    if not all(
        prediction.cell(anchor.row, anchor.column) == anchor.text
        for anchor in contract.anchors
    ):
        return False
    return all(
        _prediction_has_span_kind(prediction, kind)
        for kind in contract.required_span_kinds
    )


def _valid_prediction_span(
    prediction: TablePrediction,
    span: CellSpanPrediction,
) -> bool:
    values = (span.row, span.column, span.row_span, span.column_span)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        return False
    if span.row < 0 or span.column < 0 or span.row_span <= 0 or span.column_span <= 0:
        return False
    return (
        span.row + span.row_span <= prediction.row_count
        and span.column + span.column_span <= prediction.column_count
        and (span.row_span > 1 or span.column_span > 1)
    )


def _prediction_has_span_kind(prediction: TablePrediction, kind: str) -> bool:
    if kind == "ROW_SPAN":
        return any(item.row_span > 1 for item in prediction.spans)
    if kind == "COLUMN_SPAN":
        return any(item.column_span > 1 for item in prediction.spans)
    return False
