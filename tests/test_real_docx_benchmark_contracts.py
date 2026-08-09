from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmarks.docx_structure_real_v0_1 import run_benchmark
from benchmarks.docx_structure_real_v0_1.source_audit import _navigation_role


ROOT = Path(__file__).resolve().parents[1]
REAL_BENCHMARK = ROOT / "benchmarks" / "docx_structure_real_v0_1"


class RealDocxBenchmarkContractTests(unittest.TestCase):
    def test_frozen_gold_matches_pinned_source_revisions(self) -> None:
        sources = json.loads((REAL_BENCHMARK / "sources.json").read_text(encoding="utf-8"))
        gold = json.loads((REAL_BENCHMARK / "gold_contracts.json").read_text(encoding="utf-8"))

        source_by_id = {item["id"]: item for item in sources["documents"]}
        gold_by_id = {item["id"]: item for item in gold["documents"]}
        self.assertEqual(set(source_by_id), set(gold_by_id))
        self.assertEqual(len(source_by_id), 5)

        for document_id in sorted(source_by_id):
            source = source_by_id[document_id]
            contract = gold_by_id[document_id]
            self.assertEqual(source["bytes"], contract["bytes"])
            self.assertEqual(source["sha256"], contract["sha256"])
            self.assertRegex(contract["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_real_gold_is_explicit_about_partial_coverage(self) -> None:
        gold = run_benchmark._load_gold_payload()
        self.assertEqual(
            gold["gold_provenance"],
            "INDEPENDENT_OOXML_AUDIT_ASSISTANT_ADJUDICATED_FROZEN",
        )
        self.assertEqual(
            gold["policy"]["coverage"],
            {
                "L0_source_fidelity": "FROZEN_PARTIAL",
                "L1_element_understanding": "FROZEN_PARTIAL",
                "L2_structural_grouping": "NOT_YET_FULLY_ADJUDICATED",
                "L3_document_structure": "FROZEN_PARTIAL",
            },
        )

    def test_toc_title_is_frozen_as_navigation_not_content_heading(self) -> None:
        gold = run_benchmark._load_gold_payload()
        policy = gold["policy"]["toc_navigation"]
        self.assertIn("navigation", policy.casefold())
        contract = next(
            item
            for item in gold["documents"]
            if item["id"] == "real-docx-01-flexible-policy"
        )
        heading_texts = {
            item["text"] for item in contract["L1_element_understanding"]["headings"]
        }
        self.assertNotIn("Contents", heading_texts)
        self.assertEqual(
            contract["L1_element_understanding"]["navigation"],
            [
                {
                    "text": "Contents",
                    "role": "toc_title",
                    "style_id": "TOCHeading",
                    "count": 1,
                }
            ],
        )

    def test_independent_audit_classifies_word_toc_styles_as_navigation(self) -> None:
        styles = {
            "TOCHeading": {
                "name": "TOC Heading",
                "based_on": "Normal",
                "outline": "0",
                "definition_count": 1,
            },
            "TOC1": {
                "name": "toc 1",
                "based_on": "Normal",
                "outline": "0",
                "definition_count": 1,
            },
            "Heading1": {
                "name": "heading 1",
                "based_on": "Normal",
                "outline": "0",
                "definition_count": 1,
            },
        }
        self.assertEqual(_navigation_role("TOCHeading", styles), "toc_title")
        self.assertEqual(_navigation_role("TOC1", styles), "toc_entry")
        self.assertIsNone(_navigation_role("Heading1", styles))

    def test_real_benchmark_loads_frozen_gold_without_source_audit_oracle(self) -> None:
        self.assertNotIn("audit_source", run_benchmark.__dict__)
        gold = run_benchmark._load_gold_payload()
        self.assertEqual(gold["version"], "0.1")
        self.assertEqual(len(gold["documents"]), 5)


if __name__ == "__main__":
    unittest.main()
