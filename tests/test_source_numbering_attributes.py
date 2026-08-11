from __future__ import annotations

import unittest

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.source_attributes import (
    SourceAttributeError,
    source_numbering_format,
    source_numbering_level,
    source_numbering_sequence_id,
)


def _element(attributes: dict[str, object]) -> Element:
    return Element(
        id="e1",
        order=0,
        type=ElementType.LIST_ITEM,
        raw_text="Item",
        normalized_text="Item",
        attributes=attributes,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


class SourceNumberingAttributeTests(unittest.TestCase):
    def test_numbering_source_facts_are_read_without_hierarchy_inference(self):
        element = _element(
            {"numbering_id": "42", "numbering_level": 0, "number_format": "decimal"}
        )
        self.assertEqual(source_numbering_sequence_id(element), "42")
        self.assertEqual(source_numbering_level(element), 0)
        self.assertEqual(source_numbering_format(element), "decimal")

    def test_numbering_contract_rejects_invalid_reserved_values(self):
        with self.assertRaises(SourceAttributeError):
            source_numbering_level(_element({"numbering_level": True}))
        with self.assertRaises(SourceAttributeError):
            source_numbering_level(_element({"numbering_level": -1}))
        with self.assertRaises(SourceAttributeError):
            source_numbering_sequence_id(_element({"numbering_id": " "}))
        with self.assertRaises(SourceAttributeError):
            source_numbering_format(_element({"number_format": " decimal "}))


if __name__ == "__main__":
    unittest.main()
