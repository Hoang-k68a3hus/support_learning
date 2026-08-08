from __future__ import annotations

import unittest

from source_understanding.atomic import (
    ElementNormalizationError,
    ElementNormalizationPolicy,
    ElementNormalizer,
    UnicodeNormalizationForm,
)
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import ElementType, Provenance, RawElement


def raw(
    order: int,
    text: str | None,
    *,
    type_hint: str | None = "paragraph",
) -> RawElement:
    return RawElement(
        text=text,
        type_hint=type_hint,
        order=order,
        attributes={"source_key": f"r{order}"},
        provenance=Provenance(
            source=StructureSource.EXPLICIT,
            extractor="test-adapter",
            extractor_version="1",
        ),
    )


class ElementNormalizerTests(unittest.TestCase):
    def test_preserves_raw_text_and_records_line_and_unicode_normalization(self):
        source = "Cafe\u0301\r\nnext"
        result = ElementNormalizer().normalize((raw(0, source),), document_id="doc1")
        element = result.elements[0]
        self.assertEqual(element.raw_text, source)
        self.assertEqual(element.normalized_text, "Café\nnext")
        self.assertEqual(
            [record.operation for record in element.provenance.transformations],
            ["normalize_line_endings", "normalize_unicode"],
        )
        self.assertEqual(result.transformed_element_ids, (element.id,))

    def test_code_indentation_and_surrounding_whitespace_are_not_stripped(self):
        source = "    if x:\n        return x  \n"
        result = ElementNormalizer().normalize(
            (raw(0, source, type_hint="code"),),
            document_id="doc1",
        )
        element = result.elements[0]
        self.assertEqual(element.type, ElementType.CODE)
        self.assertEqual(element.raw_text, source)
        self.assertEqual(element.normalized_text, source)
        self.assertEqual(element.provenance.transformations, ())

    def test_type_hint_normalization_is_syntactic_not_lexical(self):
        result = ElementNormalizer().normalize(
            (
                raw(0, "row", type_hint="table-row"),
                raw(1, "heading", type_hint="Heading"),
            ),
            document_id="doc1",
        )
        self.assertEqual(result.elements[0].type, ElementType.TABLE_ROW)
        self.assertEqual(result.elements[1].type, ElementType.HEADING)
        self.assertEqual(result.unknown_type_hint_element_ids, ())

    def test_unknown_type_hint_stays_unknown_and_is_diagnosed(self):
        result = ElementNormalizer().normalize(
            (raw(0, "x", type_hint="magic_section"),),
            document_id="doc1",
        )
        element = result.elements[0]
        self.assertEqual(element.type, ElementType.UNKNOWN)
        self.assertEqual(result.unknown_type_hint_element_ids, (element.id,))

    def test_missing_type_hint_is_unknown_without_false_warning(self):
        result = ElementNormalizer().normalize(
            (raw(0, "x", type_hint=None),),
            document_id="doc1",
        )
        self.assertEqual(result.elements[0].type, ElementType.UNKNOWN)
        self.assertEqual(result.unknown_type_hint_element_ids, ())

    def test_textless_source_element_is_preserved(self):
        result = ElementNormalizer().normalize(
            (raw(0, None, type_hint="figure"),),
            document_id="doc1",
        )
        element = result.elements[0]
        self.assertEqual(element.type, ElementType.FIGURE)
        self.assertIsNone(element.raw_text)
        self.assertIsNone(element.normalized_text)
        self.assertEqual(element.attributes["source_key"], "r0")

    def test_element_identity_depends_on_source_near_input_not_normalization_policy(self):
        source = raw(0, "ＡＢＣ", type_hint="paragraph")
        nfc = ElementNormalizer(
            ElementNormalizationPolicy(unicode_form=UnicodeNormalizationForm.NFC)
        ).normalize((source,), document_id="doc1")
        nfkc = ElementNormalizer(
            ElementNormalizationPolicy(unicode_form=UnicodeNormalizationForm.NFKC)
        ).normalize((source,), document_id="doc1")
        self.assertEqual(nfc.elements[0].id, nfkc.elements[0].id)
        self.assertEqual(nfc.elements[0].normalized_text, "ＡＢＣ")
        self.assertEqual(nfkc.elements[0].normalized_text, "ABC")

    def test_source_document_identity_namespaces_element_ids(self):
        source = raw(0, "same")
        first = ElementNormalizer().normalize((source,), document_id="doc1")
        second = ElementNormalizer().normalize((source,), document_id="doc2")
        self.assertNotEqual(first.elements[0].id, second.elements[0].id)

    def test_existing_provenance_transformations_are_preserved(self):
        source = RawElement(
            text="a\r\nb",
            type_hint="paragraph",
            order=0,
            provenance=Provenance(
                source=StructureSource.EXPLICIT,
                extractor="adapter",
                transformations=(
                    {
                        "operation": "decode_source",
                        "metadata": {"encoding": "utf-8"},
                    },
                ),
            ),
        )
        result = ElementNormalizer().normalize((source,), document_id="doc1")
        operations = [
            record.operation for record in result.elements[0].provenance.transformations
        ]
        self.assertEqual(operations, ["decode_source", "normalize_line_endings"])

    def test_normalizer_does_not_invent_element_quality_or_retrieval_exclusion(self):
        result = ElementNormalizer().normalize(
            (raw(0, "Header", type_hint="header"),),
            document_id="doc1",
        )
        element = result.elements[0]
        self.assertIsNone(element.confidence.overall)
        self.assertIsNone(element.confidence.type)
        self.assertFalse(element.exclude_from_retrieval)

    def test_rejects_duplicate_and_out_of_order_raw_elements(self):
        with self.assertRaisesRegex(ElementNormalizationError, "unique order"):
            ElementNormalizer().normalize(
                (raw(0, "a"), raw(0, "b")),
                document_id="doc1",
            )
        with self.assertRaisesRegex(ElementNormalizationError, "ascending source order"):
            ElementNormalizer().normalize(
                (raw(1, "b"), raw(0, "a")),
                document_id="doc1",
            )

    def test_same_input_is_deterministic(self):
        source = (raw(0, "a"), raw(1, "b", type_hint="list-item"))
        first = ElementNormalizer().normalize(source, document_id="doc1")
        second = ElementNormalizer().normalize(source, document_id="doc1")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
