from __future__ import annotations

import re
import unittest

from benchmarks.docx_structure_real_v0_1._corpus import SOURCES
from benchmarks.docx_structure_real_v0_1.adjudication import (
    ReviewCoverageStatus,
    ReviewStatus,
)
from benchmarks.docx_structure_real_v0_1.reviewed_gold import (
    build_reviewed_benchmark_manifest,
    load_review_decisions,
)
from source_understanding.schemas.context import StructureMode
from source_understanding.schemas.element import ElementType
from source_understanding.schemas.logical_unit import LogicalUnitType


_PRODUCTION_ID_RE = re.compile(r"^(?:el_|lu_|ctx_|region_|rel_)")


class ReviewedRealDocxGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.decisions = load_review_decisions()
        cls.by_id = {item.source_id: item for item in cls.decisions}

    def test_reviewed_gold_covers_exact_pinned_corpus_and_is_final(self) -> None:
        self.assertEqual(
            set(self.by_id),
            {str(source["id"]) for source in SOURCES},
        )
        self.assertEqual(len(self.decisions), 5)
        for decision in self.decisions:
            self.assertEqual(decision.status, ReviewStatus.FINAL)
            self.assertIsNotNone(decision.gold)
            self.assertEqual(
                decision.coverage.L1_element_understanding.coverage,
                ReviewCoverageStatus.PARTIAL,
            )
            self.assertEqual(
                decision.coverage.L2_structural_grouping.coverage,
                ReviewCoverageStatus.FULL,
            )
            self.assertEqual(
                decision.coverage.L3_document_structure.coverage,
                ReviewCoverageStatus.FULL,
            )

    def test_reviewed_gold_uses_benchmark_ids_not_production_ids(self) -> None:
        for decision in self.decisions:
            gold = decision.gold
            assert gold is not None
            strings = [
                *(item.id for item in gold.elements),
                *(item.id for item in gold.logical_units),
                *(item.id for item in gold.context_nodes),
                *(item.id for item in gold.regions),
                *(item.id for item in gold.relations),
                *(item.anchor_element_id for item in gold.context_nodes),
                *(item.parent_id for item in gold.context_nodes if item.parent_id is not None),
                *(item.source_id for item in gold.relations),
                *(item.target_id for item in gold.relations),
            ]
            for value in strings:
                self.assertIsNone(_PRODUCTION_ID_RE.match(value), value)

    def test_flexible_policy_keeps_nested_visual_list_as_one_gold_unit(self) -> None:
        gold = self.by_id["real-docx-01-flexible-policy"].gold
        assert gold is not None
        order = {item.id: item.order for item in gold.elements}
        list_orders = {
            tuple(order[element_id] for element_id in unit.element_ids)
            for unit in gold.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        }
        self.assertIn(
            (43, 44, 45, 46, 48, 49, 50, 51, 53, 54, 55, 56),
            list_orders,
        )
        self.assertEqual(len(list_orders), 7)

    def test_academy_numid_zero_is_not_gold_list_content(self) -> None:
        gold = self.by_id["real-docx-02-academy-form"].gold
        assert gold is not None
        by_order = {item.order: item for item in gold.elements}
        for order in (158, 162, 163):
            self.assertEqual(by_order[order].type, ElementType.PARAGRAPH)

    def test_ivd_form_has_reviewed_key_value_group(self) -> None:
        gold = self.by_id["real-docx-03-ivd-tabular"].gold
        assert gold is not None
        order = {item.id: item.order for item in gold.elements}
        units = [
            unit
            for unit in gold.logical_units
            if unit.type == LogicalUnitType.KEY_VALUE_GROUP
        ]
        self.assertEqual(len(units), 1)
        self.assertEqual(
            tuple(order[element_id] for element_id in units[0].element_ids),
            (0, 1, 2, 4, 5, 6, 7),
        )

    def test_eps_reviewed_structure_is_hierarchical(self) -> None:
        gold = self.by_id["real-docx-04-eps-guidance"].gold
        assert gold is not None
        self.assertEqual(gold.expected_structure_mode, StructureMode.HIERARCHICAL)
        self.assertEqual(len(gold.context_nodes), 6)

    def test_contractor_numbered_list_items_can_anchor_inferred_context(self) -> None:
        gold = self.by_id["real-docx-05-contractor-licence"].gold
        assert gold is not None
        elements = {item.id: item for item in gold.elements}
        anchored = {
            elements[node.anchor_element_id].order: elements[node.anchor_element_id].type
            for node in gold.context_nodes
        }
        for order in (8, 67, 69, 75, 81, 104, 108, 128, 131, 135, 137, 144, 146, 149, 152):
            self.assertEqual(anchored[order], ElementType.LIST_ITEM)
        self.assertEqual(gold.expected_structure_mode, StructureMode.HIERARCHICAL)

    def test_reviewed_benchmark_manifest_is_reproducible(self) -> None:
        manifest = build_reviewed_benchmark_manifest(self.decisions)
        self.assertEqual(len(manifest.cases), 5)
        self.assertEqual(
            tuple(item.document_id for item in manifest.cases),
            tuple(str(source["id"]) for source in SOURCES),
        )
        self.assertTrue(
            all(item.annotation_file.startswith("reviewed_gold/") for item in manifest.cases)
        )


if __name__ == "__main__":
    unittest.main()
