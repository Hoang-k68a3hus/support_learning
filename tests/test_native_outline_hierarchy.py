from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.element import (
    Element,
    ElementConfidence,
    ElementType,
    Provenance,
    StyleInfo,
)
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)
from source_understanding.structure import (
    BoundaryScorer,
    HierarchyBuilder,
    StructureSignalExtractor,
    StructureSignalKind,
)


def _element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str | None,
    *,
    attributes: dict[str, object] | None = None,
    bold: bool | None = None,
    indentation: float | None = None,
) -> Element:
    return Element(
        id=element_id,
        order=order,
        type=element_type,
        raw_text=text,
        normalized_text=text,
        attributes={SOURCE_ZONE_ATTRIBUTE: "body", **(attributes or {})},
        style=(
            None
            if bold is None and indentation is None
            else StyleInfo(bold=bold, indentation=indentation)
        ),
        confidence=ElementConfidence(),
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def _numbered(
    element_id: str,
    order: int,
    text: str,
    *,
    level: int,
    bold: bool,
    number_format: str = "decimal",
) -> Element:
    return _element(
        element_id,
        order,
        ElementType.LIST_ITEM,
        text,
        attributes={
            "numbering_id": "1",
            "numbering_level": level,
            "number_format": number_format,
            INTEGRITY_GROUP_ID_ATTRIBUTE: "native-outline-list",
        },
        bold=bold,
        indentation=851.0,
    )


class NativeOutlineHierarchyTests(unittest.TestCase):
    def test_repeated_native_outline_creates_inferred_context_without_retyping_source(self):
        elements = [
            _element(
                "title",
                0,
                ElementType.HEADING,
                "Contract",
                attributes={HEADING_LEVEL_ATTRIBUTE: 1},
            ),
            _element("background", 1, ElementType.PARAGRAPH, "Background:", bold=True, indentation=851.0),
            _element("background_body", 2, ElementType.PARAGRAPH, "Background body."),
            _element("terms", 3, ElementType.PARAGRAPH, "Agreed Terms:", bold=True, indentation=851.0),
        ]
        order = 4
        section_ids = []
        for index in range(5):
            section_id = f"section-{index}"
            section_ids.append(section_id)
            elements.append(_numbered(section_id, order, f"Section {index + 1}", level=0, bold=True))
            order += 1
            elements.append(_numbered(f"clause-{index}", order, "Clause body.", level=1, bold=False))
            order += 1
        elements.append(_element("signing", order, ElementType.PARAGRAPH, "Signing", bold=True, indentation=851.0))
        order += 1
        elements.append(_element("signature-table", order, ElementType.TABLE, None))
        snapshot = tuple(elements)
        before = tuple(item.model_dump(mode="python") for item in snapshot)

        signals = StructureSignalExtractor().extract(snapshot)
        outline = [
            item for item in signals.signals if item.kind == StructureSignalKind.OUTLINE_LEVEL
        ]
        self.assertEqual(len(outline), 9)
        boundaries = BoundaryScorer().score(snapshot, signals)
        result = HierarchyBuilder().build(snapshot, signals, boundaries)

        by_anchor = {
            node.attributes["anchor_element_id"]: node for node in result.context_nodes
        }
        self.assertEqual(by_anchor["title"].type, "DOCUMENT_TITLE")
        self.assertEqual(by_anchor["title"].level, 0)
        self.assertEqual(by_anchor["background"].level, 1)
        self.assertEqual(by_anchor["terms"].level, 1)
        self.assertEqual(by_anchor["signing"].level, 1)
        self.assertEqual(by_anchor["terms"].parent_id, by_anchor["title"].id)
        self.assertEqual(by_anchor["signing"].parent_id, by_anchor["title"].id)
        for section_id in section_ids:
            self.assertEqual(by_anchor[section_id].type, "NUMBERED_SECTION")
            self.assertEqual(by_anchor[section_id].level, 2)
            self.assertEqual(by_anchor[section_id].parent_id, by_anchor["terms"].id)
        self.assertNotIn("clause-0", by_anchor)
        self.assertEqual(result.structure.mode, StructureMode.HIERARCHICAL)
        self.assertTrue(all(node.source == StructureSource.INFERRED for node in result.context_nodes))
        self.assertEqual(tuple(item.model_dump(mode="python") for item in snapshot), before)
        self.assertTrue(all(item.type == ElementType.LIST_ITEM for item in snapshot if item.id in section_ids))

    def test_flat_ordered_list_without_nested_outline_evidence_is_not_promoted(self):
        elements = [
            _element(
                "title",
                0,
                ElementType.HEADING,
                "Checklist",
                attributes={HEADING_LEVEL_ATTRIBUTE: 1},
            )
        ]
        for index in range(5):
            elements.append(
                _numbered(
                    f"item-{index}",
                    index + 1,
                    f"Item {index + 1}",
                    level=0,
                    bold=True,
                )
            )
        snapshot = tuple(elements)
        signals = StructureSignalExtractor().extract(snapshot)

        self.assertFalse(
            any(item.kind == StructureSignalKind.OUTLINE_LEVEL for item in signals.signals)
        )
        result = HierarchyBuilder().build(
            snapshot,
            signals,
            BoundaryScorer().score(snapshot, signals),
        )
        self.assertEqual(len(result.context_nodes), 1)
        self.assertEqual(result.context_nodes[0].type, ElementType.HEADING.value)
        self.assertEqual(result.structure.mode, StructureMode.LOCAL)

    def test_bullet_numbering_never_becomes_ordered_document_outline(self):
        elements = [
            _element(
                "title",
                0,
                ElementType.HEADING,
                "Checklist",
                attributes={HEADING_LEVEL_ATTRIBUTE: 1},
            )
        ]
        order = 1
        for index in range(5):
            elements.append(
                _numbered(
                    f"item-{index}",
                    order,
                    f"Item {index + 1}",
                    level=0,
                    bold=True,
                    number_format="bullet",
                )
            )
            order += 1
            elements.append(
                _numbered(
                    f"child-{index}",
                    order,
                    "Child",
                    level=1,
                    bold=False,
                    number_format="bullet",
                )
            )
            order += 1
        snapshot = tuple(elements)
        signals = StructureSignalExtractor().extract(snapshot)
        self.assertFalse(
            any(item.kind == StructureSignalKind.OUTLINE_LEVEL for item in signals.signals)
        )


if __name__ == "__main__":
    unittest.main()
