from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.structure.signals import (
    StructureSignalExtractor,
    StructureSignalKind,
    StructureSignalPolicy,
)


def element(text: str) -> Element:
    return Element(
        id="e1",
        type=ElementType.PARAGRAPH,
        order=0,
        raw_text=text,
        normalized_text=text,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


class StructureSignalPolicyTests(unittest.TestCase):
    def test_custom_section_markers_are_recorded_in_result_policy(self):
        result = StructureSignalExtractor(section_markers=("Article", "Clause")).extract(
            (element("Article 7"),)
        )
        self.assertEqual(result.policy.section_markers, ("Article", "Clause"))
        self.assertTrue(
            any(signal.kind == StructureSignalKind.SECTION_MARKER for signal in result.signals)
        )

    def test_policy_can_be_supplied_directly(self):
        policy = StructureSignalPolicy(section_markers=("Điều", "Khoản"))
        result = StructureSignalExtractor(policy=policy).extract((element("Điều 3"),))
        self.assertEqual(result.policy, policy)

    def test_duplicate_markers_are_rejected_case_insensitively(self):
        with self.assertRaisesRegex(ValueError, "unique case-insensitively"):
            StructureSignalPolicy(section_markers=("Section", "section"))

    def test_blank_markers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-blank"):
            StructureSignalPolicy(section_markers=("chapter", "  "))

    def test_non_string_marker_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only strings"):
            StructureSignalPolicy(section_markers=("section", 3))

    def test_cannot_supply_legacy_markers_and_policy_together(self):
        with self.assertRaisesRegex(ValueError, "either section_markers or policy"):
            StructureSignalExtractor(
                section_markers=("Article",),
                policy=StructureSignalPolicy(section_markers=("Clause",)),
            )


if __name__ == "__main__":
    unittest.main()
