from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from source_understanding.adapters import (
    AdapterError,
    PlainTextAdapter,
    PlainTextAdapterPolicy,
    PlainTextEncoding,
    SourceAdapterRunner,
)
from source_understanding.schemas.context import StructureSource


class PlainTextAdapterTests(unittest.TestCase):
    def test_preserves_complete_source_view_and_exact_character_ranges(self) -> None:
        source_text = "alpha\r\nbeta\r\n\r\ngamma"

        result = PlainTextAdapter().adapt(
            source_text.encode("utf-8"),
            source_name="notes.txt",
        )

        self.assertEqual(
            "".join(element.text or "" for element in result.raw_elements),
            source_text,
        )
        self.assertEqual(
            tuple(element.type_hint for element in result.raw_elements),
            ("PARAGRAPH", "SEPARATOR", "PARAGRAPH"),
        )
        self.assertEqual(
            tuple(
                (element.location.line_start, element.location.line_end)
                for element in result.raw_elements
                if element.location is not None
            ),
            ((1, 2), (3, 3), (4, 4)),
        )
        cursor = 0
        for element in result.raw_elements:
            self.assertIsNotNone(element.location)
            location = element.location
            assert location is not None
            self.assertEqual(location.source, StructureSource.EXPLICIT)
            self.assertEqual(location.start_char, cursor)
            self.assertEqual(
                source_text[location.start_char : location.end_char],
                element.text,
            )
            cursor = location.end_char
        self.assertEqual(cursor, len(source_text))
        self.assertEqual(result.metadata.source_name, "notes.txt")
        self.assertEqual(
            result.metadata.attributes["plain_text"]["source_text_hash"],
            "sha256:" + hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )

    def test_auto_detects_utf8_bom_without_putting_bom_in_source_text(self) -> None:
        result = PlainTextAdapter().adapt(b"\xef\xbb\xbfhello")

        self.assertEqual(result.raw_elements[0].text, "hello")
        self.assertEqual(result.raw_elements[0].location.start_char, 0)
        self.assertEqual(result.metadata.attributes["plain_text"]["bom"], "UTF-8")
        self.assertEqual(result.diagnostics[0].code, "TEXT_ENCODING_BOM_DETECTED")

    def test_auto_detects_utf16_bom_and_uses_decoded_character_offsets(self) -> None:
        source_text = "xin chào\n\nthế giới"
        payload = b"\xff\xfe" + source_text.encode("utf-16-le")

        result = PlainTextAdapter().adapt(payload)

        self.assertEqual(
            "".join(element.text or "" for element in result.raw_elements),
            source_text,
        )
        self.assertEqual(
            result.metadata.attributes["plain_text"]["encoding"],
            "UTF-16-LE",
        )
        self.assertEqual(result.raw_elements[-1].location.end_char, len(source_text))

    def test_explicit_utf16_endianness_rejects_conflicting_bom(self) -> None:
        adapter = PlainTextAdapter(
            PlainTextAdapterPolicy(encoding=PlainTextEncoding.UTF16_LE)
        )

        with self.assertRaisesRegex(AdapterError, "BOM conflicts"):
            adapter.adapt(b"\xfe\xff" + "hello".encode("utf-16-be"))

    def test_auto_encoding_rejects_utf32_bom_instead_of_misreading_utf16(self) -> None:
        with self.assertRaisesRegex(AdapterError, "does not support UTF-32"):
            PlainTextAdapter().adapt(b"\xff\xfe\x00\x00h\x00\x00\x00")

    def test_invalid_utf8_and_nul_are_rejected_without_replacement(self) -> None:
        with self.assertRaisesRegex(AdapterError, "decode failed"):
            PlainTextAdapter().adapt(b"\xff")
        with self.assertRaisesRegex(AdapterError, "NUL"):
            PlainTextAdapter().adapt(b"a\x00b")

    def test_empty_source_is_reported_without_inventing_an_element(self) -> None:
        result = PlainTextAdapter().adapt(b"")

        self.assertEqual(result.raw_elements, ())
        self.assertEqual(result.diagnostics[0].code, "EMPTY_DOCUMENT")
        self.assertTrue(result.diagnostics[0].affects_structural_completeness)

        with self.assertRaisesRegex(AdapterError, "no raw elements"):
            SourceAdapterRunner().understand_bytes(
                b"",
                adapter=PlainTextAdapter(),
                document_id="empty-text",
                processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            )

    def test_runs_end_to_end_with_fail_closed_preservation_report(self) -> None:
        source_text = "First paragraph.\n\nSecond paragraph."

        result = SourceAdapterRunner().understand_bytes(
            source_text.encode("utf-8"),
            adapter=PlainTextAdapter(),
            document_id="plain-text-document",
            source_name="notes.txt",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertTrue(result.preservation_report.fully_preserved)
        self.assertEqual(result.preservation_report.raw_text_preservation_ratio, 1.0)
        self.assertEqual(result.understanding.document.processing.adapter_name, "plain-text")
        self.assertEqual(
            "".join(element.raw_text or "" for element in result.understanding.document.elements),
            source_text,
        )


if __name__ == "__main__":
    unittest.main()
