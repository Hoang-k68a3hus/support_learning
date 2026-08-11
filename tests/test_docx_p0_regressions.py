from __future__ import annotations

import io
import unittest
from collections.abc import Mapping
import zipfile
from datetime import datetime, timezone

from source_understanding.adapters import AdapterError, DocxAdapter, SourceAdapterRunner
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE,
)


CONTENT_TYPES = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

NORMAL_STYLES = """<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""


def package(document: str, styles: str = NORMAL_STYLES) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
    return output.getvalue()


def one_cell_table(text: str) -> str:
    return (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>"
        + text
        + "</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )


def alternate_textbox_table(choice_text: str, fallback_text: str) -> str:
    return f"""
    <mc:AlternateContent>
      <mc:Choice Requires="wps">
        <w:drawing><wps:wsp><wps:txbx><w:txbxContent>
          {one_cell_table(choice_text)}
        </w:txbxContent></wps:txbx></wps:wsp></w:drawing>
      </mc:Choice>
      <mc:Fallback>
        <w:pict><w:txbxContent>
          {one_cell_table(fallback_text)}
        </w:txbxContent></w:pict>
      </mc:Fallback>
    </mc:AlternateContent>
    """


class DocxP0RegressionTests(unittest.TestCase):
    def test_duplicate_style_missing_numpr_merges_with_explicit_numbering(self) -> None:
        styles = """<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
        <w:style w:type="paragraph" w:styleId="Heading2">
          <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr/>
        </w:style>
        <w:style w:type="paragraph" w:styleId="Heading2">
          <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
          <w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr><w:outlineLvl w:val="1"/></w:pPr>
        </w:style>
        </w:styles>"""
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Resolved heading</w:t></w:r></w:p>
        </w:body></w:document>"""

        adapted = DocxAdapter().adapt(package(document, styles))
        heading = next(item for item in adapted.raw_elements if item.text == "Resolved heading")
        self.assertEqual(heading.type_hint, "HEADING")
        self.assertEqual(heading.attributes.get("heading_level"), 2)
        self.assertEqual(heading.attributes.get("numbering_id"), "7")
        self.assertEqual(heading.attributes.get("numbering_level"), 1)
        merged = [
            diagnostic
            for diagnostic in adapted.diagnostics
            if diagnostic.code == "COMPATIBLE_DUPLICATE_STYLE_MERGED"
        ]
        self.assertEqual({item.metadata.get("style_id") for item in merged}, {"Heading2"})

    def test_duplicate_style_explicit_numbering_conflict_still_fails_closed(self) -> None:
        styles = """<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr></w:style>
        <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="8"/></w:numPr></w:pPr></w:style>
        </w:styles>"""
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Ambiguous heading</w:t></w:r></w:p>
        </w:body></w:document>"""

        with self.assertRaisesRegex(AdapterError, "conflicting duplicate DOCX styleId"):
            DocxAdapter().adapt(package(document, styles))

    def test_alternate_content_textbox_tables_are_promoted_once_with_integrity(self) -> None:
        outside = alternate_textbox_table("Choice outside", "Fallback outside")
        nested = alternate_textbox_table("Choice nested", "Fallback nested")
        document = f"""<w:document
          xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
          xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
        <w:body>
          <w:p><w:r><w:t>Outer paragraph</w:t>{outside}</w:r></w:p>
          <w:tbl><w:tr><w:tc>
            <w:p><w:r><w:t>Host cell</w:t>{nested}</w:r></w:p>
          </w:tc></w:tr></w:tbl>
        </w:body></w:document>"""

        payload = package(document)
        adapted = DocxAdapter().adapt(payload)
        tables = [item for item in adapted.raw_elements if item.type_hint == "TABLE"]
        self.assertEqual(len(tables), 3)

        embedded_tables = [
            item
            for item in tables
            if any(
                wrapper.get("alternate_branch") == "SELECTED"
                for wrapper in item.attributes.get("source_wrappers", [])
                if isinstance(wrapper, Mapping)
            )
        ]
        self.assertEqual(len(embedded_tables), 2)
        embedded_group_ids = {
            item.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] for item in embedded_tables
        }
        embedded_cells = [
            item
            for item in adapted.raw_elements
            if item.type_hint == "TABLE_CELL"
            and item.attributes.get(INTEGRITY_GROUP_ID_ATTRIBUTE) in embedded_group_ids
        ]
        self.assertEqual({item.text for item in embedded_cells}, {"Choice outside", "Choice nested"})
        self.assertTrue(all("Fallback" not in (item.text or "") for item in embedded_cells))

        nested_table = next(
            item
            for item in embedded_tables
            if INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE in item.attributes
        )
        parent_group_id = nested_table.attributes[INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE]
        top_level_group_ids = {
            item.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE]
            for item in tables
            if INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE not in item.attributes
        }
        self.assertIn(parent_group_id, top_level_group_ids)

        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="alternate-content-textbox-table",
            processed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        self.assertTrue(result.understanding.completion_report.structural_pipeline_complete)
        self.assertEqual(
            len([element for element in result.adapter_result.raw_elements if element.type_hint == "TABLE"]),
            3,
        )


if __name__ == "__main__":
    unittest.main()
