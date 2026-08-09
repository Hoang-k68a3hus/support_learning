from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)

from .discover import FIXED_EVALUATION_TIME, SOURCES, _download


HERE = Path(__file__).resolve().parent
LEVELS = (
    "L0_source_fidelity",
    "L1_element_understanding",
    "L2_structural_grouping",
    "L3_document_structure",
)


def _load_documents(file_name: str) -> dict[str, dict[str, object]]:
    payload = json.loads((HERE / file_name).read_text(encoding="utf-8"))
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError(f"{file_name} must contain a documents list")
    output: dict[str, dict[str, object]] = {}
    for item in documents:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuntimeError(f"{file_name} contains an invalid document record")
        document_id = item["id"]
        if document_id in output:
            raise RuntimeError(f"{file_name} contains duplicate document id {document_id!r}")
        output[document_id] = item
    return output


def _load_gold_payload() -> dict[str, object]:
    payload = json.loads((HERE / "gold_contracts.json").read_text(encoding="utf-8"))
    if payload.get("version") != "0.1":
        raise RuntimeError("unsupported real DOCX gold contract version")
    return payload


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _predicted_headings(raw_elements: tuple[object, ...]) -> Counter[tuple[str, int]]:
    output: Counter[tuple[str, int]] = Counter()
    for item in raw_elements:
        if getattr(item, "type_hint", None) != "HEADING":
            continue
        attrs = getattr(item, "attributes", {})
        if attrs.get(SOURCE_ZONE_ATTRIBUTE) != "body":
            continue
        level = attrs.get(HEADING_LEVEL_ATTRIBUTE)
        if isinstance(level, int):
            output[(_normalize_text(getattr(item, "text", None)), level)] += 1
    return output


def _gold_headings(contract: dict[str, object]) -> Counter[tuple[str, int]]:
    output: Counter[tuple[str, int]] = Counter()
    for item in contract["L1_element_understanding"]["headings"]:
        output[(_normalize_text(item.get("text")), int(item["level"]))] += int(item.get("count", 1))
    return output


def _predicted_navigation(
    raw_elements: tuple[object, ...],
) -> Counter[tuple[str, str, str]]:
    output: Counter[tuple[str, str, str]] = Counter()
    for item in raw_elements:
        attrs = getattr(item, "attributes", {})
        if attrs.get(SOURCE_ZONE_ATTRIBUTE) != "body":
            continue
        role = attrs.get("docx_navigation_role")
        style_id = attrs.get("paragraph_style_id")
        if isinstance(role, str) and isinstance(style_id, str):
            output[(_normalize_text(getattr(item, "text", None)), role, style_id)] += 1
    return output


def _gold_navigation(contract: dict[str, object]) -> Counter[tuple[str, str, str]]:
    output: Counter[tuple[str, str, str]] = Counter()
    for item in contract["L1_element_understanding"].get("navigation", []):
        output[
            (
                _normalize_text(item.get("text")),
                str(item["role"]),
                str(item["style_id"]),
            )
        ] += int(item.get("count", 1))
    return output


