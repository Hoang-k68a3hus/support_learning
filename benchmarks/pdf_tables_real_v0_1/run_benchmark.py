from __future__ import annotations

from dataclasses import asdict
import argparse
import json
from pathlib import Path

from benchmarks.pdf_tables_real_v0_1._corpus import (
    download_source,
    load_sources,
    sha256_hex,
)
from benchmarks.pdf_tables_real_v0_1.audit import audit_missed_table_failures
from benchmarks.pdf_tables_real_v0_1.evaluate import (
    PagePrediction,
    TablePrediction,
    evaluate,
    load_gold_cases,
)
from source_understanding.adapters import PdfAdapter
from source_understanding.source_attributes import INTEGRITY_GROUP_ID_ATTRIBUTE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--enforce-capability-gate",
        action="store_true",
        help="return non-zero when a non-OBSERVE capability contract fails",
    )
    args = parser.parse_args()

    sources = load_sources()
    gold = load_gold_cases()
    gold_pages_by_source: dict[str, set[int]] = {}
    for case in gold:
        gold_pages_by_source.setdefault(case.source_id, set()).add(case.page)

    predictions: list[PagePrediction] = []
    source_reports: list[dict[str, object]] = []
    for source in sources:
        payload = download_source(source)
        adapted = PdfAdapter().adapt(payload, source_name=source.file_name)
        pages = gold_pages_by_source.get(source.id, set())
        for page in sorted(pages):
            predictions.append(_prediction_from_raw(source.id, page, adapted.raw_elements))
        source_reports.append(
            {
                "source_id": source.id,
                "bytes": len(payload),
                "sha256": sha256_hex(payload),
                "diagnostic_codes": sorted({item.code for item in adapted.diagnostics}),
                "table_diagnostics": [
                    {
                        "code": item.code,
                        "part": item.part,
                        "metadata": item.metadata,
                    }
                    for item in adapted.diagnostics
                    if item.code.startswith("PDF_TABLE_")
                ],
            }
        )

    result = evaluate(gold, predictions)
    missed_cases = _known_count_missed_cases(gold, predictions)
    failure_audit = audit_missed_table_failures(missed_cases, source_reports)
    report = {
        "benchmark": "pdf_tables_real_v0_1",
        "source_reports": source_reports,
        "predictions": [asdict(item) for item in predictions],
        "result": asdict(result),
        "m2_3_failure_audit": failure_audit,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.enforce_capability_gate and not result.quality_gate_passed:
        return 2
    return 0


def _known_count_missed_cases(gold_cases, predictions) -> tuple[tuple[str, int], ...]:
    predicted_by_key = {
        (item.source_id, item.page): len(item.tables)
        for item in predictions
    }
    missed: list[tuple[str, int]] = []
    for case in gold_cases:
        expected = case.source_truth_table_count
        if expected is None:
            continue
        actual = predicted_by_key.get((case.source_id, case.page), 0)
        if actual < expected:
            missed.append((case.source_id, case.page))
    return tuple(missed)


def _prediction_from_raw(source_id: str, page: int, raw_elements) -> PagePrediction:
    tables_by_group: dict[str, dict[str, object]] = {}
    for element in raw_elements:
        if element.location is None or element.location.page != page:
            continue
        group_id = element.attributes.get(INTEGRITY_GROUP_ID_ATTRIBUTE)
        if not isinstance(group_id, str) or not group_id.startswith("pdf-table:"):
            continue
        bucket = tables_by_group.setdefault(group_id, {"table": None, "cells": {}})
        if element.type_hint == "TABLE":
            bucket["table"] = element
        elif element.type_hint == "TABLE_CELL":
            key = (int(element.attributes["row_index"]), int(element.attributes["cell_index"]))
            bucket["cells"][key] = element.text or ""

    tables: list[TablePrediction] = []
    for group_id in sorted(tables_by_group, key=_group_sort_key):
        bucket = tables_by_group[group_id]
        table = bucket["table"]
        if table is None:
            raise ValueError(f"table integrity group has no TABLE container: {group_id}")
        row_count = int(table.attributes["row_count"])
        column_count = int(table.attributes["column_count"])
        cells = bucket["cells"]
        matrix = tuple(
            tuple(str(cells.get((row, column), "")) for column in range(column_count))
            for row in range(row_count)
        )
        tables.append(
            TablePrediction(
                row_count=row_count,
                column_count=column_count,
                cells=matrix,
            )
        )
    return PagePrediction(source_id=source_id, page=page, tables=tuple(tables))


def _group_sort_key(group_id: str) -> tuple[int, int, str]:
    try:
        _prefix, page_part, table_part = group_id.split(":", 2)
        return int(page_part.removeprefix("p")), int(table_part.removeprefix("t")), group_id
    except (ValueError, TypeError):
        return 2**31 - 1, 2**31 - 1, group_id


if __name__ == "__main__":
    raise SystemExit(main())
