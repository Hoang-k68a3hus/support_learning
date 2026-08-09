from __future__ import annotations

import io
import unittest
import zipfile
from datetime import datetime, timezone

from source_understanding.adapters import AdapterError, DocxAdapter, SourceAdapterRunner
from source_understanding.profiling import ContentCategory
from source_understanding.schemas.relation import RelationType
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
</Types>"""

STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="Heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="CustomHeading">
    <w:name w:val="Custom Heading"/><w:basedOn w:val="Heading1"/>
  </w:style>
</w:styles>"""

DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="CustomHeading"/></w:pPr><w:r><w:t>Introduction</w:t></w:r></w:p>
  <w:p><w:r><w:t>See note</w:t><w:footnoteReference w:id="1"/></w:r></w:p>
  <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  <w:sectPr><w:headerReference w:type="default" r:id="rHeader"/></w:sectPr>
 </w:body>
</w:document>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
</Relationships>"""

FOOTNOTES = """<?xml version="1.0" encoding="UTF-8"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:footnote w:id="-1"><w:p><w:r><w:t>separator</w:t></w:r></w:p></w:footnote>
 <w:footnote w:id="1"><w:p><w:r><w:t>Footnote text</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""

HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Header layout cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:hdr>"""


def make_docx(*, malicious_document: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", DOCUMENT if malicious_document is None else malicious_document)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        archive.writestr("word/styles.xml", STYLES)
        archive.writestr("word/footnotes.xml", FOOTNOTES)
        archive.writestr("word/header1.xml", HEADER)
    return buffer.getvalue()


class DocxAdapterTests(unittest.TestCase):
    def test_source_near_adapter_preserves_native_structure_without_page_claims(self):
        result = DocxAdapter().adapt(make_docx(), source_name="sample.docx")
        self.assertTrue(result.raw_elements)
        self.assertTrue(all(element.location is None for element in result.raw_elements))

        heading = next(element for element in result.raw_elements if element.text == "Introduction")
        self.assertEqual(heading.type_hint, "HEADING")
        self.assertEqual(heading.attributes[HEADING_LEVEL_ATTRIBUTE], 1)

        table_elements = [
            element for element in result.raw_elements
            if element.type_hint in {"TABLE", "TABLE_ROW", "TABLE_CELL"}
            and element.attributes.get(SOURCE_ZONE_ATTRIBUTE) == "body"
        ]
        self.assertGreaterEqual(len(table_elements), 3)
        group_ids = {element.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] for element in table_elements}
        self.assertEqual(len(group_ids), 1)

        note = next(element for element in result.raw_elements if element.text == "Footnote text")
        self.assertEqual(note.attributes[SOURCE_ANCHOR_ATTRIBUTE], {"kind": "footnote", "id": "1"})

        header_table = next(
            element for element in result.raw_elements
            if element.type_hint == "TABLE"
            and element.attributes.get(SOURCE_ZONE_ATTRIBUTE) == "header"
        )
        self.assertIsNotNone(header_table)

    def test_docx_runs_through_full_adapter_to_structure_pipeline(self):
        adapted = SourceAdapterRunner().understand_bytes(
            make_docx(),
            adapter=DocxAdapter(),
            document_id="docx-fixture",
            source_name="sample.docx",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        document = adapted.understanding.document
        self.assertEqual(document.processing.adapter_name, "docx-ooxml")
        self.assertEqual(document.processing.normalizer_version, "2")
        self.assertEqual(document.processing.structure_version, "3")
        self.assertTrue(adapted.understanding.completion_report.structural_pipeline_complete)

        footnote_relations = [
            relation for relation in document.relations
            if relation.type == RelationType.FOOTNOTE_OF
        ]
        self.assertEqual(len(footnote_relations), 1)
        note = next(element for element in document.elements if element.raw_text == "Footnote text")
        referring = next(element for element in document.elements if element.raw_text == "See note")
        self.assertEqual(footnote_relations[0].source_id, note.id)
        self.assertEqual(footnote_relations[0].target_id, referring.id)

        # Header layout tables remain typed but route as boilerplate, so they do
        # not masquerade as a main-document table modality.
        self.assertGreater(
            adapted.understanding.content_profile.category_distribution[ContentCategory.BOILERPLATE.value],
            0.0,
        )

    def test_xml_dtd_or_entity_declaration_is_rejected(self):
        malicious = """<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe "boom">]>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>"""
        with self.assertRaisesRegex(AdapterError, "DTD/entity"):
            DocxAdapter().adapt(make_docx(malicious_document=malicious))


if __name__ == "__main__":
    unittest.main()
