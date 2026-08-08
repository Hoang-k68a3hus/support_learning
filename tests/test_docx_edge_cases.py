from __future__ import annotations

import io
import unittest
import zipfile
from datetime import datetime, timezone

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.schemas.relation import RelationType
from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE,
)


CONTENT_TYPES = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>
</Types>"""


def package(document: str, *, footnotes: str | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        if footnotes is not None:
            archive.writestr("word/footnotes.xml", footnotes)
    return output.getvalue()


class DocxEdgeCaseTests(unittest.TestCase):
    def test_nested_table_inside_content_control_is_promoted(self):
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body><w:tbl><w:tr><w:tc>
          <w:p><w:r><w:t>Outer text</w:t></w:r></w:p>
          <w:sdt><w:sdtPr><w:tag w:val="nested"/></w:sdtPr><w:sdtContent>
            <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Nested text</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          </w:sdtContent></w:sdt>
        </w:tc></w:tr></w:tbl></w:body></w:document>"""
        raw = DocxAdapter().adapt(package(document)).raw_elements
        tables = [item for item in raw if item.type_hint == "TABLE"]
        self.assertEqual(len(tables), 2)
        outer = next(item for item in tables if INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE not in item.attributes)
        nested = next(item for item in tables if INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE in item.attributes)
        self.assertEqual(
            nested.attributes[INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE],
            outer.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE],
        )
        self.assertTrue(nested.attributes.get("source_wrappers"))

        result = SourceAdapterRunner().understand_bytes(
            package(document),
            adapter=DocxAdapter(),
            document_id="nested",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        nesting = [
            relation for relation in result.understanding.document.relations
            if relation.type == RelationType.PART_OF
            and relation.metadata.get("membership") == "native_integrity_parent"
        ]
        self.assertEqual(len(nesting), 1)

    def test_table_inside_footnote_keeps_text_but_marks_structure_incomplete(self):
        document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body><w:p><w:r><w:t>Body</w:t><w:footnoteReference w:id="1"/></w:r></w:p></w:body></w:document>"""
        footnotes = """<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:footnote w:id="1"><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Inside note table</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:footnote>
        </w:footnotes>"""
        payload = package(document, footnotes=footnotes)
        adapted = DocxAdapter().adapt(payload)
        note = next(item for item in adapted.raw_elements if item.attributes.get("note_kind") == "footnote")
        self.assertIn("Inside note table", note.text)
        structural = [d for d in adapted.diagnostics if d.affects_structural_completeness]
        self.assertTrue(any(d.code == "FOOTNOTE_COMPLEX_STRUCTURE_FLATTENED" for d in structural))

        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="note-table",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        self.assertFalse(result.understanding.completion_report.structural_ready)
        self.assertGreater(result.understanding.completion_report.metrics.adapter_structural_issue_count, 0)


if __name__ == "__main__":
    unittest.main()
