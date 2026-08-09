from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)

from .discover import FIXED_EVALUATION_TIME, SOURCES, _download
from .source_audit import audit_source


HERE = Path(__file__).resolve().parent


def _load_pins() -> dict[str, dict[str, object]]:
    payload = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    return {item["id"]: item for item in payload["documents"]}


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _predicted_table_shapes(raw_elements: tuple[object, ...]) -> Counter[tuple[int, int]]:
    rows: dict[str, set[int]] = defaultdict(set)
    cells: dict[str, set[tuple[int, int]]] = defaultdict(set)
    table_groups: set[str] = set()
    for item in raw_elements:
        attrs = getattr(item, "attributes", {})
        if attrs.get(SOURCE_ZONE_ATTRIBUTE) != "body":
            continue
        group = attrs.get(INTEGRITY_GROUP_ID_ATTRIBUTE)
        if not isinstance(group, str):
            continue
        type_hint = getattr(item, "type_hint", None)
        if type_hint == "TABLE":
            table_groups.add(group)
        elif type_hint == "TABLE_ROW":
            row_index = attrs.get("row_index")
            if isinstance(row_index, int):
                rows[group].add(row_index)
        elif type_hint == "TABLE_CELL":
            row_index = attrs.get("row_index")
            cell_index = attrs.get("cell_index")
            if isinstance(row_index, int) and isinstance(cell_index, int):
                cells[group].add((row_index, cell_index))
    return Counter((len(rows[group]), len(cells[group])) for group in table_groups)


def _expected_table_shapes(audit: dict[str, object]) -> Counter[tuple[int, int]]:
    body = audit["body"]
    return Counter((int(item["rows"]), int(item["cells"])) for item in body["tables"])


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


def _expected_headings(audit: dict[str, object]) -> Counter[tuple[str, int]]:
    output: Counter[tuple[str, int]] = Counter()
    for item in audit["body"]["headings"]:
        level = item["heading_level"]
        if isinstance(level, int):
            output[(_normalize_text(item["text"]), level)] += 1
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


def _candidate_elements_for_missing_headings(
    raw_elements: tuple[object, ...], missing: Counter[tuple[str, int]]
) -> list[dict[str, object]]:
    missing_text = {text for text, _ in missing}
    output: list[dict[str, object]] = []
    for item in raw_elements:
        text = _normalize_text(getattr(item, "text", None))
        if text not in missing_text:
            continue
        attrs = dict(getattr(item, "attributes", {}))
        output.append(
            {
                "text": text,
                "type_hint": getattr(item, "type_hint", None),
                "paragraph_style_id": attrs.get("paragraph_style_id"),
                "paragraph_style_name": attrs.get("paragraph_style_name"),
                "heading_level": attrs.get(HEADING_LEVEL_ATTRIBUTE),
                "source_zone": attrs.get(SOURCE_ZONE_ATTRIBUTE),
                "numbering_id": attrs.get("numbering_id"),
                "numbering_level": attrs.get("numbering_level"),
            }
        )
    return output


