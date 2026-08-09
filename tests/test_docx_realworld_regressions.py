from __future__ import annotations

import io
import unittest
import zipfile
from datetime import datetime, timezone

from source_understanding.adapters import AdapterError, DocxAdapter, SourceAdapterRunner
from source_understanding.source_attributes import INTEGRITY_GROUP_ID_ATTRIBUTE


CONTENT_TYPES = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""

NUMBERING = """<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1"/></w:lvl></w:abstractNum>
<w:num w:numId="0"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


def package(document: str, styles: str, numbering: str = NUMBERING) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/numbering.xml", numbering)
    return output.getvalue()


class DocxRealWorldRegressionTests(unittest.TestCase):
    def test_numbered_headings_do_not_form_native_list_integrity_group(self) -> None:
        styles = """<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
        <w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="3"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr></w:style>
        </w:styles>"""
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading4"/></w:pPr><w:r><w:t>First heading</w:t></w:r></w:p>
        <w:p><w:pPr><w:pStyle w:val="Heading4"/></w:pPr><w:r><w:t>Second heading</w:t></w:r></w:p>
        <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr><w:r><w:t>Actual list item</w:t></w:r></w:p>
        </w:body></w:document>"""
        payload = package(document, styles)
        adapted = DocxAdapter().adapt(payload)
        headings = [item for item in adapted.raw_elements if item.type_hint == "HEADING"]
        self.assertEqual([item.text for item in headings], ["First heading", "Second heading"])
        self.assertTrue(all(INTEGRITY_GROUP_ID_ATTRIBUTE not in item.attributes for item in headings))
        self.assertTrue(all(item.attributes.get("numbering_id") == "0" for item in headings))

        list_item = next(item for item in adapted.raw_elements if item.type_hint == "LIST_ITEM")
        self.assertIn(INTEGRITY_GROUP_ID_ATTRIBUTE, list_item.attributes)

        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="numbered-headings",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        self.assertTrue(result.understanding.completion_report.structural_pipeline_complete)
        self.assertEqual(len(result.understanding.document.context_nodes), 2)

    def test_compatible_duplicate_styles_merge_missing_structural_fields(self) -> None:
        styles = """<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="normal"/></w:style>
        <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
        <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style>
        <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
        </w:styles>"""
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Resolved heading</w:t></w:r></w:p>
        </w:body></w:document>"""
        adapted = DocxAdapter().adapt(package(document, styles))
        heading = next(item for item in adapted.raw_elements if item.text == "Resolved heading")
        self.assertEqual(heading.type_hint, "HEADING")
        self.assertEqual(heading.attributes.get("heading_level"), 1)
        merged = [d for d in adapted.diagnostics if d.code == "COMPATIBLE_DUPLICATE_STYLE_MERGED"]
        self.assertEqual({d.metadata.get("style_id") for d in merged}, {"Normal", "Heading1"})
        self.assertTrue(all(not d.affects_structural_completeness for d in merged))

    def test_conflicting_duplicate_style_structural_fields_still_fail_closed(self) -> None:
        styles = """<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
        <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>
        </w:styles>"""
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Ambiguous heading</w:t></w:r></w:p>
        </w:body></w:document>"""
        with self.assertRaisesRegex(AdapterError, "conflicting duplicate DOCX styleId"):
            DocxAdapter().adapt(package(document, styles))


if __name__ == "__main__":
    unittest.main()
