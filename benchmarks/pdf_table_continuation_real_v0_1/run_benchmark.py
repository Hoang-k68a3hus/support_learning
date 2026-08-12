from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from source_understanding.adapters import PdfAdapter, SourceAdapterRunner
from source_understanding.schemas.relation import RelationType

from .evaluate import evaluate, load_gold

HERE = Path(__file__).parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--enforce-promotion-gate", action="store_true")
    args = parser.parse_args()
    gold_payload = json.loads((HERE / "gold_contracts.json").read_text(encoding="utf-8"))
    gold = load_gold(HERE / "gold_contracts.json")
    sources = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))["sources"]
    needed_sources = {case.source_id for case in gold}
    predicted: set[tuple[str, int, int]] = set()
    source_reports: list[dict[str, object]] = []
    for source in sources:
        if source["id"] not in needed_sources:
            continue
        path = args.root / source["relative_path"]
        payload = path.read_bytes()
        actual_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        expected_hash = source.get("sha256")
        if expected_hash is not None and actual_hash != expected_hash:
            raise SystemExit(f"source hash mismatch for {source['id']}: {actual_hash}")
        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=PdfAdapter(),
            document_id=source["id"],
            source_name=path.name,
        )
        edges = [
            relation
            for relation in result.understanding.relation_result.relations
            if relation.type == RelationType.CONTINUES
        ]
        for relation in edges:
            page_pair = relation.metadata.get("page_pair")
            if isinstance(page_pair, list) and len(page_pair) == 2:
                predicted.add((source["id"], int(page_pair[0]), int(page_pair[1])))
        source_reports.append(
            {
                "source_id": source["id"],
                "relative_path": source["relative_path"],
                "sha256": actual_hash,
                "raw_element_count": len(result.adapter_result.raw_elements),
                "canonical_element_count": len(result.understanding.structural_document.elements),
                "preserved": result.preservation_report.fully_preserved,
                "continuation_relation_count": len(edges),
            }
        )
    gold_keys = {case.key for case in gold}
    unadjudicated_predictions = sorted(predicted - gold_keys)
    metrics = evaluate(
        gold,
        predicted & gold_keys,
        tuple(gold_payload.get("chain_requirements", ())),
    )
    effective_promotion_gate = metrics.promotion_gate_passed and not unadjudicated_predictions
    report = {
        "benchmark": "pdf_table_continuation_real_v0_1",
        "gold_provenance": gold_payload["gold_provenance"],
        "source_reports": source_reports,
        "predicted_edges_adjudicated": sorted(predicted & gold_keys),
        "unadjudicated_predicted_edges": unadjudicated_predictions,
        "unadjudicated_predicted_edge_count": len(unadjudicated_predictions),
        "metrics": asdict(metrics),
        "effective_promotion_gate_passed": effective_promotion_gate,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.enforce_promotion_gate and not effective_promotion_gate:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
