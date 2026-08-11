from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.element import Element, ElementConfidence, ElementType, Provenance, StyleInfo
from source_understanding.source_attributes import HEADING_LEVEL_ATTRIBUTE, SOURCE_ZONE_ATTRIBUTE
from source_understanding.structure import BoundaryScorer, HierarchyBuilder, StructureSignalExtractor, StructureSignalKind


def _element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str,
    *,
    font_size: float | None = None,
    bold: bool | None = None,
    heading_level: int | None = None,
) -> Element:
    attributes: dict[str, object] = {SOURCE_ZONE_ATTRIBUTE: "body"}
    if heading_level is not None:
        attributes[HEADING_LEVEL_ATTRIBUTE] = heading_level
    return Element(
        id=element_id,
        order=order,
        type=element_type,
        raw_text=text,
        normalized_text=text,
        attributes=attributes,
        style=None if font_size is None and bold is None else StyleInfo(font_size=font_size, bold=bold),
        confidence=ElementConfidence(),
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


class PrefaceOutlineHierarchyTests(unittest.TestCase):
    def test_typographic_preface_plus_navigation_infers_root_and_sections(self) -> None:
        elements = (
            _element("logo", 0, ElementType.PARAGRAPH, "\t"),
            _element("title", 1, ElementType.PARAGRAPH, "Application form", font_size=18.0, bold=True),
            _element("intro", 2, ElementType.PARAGRAPH, "Intro", font_size=16.0, bold=True),
            _element("body1", 3, ElementType.PARAGRAPH, "Body", font_size=11.0),
            _element("data", 4, ElementType.PARAGRAPH, "Data use", font_size=16.0, bold=True),
            _element("body2", 5, ElementType.PARAGRAPH, "Body", font_size=11.0),
            _element("toc-title", 6, ElementType.PARAGRAPH, "Contents"),
            _element("toc1", 7, ElementType.PARAGRAPH, "\tSection A\t3"),
            _element("toc2", 8, ElementType.PARAGRAPH, "\tSection B\t4"),
            _element("toc3", 9, ElementType.PARAGRAPH, "\tSection C\t5"),
            _element("form", 10, ElementType.HEADING, "Form", heading_level=1),
            _element("section", 11, ElementType.HEADING, "Section A", heading_level=2),
        )
        before = tuple(item.model_dump(mode="python") for item in elements)
        signals = StructureSignalExtractor().extract(elements)
        outline = [item for item in signals.signals if item.kind == StructureSignalKind.OUTLINE_LEVEL]
        self.assertEqual({item.element_ids[0] for item in outline}, {"title", "intro", "data"})

        result = HierarchyBuilder().build(elements, signals, BoundaryScorer().score(elements, signals))
        by_anchor = {node.attributes["anchor_element_id"]: node for node in result.context_nodes}
        self.assertEqual(by_anchor["title"].type, "DOCUMENT_TITLE")
        self.assertEqual(by_anchor["title"].level, 0)
        self.assertEqual(by_anchor["intro"].level, 1)
        self.assertEqual(by_anchor["data"].level, 1)
        self.assertEqual(by_anchor["form"].parent_id, by_anchor["title"].id)
        self.assertEqual(by_anchor["section"].parent_id, by_anchor["form"].id)
        self.assertEqual(result.structure.mode, StructureMode.HIERARCHICAL)
        self.assertEqual(tuple(item.model_dump(mode="python") for item in elements), before)
        self.assertEqual(elements[1].type, ElementType.PARAGRAPH)

    def test_preface_without_repeated_navigation_does_not_promote_paragraphs(self) -> None:
        elements = (
            _element("title", 0, ElementType.PARAGRAPH, "Document", font_size=18.0, bold=True),
            _element("intro", 1, ElementType.PARAGRAPH, "Intro", font_size=16.0, bold=True),
            _element("data", 2, ElementType.PARAGRAPH, "Data", font_size=16.0, bold=True),
            _element("h1", 3, ElementType.HEADING, "Section", heading_level=1),
        )
        signals = StructureSignalExtractor().extract(elements)
        self.assertFalse(any(item.kind == StructureSignalKind.OUTLINE_LEVEL for item in signals.signals))

    def test_ambiguous_top_typography_does_not_infer_document_title(self) -> None:
        elements = (
            _element("title-a", 0, ElementType.PARAGRAPH, "A", font_size=18.0, bold=True),
            _element("title-b", 1, ElementType.PARAGRAPH, "B", font_size=18.0, bold=True),
            _element("s1", 2, ElementType.PARAGRAPH, "S1", font_size=16.0, bold=True),
            _element("s2", 3, ElementType.PARAGRAPH, "S2", font_size=16.0, bold=True),
            _element("toc1", 4, ElementType.PARAGRAPH, "\tA\t1"),
            _element("toc2", 5, ElementType.PARAGRAPH, "\tB\t2"),
            _element("toc3", 6, ElementType.PARAGRAPH, "\tC\t3"),
            _element("h1", 7, ElementType.HEADING, "Section", heading_level=1),
        )
        signals = StructureSignalExtractor().extract(elements)
        self.assertFalse(any(item.kind == StructureSignalKind.OUTLINE_LEVEL for item in signals.signals))


if __name__ == "__main__":
    unittest.main()
