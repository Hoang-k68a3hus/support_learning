from __future__ import annotations

import io
import unittest
import zipfile

from source_understanding.adapters import DocxAdapter


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="DisabledList">
    <w:name w:val="Disabled list"/>
    <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr>
  </w:style>
</w:styles>"""

DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:body>
  <w:p>
   <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr>
   <w:r><w:t>Direct numbering disabled</w:t></w:r>
  </w:p>
  <w:p>
   <w:pPr><w:pStyle w:val="DisabledList"/></w:pPr>
   <w:r><w:t>Inherited numbering disabled</w:t></w:r>
  </w:p>
  <w:p>
   <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr>
   <w:r><w:t>Active list item</w:t></w:r>
  </w:p>
 </w:body>
</w:document>"""


def make_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", DOCUMENT)
        archive.writestr("word/styles.xml", STYLES)
    return buffer.getvalue()


class DocxNumIdZeroTests(unittest.TestCase):
    def test_numid_zero_suppresses_list_semantics(self) -> None:
        result = DocxAdapter().adapt(make_docx(), source_name="numid-zero.docx")
        by_text = {item.text: item for item in result.raw_elements if item.text}

        direct = by_text["Direct numbering disabled"]
        inherited = by_text["Inherited numbering disabled"]
        active = by_text["Active list item"]

        self.assertEqual(direct.type_hint, "PARAGRAPH")
        self.assertNotIn("numbering_id", direct.attributes)
        self.assertNotIn("integrity_group_id", direct.attributes)

        self.assertEqual(inherited.type_hint, "PARAGRAPH")
        self.assertNotIn("numbering_id", inherited.attributes)
        self.assertNotIn("integrity_group_id", inherited.attributes)

        self.assertEqual(active.type_hint, "LIST_ITEM")
        self.assertEqual(active.attributes["numbering_id"], "7")
        self.assertEqual(active.attributes["numbering_level"], 0)
        self.assertIn("integrity_group_id", active.attributes)


if __name__ == "__main__":
    unittest.main()