def evaluate_source(source: dict[str, str], pin: dict[str, object]) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    payload = _download(source["url"])
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if digest != pin["sha256"] or len(payload) != pin["bytes"]:
        errors.append({
            "type": "SOURCE_REVISION_MISMATCH",
            "expected_sha256": pin["sha256"],
            "actual_sha256": digest,
            "expected_bytes": pin["bytes"],
            "actual_bytes": len(payload),
        })

    audit = audit_source(source)
    adapter = DocxAdapter()
    adapted = adapter.adapt(payload, source_name=source["file_name"])
    result = SourceAdapterRunner().understand_bytes(
        payload,
        adapter=adapter,
        document_id=source["id"],
        source_name=source["file_name"],
        processed_at=FIXED_EVALUATION_TIME,
    )

    expected_headings = _expected_headings(audit)
    predicted_headings = _predicted_headings(adapted.raw_elements)
    if expected_headings != predicted_headings:
        missing = expected_headings - predicted_headings
        errors.append({
            "type": "HEADING_CONTRACT_MISMATCH",
            "missing": list(missing.elements()),
            "extra": list((predicted_headings - expected_headings).elements()),
            "candidate_elements": _candidate_elements_for_missing_headings(
                adapted.raw_elements, missing
            ),
        })

    expected_tables = _expected_table_shapes(audit)
    predicted_tables = _predicted_table_shapes(adapted.raw_elements)
    # The independent audit intentionally counts only direct row/cell children.
    # If a real table wraps cells in sdt, aggregate raw OOXML counts are checked
    # below instead of treating this shape comparison as authoritative.
    raw_tags = audit["raw_tag_counts"]
    predicted_body_type_counts = Counter(
        item.type_hint
        for item in adapted.raw_elements
        if item.attributes.get(SOURCE_ZONE_ATTRIBUTE) == "body"
    )
    expected_aggregate = {
        "TABLE": int(raw_tags.get("tbl", 0)),
        "TABLE_ROW": int(raw_tags.get("tr", 0)),
        "TABLE_CELL": int(raw_tags.get("tc", 0)),
    }
    actual_aggregate = {
        key: int(predicted_body_type_counts.get(key, 0)) for key in expected_aggregate
    }
    if expected_aggregate != actual_aggregate:
        errors.append({
            "type": "TABLE_AGGREGATE_MISMATCH",
            "expected": expected_aggregate,
            "actual": actual_aggregate,
            "independent_direct_shapes": list(expected_tables.elements()),
            "predicted_shapes": list(predicted_tables.elements()),
        })

    expected_notes = Counter(
        {kind: int(info["count"]) for kind, info in audit["notes"].items()}
    )
    predicted_notes = _predicted_note_counts(adapted.raw_elements)
    for kind, expected_count in expected_notes.items():
        if predicted_notes.get(kind, 0) != expected_count:
            errors.append({
                "type": "NOTE_COUNT_MISMATCH",
                "kind": kind,
                "expected": expected_count,
                "actual": predicted_notes.get(kind, 0),
            })

    expected_story_kinds = Counter(
        "header" if "/header" in part else "footer"
        for part in audit["referenced_header_footer_stories"]
    )
    predicted_story_presence = Counter(
        item.attributes.get(SOURCE_ZONE_ATTRIBUTE)
        for item in adapted.raw_elements
        if item.attributes.get(SOURCE_ZONE_ATTRIBUTE) in {"header", "footer"}
    )
    for kind, part_count in expected_story_kinds.items():
        if part_count > 0 and predicted_story_presence.get(kind, 0) == 0:
            errors.append({"type": "REFERENCED_STORY_MISSING", "kind": kind})

    duplicate_style_groups = len(audit["style_duplicate_counts"])
    duplicate_style_diagnostics = sum(
        1 for item in adapted.diagnostics if item.code == "COMPATIBLE_DUPLICATE_STYLE_MERGED"
    )
    if duplicate_style_groups != duplicate_style_diagnostics:
        errors.append({
            "type": "DUPLICATE_STYLE_DIAGNOSTIC_MISMATCH",
            "expected_groups": duplicate_style_groups,
            "actual_diagnostics": duplicate_style_diagnostics,
        })

    structural_diagnostics = [
        item.code for item in adapted.diagnostics if item.affects_structural_completeness
    ]
    if structural_diagnostics:
        errors.append({
            "type": "UNRESOLVED_STRUCTURAL_ADAPTER_DIAGNOSTIC",
            "codes": structural_diagnostics,
        })

    if not result.understanding.completion_report.structural_ready:
        errors.append({"type": "STRUCTURAL_READY_FALSE"})

    return {
        "id": source["id"],
        "sha256": digest,
        "bytes": len(payload),
        "independent_gold": {
            "heading_count": sum(expected_headings.values()),
            "headings": [[text, level, count] for (text, level), count in sorted(expected_headings.items())],
            "table_aggregate": expected_aggregate,
            "notes": dict(expected_notes),
            "referenced_story_parts": len(audit["referenced_header_footer_stories"]),
            "duplicate_style_groups": duplicate_style_groups,
        },
        "prediction": {
            "heading_count": sum(predicted_headings.values()),
            "table_aggregate": actual_aggregate,
            "note_counts": dict(predicted_notes),
            "structure_mode": result.understanding.document.structure.mode.value,
            "structural_ready": result.understanding.completion_report.structural_ready,
            "adapter_diagnostic_codes": [item.code for item in adapted.diagnostics],
        },
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    pins = _load_pins()
    documents = []
    for source in SOURCES:
        if source["id"] not in pins:
            raise RuntimeError(f"missing pinned source {source['id']!r}")
        documents.append(evaluate_source(source, pins[source["id"]]))
    error_count = sum(len(item["errors"]) for item in documents)
    report = {
        "benchmark": "DOCX Structure Real Pilot V0.1",
        "version": "0.1",
        "gold_provenance": "INDEPENDENT_OOXML_AUDIT_ASSISTANT_REVIEWED",
        "documents": documents,
        "document_count": len(documents),
        "error_count": error_count,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    if args.fail_on_error and error_count:
        raise SystemExit(f"real DOCX benchmark found {error_count} contract error(s)")


if __name__ == "__main__":
    main()
