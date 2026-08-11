from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from source_understanding.adapters import (
    AdapterError,
    MarkdownAdapter,
    MarkdownAdapterPolicy,
    MarkdownEncoding,
    SourceAdapterRunner,
)
from source_understanding.schemas.context import StructureSource


class MarkdownAdapterTests(unittest.TestCase):
    def test_preserves_complete_source_view_offsets_and_block_facts(self) -> None:
        source_text = (
            "# Title #\r\n"
            "\r\n"
            "Intro **raw**.\r\n"
            "\r\n"
            "- first\r\n"
            "  continuation\r\n"
            "- second\r\n"
            "\r\n"
            "> quoted\r\n"
            "> line\r\n"
            "\r\n"
            "```py\r\n"
            "# not a heading\r\n"
            "```\r\n"
        )

        result = MarkdownAdapter().adapt(
            source_text.encode("utf-8"),
            source_name="guide.md",
        )

        self.assertEqual(
            "".join(item.text or "" for item in result.raw_elements),
            source_text,
        )
        self.assertEqual(
            tuple(item.type_hint for item in result.raw_elements),
            (
                "HEADING",
                "SEPARATOR",
                "PARAGRAPH",
                "SEPARATOR",
                "LIST_ITEM",
                "LIST_ITEM",
                "SEPARATOR",
                "PARAGRAPH",
                "SEPARATOR",
                "CODE",
            ),
        )
        self.assertEqual(result.raw_elements[0].attributes["source_label"], "Title")
        self.assertEqual(result.raw_elements[0].attributes["heading_level"], 1)
        self.assertEqual(
            result.raw_elements[4].attributes["integrity_group_id"],
            result.raw_elements[5].attributes["integrity_group_id"],
        )
        self.assertIn("continuation", result.raw_elements[4].text)
        self.assertEqual(
            result.raw_elements[7].attributes["markdown_blockquote_depths"],
            [1, 1],
        )
        self.assertEqual(result.raw_elements[-1].attributes["markdown_info_string"], "py")

        cursor = 0
        for element in result.raw_elements:
            location = element.location
            self.assertIsNotNone(location)
            assert location is not None
            self.assertEqual(location.source, StructureSource.EXPLICIT)
            self.assertEqual(location.start_char, cursor)
            self.assertEqual(
                source_text[location.start_char : location.end_char],
                element.text,
            )
            cursor = location.end_char
        self.assertEqual(cursor, len(source_text))
        self.assertEqual(
            result.metadata.attributes["markdown"]["source_text_hash"],
            "sha256:" + hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )

    def test_setext_is_heading_only_with_preceding_paragraph_context(self) -> None:
        source_text = "Title\n===\n\n---\n\nBody\n---\n"

        result = MarkdownAdapter().adapt(source_text.encode("utf-8"))

        self.assertEqual(
            tuple(item.type_hint for item in result.raw_elements),
            ("HEADING", "SEPARATOR", "SEPARATOR", "SEPARATOR", "HEADING"),
        )
        self.assertEqual(result.raw_elements[0].attributes["source_label"], "Title")
        self.assertEqual(result.raw_elements[0].attributes["heading_level"], 1)
        self.assertEqual(
            result.raw_elements[2].attributes["markdown_block_kind"],
            "thematic_break",
        )
        self.assertEqual(result.raw_elements[-1].attributes["source_label"], "Body")
        self.assertEqual(result.raw_elements[-1].attributes["heading_level"], 2)

    def test_conservative_grammar_does_not_overclaim_inline_or_gfm_semantics(self) -> None:
        source_text = (
            "#NoSpace\n"
            "####### Too many\n"
            "\n"
            "| Name | Value |\n"
            "| --- | --- |\n"
            "| A | 1 |\n"
            "\n"
            "> Warning: source quote, not a warning annotation.\n"
            "\n"
            "Definition: lexical text remains a paragraph.\n"
        )

        result = MarkdownAdapter().adapt(source_text.encode("utf-8"))

        non_separators = [
            item for item in result.raw_elements if item.type_hint != "SEPARATOR"
        ]
        self.assertTrue(all(item.type_hint == "PARAGRAPH" for item in non_separators))
        self.assertEqual(
            non_separators[1].attributes["markdown_block_kind"],
            "paragraph",
        )
        self.assertNotIn("semantic_role", non_separators[-1].attributes)

    def test_fenced_code_is_atomic_and_unclosed_fence_is_diagnosed(self) -> None:
        source_text = "~~~python\n## not heading\n- not list\n"

        result = MarkdownAdapter().adapt(source_text.encode("utf-8"))

        self.assertEqual(len(result.raw_elements), 1)
        self.assertEqual(result.raw_elements[0].type_hint, "CODE")
        self.assertEqual(result.raw_elements[0].text, source_text)
        self.assertFalse(result.raw_elements[0].attributes["markdown_fence_closed"])
        self.assertEqual(result.diagnostics[0].code, "MARKDOWN_UNCLOSED_FENCE")
        self.assertFalse(result.diagnostics[0].affects_structural_completeness)

    def test_heading_source_label_drives_clean_context_without_changing_raw_text(self) -> None:
        source_text = "# Course\n\n## Unit\nBody text.\n"

        result = SourceAdapterRunner().understand_bytes(
            source_text.encode("utf-8"),
            adapter=MarkdownAdapter(),
            document_id="markdown-course",
            source_name="course.md",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        document = result.understanding.document
        self.assertTrue(result.preservation_report.fully_preserved)
        self.assertEqual(
            "".join(item.raw_text or "" for item in document.elements),
            source_text,
        )
        self.assertEqual(
            tuple(node.label for node in document.context_nodes),
            ("Course", "Unit"),
        )
        self.assertEqual(document.context_nodes[1].parent_id, document.context_nodes[0].id)
        manifest = document.processing.configuration["source_understanding_pipeline"]
        self.assertEqual(manifest["source_attribute_contract_version"], "3")
        self.assertEqual(manifest["hierarchy_version"], "5")
        self.assertEqual(document.processing.adapter_name, "markdown-block-subset")
        self.assertEqual(
            document.processing.configuration["source_adapter"]["policy"]["dialect"],
            "COMMONMARK_BLOCK_SUBSET_V1",
        )

    def test_bom_decoding_and_invalid_text_fail_closed(self) -> None:
        result = MarkdownAdapter().adapt(b"\xef\xbb\xbf# Title\n")
        self.assertEqual(result.raw_elements[0].text, "# Title\n")
        self.assertEqual(result.raw_elements[0].location.start_char, 0)
        self.assertEqual(result.diagnostics[0].code, "MARKDOWN_ENCODING_BOM_DETECTED")

        with self.assertRaisesRegex(AdapterError, "decode failed"):
            MarkdownAdapter().adapt(b"\xff")
        with self.assertRaisesRegex(AdapterError, "NUL"):
            MarkdownAdapter().adapt(b"a\x00b")
        with self.assertRaisesRegex(AdapterError, "UTF-32"):
            MarkdownAdapter().adapt(b"\xff\xfe\x00\x00h\x00\x00\x00")

        configured = MarkdownAdapter(
            MarkdownAdapterPolicy(encoding=MarkdownEncoding.UTF16_BE)
        )
        with self.assertRaisesRegex(AdapterError, "BOM conflicts"):
            configured.adapt(b"\xff\xfe" + "# title".encode("utf-16-le"))

    def test_empty_and_size_limit_do_not_invent_content(self) -> None:
        result = MarkdownAdapter().adapt(b"")
        self.assertEqual(result.raw_elements, ())
        self.assertEqual(result.diagnostics[0].code, "EMPTY_DOCUMENT")
        self.assertTrue(result.diagnostics[0].affects_structural_completeness)

        adapter = MarkdownAdapter(MarkdownAdapterPolicy(max_source_bytes=2))
        with self.assertRaisesRegex(AdapterError, "exceeds max_source_bytes"):
            adapter.adapt(b"abc")

    def test_same_source_and_policy_are_deterministic(self) -> None:
        payload = b"# Heading\n\n1. first\n2. second\n"
        adapter = MarkdownAdapter()
        self.assertEqual(
            adapter.adapt(payload, source_name="same.md"),
            adapter.adapt(payload, source_name="same.md"),
        )


if __name__ == "__main__":
    unittest.main()