def _predicted_note_counts(raw_elements: tuple[object, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in raw_elements:
        anchor = getattr(item, "attributes", {}).get(SOURCE_ANCHOR_ATTRIBUTE)
        if not isinstance(anchor, dict):
            continue
        kind = anchor.get("kind")
        if isinstance(kind, str):
            counts[kind] += 1
    return counts


def _predicted_table_aggregate(raw_elements: tuple[object, ...]) -> dict[str, int]:
    counts = Counter(
        getattr(item, "type_hint", None)
        for item in raw_elements
        if getattr(item, "attributes", {}).get(SOURCE_ZONE_ATTRIBUTE) == "body"
    )
    return {
        key: int(counts.get(key, 0))
        for key in ("TABLE", "TABLE_ROW", "TABLE_CELL")
    }


def _predicted_story_part_count(raw_elements: tuple[object, ...]) -> int:
    parts = {
        attrs.get("opc_part")
        for item in raw_elements
        if (attrs := getattr(item, "attributes", {})).get(SOURCE_ZONE_ATTRIBUTE)
        in {"header", "footer"}
        and isinstance(attrs.get("opc_part"), str)
    }
    return len(parts)


def _candidate_elements(
    raw_elements: tuple[object, ...],
    target_texts: set[str],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for item in raw_elements:
        text = _normalize_text(getattr(item, "text", None))
        if text not in target_texts:
            continue
        attrs = dict(getattr(item, "attributes", {}))
        output.append(
            {
                "text": text,
                "type_hint": getattr(item, "type_hint", None),
                "paragraph_style_id": attrs.get("paragraph_style_id"),
                "paragraph_style_name": attrs.get("paragraph_style_name"),
                "heading_level": attrs.get(HEADING_LEVEL_ATTRIBUTE),
                "docx_navigation_role": attrs.get("docx_navigation_role"),
                "docx_outline_level": attrs.get("docx_outline_level"),
                "source_zone": attrs.get(SOURCE_ZONE_ATTRIBUTE),
            }
        )
    return output


def _level_record(status: str) -> dict[str, object]:
    return {"status": status, "errors": []}


def evaluate_source(
    source: dict[str, str],
    pin: dict[str, object],
    contract: dict[str, object],
) -> dict[str, object]:
    levels = {
        "L0_source_fidelity": _level_record("FROZEN_PARTIAL"),
        "L1_element_understanding": _level_record("FROZEN_PARTIAL"),
        "L2_structural_grouping": _level_record(
            str(contract["L2_structural_grouping"].get("status", "NOT_YET_FULLY_ADJUDICATED"))
        ),
        "L3_document_structure": _level_record(
            str(contract["L3_document_structure"].get("status", "PARTIAL"))
        ),
    }
    l0 = levels["L0_source_fidelity"]["errors"]
    l1 = levels["L1_element_understanding"]["errors"]
    l3 = levels["L3_document_structure"]["errors"]

    payload = _download(source["url"])
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    expected_bytes = int(contract["bytes"])
    expected_digest = str(contract["sha256"])
    if pin.get("bytes") != expected_bytes or pin.get("sha256") != expected_digest:
        l0.append(
            {
                "type": "PIN_GOLD_REVISION_DISAGREEMENT",
                "source_pin": {"bytes": pin.get("bytes"), "sha256": pin.get("sha256")},
                "frozen_gold": {"bytes": expected_bytes, "sha256": expected_digest},
            }
        )
    if digest != expected_digest or len(payload) != expected_bytes:
        l0.append(
            {
                "type": "SOURCE_REVISION_MISMATCH",
                "expected_sha256": expected_digest,
                "actual_sha256": digest,
                "expected_bytes": expected_bytes,
                "actual_bytes": len(payload),
            }
        )

    adapter = DocxAdapter()
    adapted = adapter.adapt(payload, source_name=source["file_name"])
    result = SourceAdapterRunner().understand_bytes(
        payload,
        adapter=adapter,
        document_id=source["id"],
        source_name=source["file_name"],
        processed_at=FIXED_EVALUATION_TIME,
    )

    gold_l0 = contract["L0_source_fidelity"]
    expected_tables = {
        key: int(value) for key, value in gold_l0["table_aggregate"].items()
    }
    predicted_tables = _predicted_table_aggregate(adapted.raw_elements)
    if expected_tables != predicted_tables:
        l0.append(
            {
                "type": "TABLE_AGGREGATE_MISMATCH",
                "expected": expected_tables,
                "actual": predicted_tables,
            }
        )

    expected_notes = Counter(
        {key: int(value) for key, value in gold_l0.get("notes", {}).items()}
    )
    predicted_notes = _predicted_note_counts(adapted.raw_elements)
    for kind in sorted(set(expected_notes) | set(predicted_notes)):
        if predicted_notes.get(kind, 0) != expected_notes.get(kind, 0):
            l0.append(
                {
                    "type": "NOTE_COUNT_MISMATCH",
                    "kind": kind,
                    "expected": expected_notes.get(kind, 0),
                    "actual": predicted_notes.get(kind, 0),
                }
            )

    expected_story_parts = int(gold_l0.get("referenced_story_parts", 0))
    predicted_story_parts = _predicted_story_part_count(adapted.raw_elements)
    if expected_story_parts != predicted_story_parts:
        l0.append(
            {
                "type": "REFERENCED_STORY_COUNT_MISMATCH",
                "expected": expected_story_parts,
                "actual": predicted_story_parts,
            }
        )

    expected_duplicate_groups = int(gold_l0.get("duplicate_style_groups", 0))
    predicted_duplicate_diagnostics = sum(
        1
        for item in adapted.diagnostics
        if item.code == "COMPATIBLE_DUPLICATE_STYLE_MERGED"
    )
    if expected_duplicate_groups != predicted_duplicate_diagnostics:
        l0.append(
            {
                "type": "DUPLICATE_STYLE_DIAGNOSTIC_MISMATCH",
                "expected_groups": expected_duplicate_groups,
                "actual_diagnostics": predicted_duplicate_diagnostics,
            }
        )

    structural_diagnostics = [
        item.code for item in adapted.diagnostics if item.affects_structural_completeness
    ]
    expected_structural_diagnostic_count = int(
        gold_l0.get("unexpected_structural_diagnostic_count", 0)
    )
    if len(structural_diagnostics) != expected_structural_diagnostic_count:
        l0.append(
            {
                "type": "STRUCTURAL_ADAPTER_DIAGNOSTIC_COUNT_MISMATCH",
                "expected": expected_structural_diagnostic_count,
                "actual": len(structural_diagnostics),
                "codes": structural_diagnostics,
            }
        )

    expected_headings = _gold_headings(contract)
    predicted_headings = _predicted_headings(adapted.raw_elements)
    if expected_headings != predicted_headings:
        missing = expected_headings - predicted_headings
        extra = predicted_headings - expected_headings
        texts = {text for text, _ in missing} | {text for text, _ in extra}
        l1.append(
            {
                "type": "HEADING_CONTRACT_MISMATCH",
                "missing": list(missing.elements()),
                "extra": list(extra.elements()),
                "candidate_elements": _candidate_elements(adapted.raw_elements, texts),
            }
        )

    expected_navigation = _gold_navigation(contract)
    predicted_navigation = _predicted_navigation(adapted.raw_elements)
    if expected_navigation != predicted_navigation:
        missing = expected_navigation - predicted_navigation
        extra = predicted_navigation - expected_navigation
        texts = {text for text, _, _ in missing} | {text for text, _, _ in extra}
        l1.append(
            {
                "type": "NAVIGATION_CONTRACT_MISMATCH",
                "missing": list(missing.elements()),
                "extra": list(extra.elements()),
                "candidate_elements": _candidate_elements(adapted.raw_elements, texts),
            }
        )

    expected_structural_ready = bool(
        contract["L3_document_structure"].get("structural_ready", True)
    )
    actual_structural_ready = result.understanding.completion_report.structural_ready
    if actual_structural_ready != expected_structural_ready:
        l3.append(
            {
                "type": "STRUCTURAL_READY_MISMATCH",
                "expected": expected_structural_ready,
                "actual": actual_structural_ready,
            }
        )

    error_count = sum(len(levels[level]["errors"]) for level in LEVELS)
    return {
        "id": source["id"],
        "sha256": digest,
        "bytes": len(payload),
        "levels": levels,
        "prediction": {
            "adapter_version": adapted.adapter_version,
            "element_count": len(adapted.raw_elements),
            "heading_count": sum(predicted_headings.values()),
            "navigation_count": sum(predicted_navigation.values()),
            "table_aggregate": predicted_tables,
            "note_counts": dict(predicted_notes),
            "referenced_story_parts": predicted_story_parts,
            "structure_mode": result.understanding.document.structure.mode.value,
            "structural_ready": actual_structural_ready,
            "adapter_diagnostic_codes": [item.code for item in adapted.diagnostics],
        },
        "error_count": error_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    pins = _load_documents("sources.json")
    gold_payload = _load_gold_payload()
    gold = {
        item["id"]: item
        for item in gold_payload["documents"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    source_ids = {source["id"] for source in SOURCES}
    if source_ids != set(pins) or source_ids != set(gold):
        raise RuntimeError(
            "real DOCX source, pin, and frozen-gold document sets must match exactly"
        )

    documents = [
        evaluate_source(source, pins[source["id"]], gold[source["id"]])
        for source in SOURCES
    ]
    errors_by_level = {
        level: sum(len(document["levels"][level]["errors"]) for document in documents)
        for level in LEVELS
    }
    error_count = sum(errors_by_level.values())
    report = {
        "benchmark": gold_payload["benchmark"],
        "version": gold_payload["version"],
        "gold_provenance": gold_payload["gold_provenance"],
        "coverage": gold_payload["policy"]["coverage"],
        "documents": documents,
        "document_count": len(documents),
        "errors_by_level": errors_by_level,
        "error_count": error_count,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    if args.fail_on_error and error_count:
        raise SystemExit(f"real DOCX benchmark found {error_count} frozen-contract error(s)")


if __name__ == "__main__":
    main()
