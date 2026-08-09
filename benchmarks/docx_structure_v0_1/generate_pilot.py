from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from source_understanding.evaluation.schemas import (
    BenchmarkCase,
    BenchmarkManifest,
    BenchmarkSourceKind,
    BenchmarkSplit,
    ExpectedAdapterDiagnostic,
    GoldContextNode,
    GoldDocumentStructure,
    GoldElement,
    GoldLogicalUnit,
    GoldRegion,
    GoldRelation,
    GoldSourceAnchor,
    GoldSourceDescriptor,
    UnsupportedConstruct,
)
from source_understanding.schemas.context import StructureMode
from source_understanding.schemas.element import ElementType
from source_understanding.schemas.logical_unit import LogicalUnitType
from source_understanding.schemas.relation import RelationType


GENERATOR_ID = "docx-structure-pilot-generator:0.1"
GENERATOR_SEED = 20260809
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_STYLE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
REL_NUMBERING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
REL_HEADER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
REL_FOOTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
REL_FOOTNOTE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
REL_ENDNOTE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"
REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
REL_ALTCHUNK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk"
MAIN_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
STYLES_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
NUMBERING_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
FOOTNOTES_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
ENDNOTES_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
HEADER_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
FOOTER_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"


@dataclass(frozen=True)
class GeneratedCase:
    document_id: str
    file_name: str
    payload: bytes
    gold: GoldDocumentStructure
    split: BenchmarkSplit
    tags: tuple[str, ...]


def _zip(entries: dict[str, str | bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(entries):
            raw = entries[name]
            data = raw.encode("utf-8") if isinstance(raw, str) else raw
            info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()


def _root_rels() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{PKG_REL_NS}">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>'''


def _content_types(overrides: dict[str, str], *, html: bool = False) -> str:
    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    if html:
        defaults.append('<Default Extension="html" ContentType="text/html"/>')
    override_xml = "\n".join(
        f'<Override PartName="/{escape(part)}" ContentType="{escape(content_type)}"/>'
        for part, content_type in sorted(overrides.items())
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="{CT_NS}">
  {"".join(defaults)}
  {override_xml}
</Types>'''


def _rels(items: list[tuple[str, str, str, bool]]) -> str:
    body = []
    for rel_id, rel_type, target, external in items:
        external_attr = ' TargetMode="External"' if external else ""
        body.append(
            f'<Relationship Id="{escape(rel_id)}" Type="{escape(rel_type)}" '
            f'Target="{escape(target)}"{external_attr}/>'
        )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Relationships xmlns="{PKG_REL_NS}">\n'
        + "\n".join(body)
        + "\n</Relationships>"
    )


def _styles() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="{W_NS}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="Heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="Heading 2"/><w:basedOn w:val="Heading1"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="CustomHeading"><w:name w:val="Custom Heading"/><w:basedOn w:val="Heading1"/></w:style>
</w:styles>'''


def _numbering() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<w:numbering xmlns:w="{W_NS}">
  <w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="multilevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>'''


def _paragraph(text: str, *, style: str | None = None, num: bool = False) -> str:
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{escape(style)}"/>')
    if num:
        props.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    ppr = "<w:pPr>" + "".join(props) + "</w:pPr>" if props else ""
    return f'<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>'


def _sectpr() -> str:
    return "<w:sectPr/>"


def _document(body: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>{body}</w:body></w:document>'''


def _base_entries(
    document_xml: str,
    *,
    styles: bool = True,
    numbering: bool = False,
    rels: list[tuple[str, str, str, bool]] | None = None,
    extra_parts: dict[str, str | bytes] | None = None,
    extra_types: dict[str, str] | None = None,
    html: bool = False,
) -> dict[str, str | bytes]:
    overrides = {"word/document.xml": MAIN_CT}
    entries: dict[str, str | bytes] = {
        "_rels/.rels": _root_rels(),
        "word/document.xml": document_xml,
    }
    relationship_items: list[tuple[str, str, str, bool]] = []
    if styles:
        entries["word/styles.xml"] = _styles()
        overrides["word/styles.xml"] = STYLES_CT
        relationship_items.append(("rStyles", REL_STYLE, "styles.xml", False))
    if numbering:
        entries["word/numbering.xml"] = _numbering()
        overrides["word/numbering.xml"] = NUMBERING_CT
        relationship_items.append(("rNumbering", REL_NUMBERING, "numbering.xml", False))
    relationship_items.extend(rels or [])
    if relationship_items:
        entries["word/_rels/document.xml.rels"] = _rels(relationship_items)
    if extra_parts:
        entries.update(extra_parts)
    if extra_types:
        overrides.update(extra_types)
    entries["[Content_Types].xml"] = _content_types(overrides, html=html)
    return entries


def _hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _anchor(
    *,
    part: str = "word/document.xml",
    zone: str = "body",
    source_kind: str | None = None,
    occurrence: int | None = None,
    native: tuple[str, str] | None = None,
) -> GoldSourceAnchor:
    return GoldSourceAnchor(
        opc_part=part,
        source_zone=zone,
        source_kind=source_kind,
        occurrence=occurrence,
        source_anchor_kind=native[0] if native else None,
        source_anchor_id=native[1] if native else None,
    )


def _element(
    element_id: str,
    order: int,
    element_type: ElementType,
    text: str | None,
    *,
    anchor: GoldSourceAnchor,
    heading_level: int | None = None,
) -> GoldElement:
    return GoldElement(
        id=element_id,
        order=order,
        anchor=anchor,
        text=text,
        type=element_type,
        heading_level=heading_level,
    )


def _source(file_name: str, payload: bytes, *, document_class: str) -> GoldSourceDescriptor:
    return GoldSourceDescriptor(
        file_name=file_name,
        sha256=_hash(payload),
        language="en",
        document_class=document_class,
        source_kind=BenchmarkSourceKind.GENERATED,
        generator_id=GENERATOR_ID,
        provenance={
            "seed": GENERATOR_SEED,
            "license": "CC0-1.0 generated fixture text",
            "research_basis": [
                "ISO/IEC 29500 WordprocessingML structure",
                "Microsoft Open XML WordprocessingML documentation",
                "DocParser hierarchical document structure evaluation",
                "DocLayNet diversity/annotation guidance",
            ],
        },
    )


def build_case_01() -> GeneratedCase:
    file_name = "01_hierarchy_lists.docx"
    body = "".join([
        _paragraph("System Overview", style="CustomHeading"),
        _paragraph("Benchmark case one narrative paragraph."),
        _paragraph("1.1 Components", style="Heading2"),
        _paragraph("Parser core", num=True),
        _paragraph("Adapter layer", num=True),
        _paragraph("Evaluation harness", num=True),
        _paragraph("1.2 Guarantees", style="Heading2"),
        _paragraph("Source facts remain separate from inferred structure."),
        _sectpr(),
    ])
    payload = _zip(_base_entries(_document(body), styles=True, numbering=True))
    elements = (
        _element("e01", 0, ElementType.HEADING, "System Overview", anchor=_anchor(), heading_level=1),
        _element("e02", 1, ElementType.PARAGRAPH, "Benchmark case one narrative paragraph.", anchor=_anchor()),
        _element("e03", 2, ElementType.HEADING, "1.1 Components", anchor=_anchor(), heading_level=2),
        _element("e04", 3, ElementType.LIST_ITEM, "Parser core", anchor=_anchor()),
        _element("e05", 4, ElementType.LIST_ITEM, "Adapter layer", anchor=_anchor()),
        _element("e06", 5, ElementType.LIST_ITEM, "Evaluation harness", anchor=_anchor()),
        _element("e07", 6, ElementType.HEADING, "1.2 Guarantees", anchor=_anchor(), heading_level=2),
        _element("e08", 7, ElementType.PARAGRAPH, "Source facts remain separate from inferred structure.", anchor=_anchor()),
        _element("e09", 8, ElementType.SEPARATOR, None, anchor=_anchor(source_kind="separator:section_break", occurrence=0)),
    )
    gold = GoldDocumentStructure(
        document_id="docx-pilot-01",
        source=_source(file_name, payload, document_class="technical_report"),
        elements=elements,
        logical_units=(GoldLogicalUnit(id="lu_list", type=LogicalUnitType.LIST_GROUP, element_ids=("e04", "e05", "e06")),),
        evaluated_logical_unit_types=(LogicalUnitType.LIST_GROUP,),
        context_nodes=(
            GoldContextNode(id="ctx1", anchor_element_id="e01", type="HEADING", level=1),
            GoldContextNode(id="ctx2", anchor_element_id="e03", type="HEADING", level=2, parent_id="ctx1"),
            GoldContextNode(id="ctx3", anchor_element_id="e07", type="HEADING", level=2, parent_id="ctx1"),
        ),
        regions=(
            GoldRegion(id="r1", element_ids=("e01", "e02", "e03"), category="narrative"),
            GoldRegion(id="r2", element_ids=("e04", "e05", "e06"), category="list"),
            GoldRegion(id="r3", element_ids=("e07", "e08", "e09"), category="narrative"),
        ),
        expected_structure_mode=StructureMode.HIERARCHICAL,
        expected_structural_ready=True,
        metadata={"focus": "style inheritance, heading hierarchy, list integrity"},
    )
    return GeneratedCase(gold.document_id, file_name, payload, gold, BenchmarkSplit.DEV, ("hierarchy", "styles", "lists"))


def build_case_02() -> GeneratedCase:
    file_name = "02_nested_tables.docx"
    nested = '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Nested X</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    outer = f'''<w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Outer A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Outer B</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Outer C</w:t></w:r></w:p><w:sdt><w:sdtPr><w:tag w:val="nested-table"/></w:sdtPr><w:sdtContent>{nested}</w:sdtContent></w:sdt></w:tc></w:tr>
    </w:tbl>'''
    body = "".join([_paragraph("Data Tables", style="Heading1"), outer, _paragraph("After table narrative."), _sectpr()])
    payload = _zip(_base_entries(_document(body), styles=True))
    elements = (
        _element("e01", 0, ElementType.HEADING, "Data Tables", anchor=_anchor(), heading_level=1),
        _element("e02", 1, ElementType.TABLE, None, anchor=_anchor(source_kind="table", occurrence=0)),
        _element("e03", 2, ElementType.TABLE_ROW, "Outer A\nOuter B", anchor=_anchor(source_kind="table_row")),
        _element("e04", 3, ElementType.TABLE_CELL, "Outer A", anchor=_anchor(source_kind="table_cell")),
        _element("e05", 4, ElementType.TABLE_CELL, "Outer B", anchor=_anchor(source_kind="table_cell")),
        _element("e06", 5, ElementType.TABLE_ROW, "Outer C", anchor=_anchor(source_kind="table_row")),
        _element("e07", 6, ElementType.TABLE_CELL, "Outer C", anchor=_anchor(source_kind="table_cell")),
        _element("e08", 7, ElementType.TABLE, None, anchor=_anchor(source_kind="table", occurrence=1)),
        _element("e09", 8, ElementType.TABLE_ROW, "Nested X", anchor=_anchor(source_kind="table_row")),
        _element("e10", 9, ElementType.TABLE_CELL, "Nested X", anchor=_anchor(source_kind="table_cell")),
        _element("e11", 10, ElementType.PARAGRAPH, "After table narrative.", anchor=_anchor()),
        _element("e12", 11, ElementType.SEPARATOR, None, anchor=_anchor(source_kind="separator:section_break", occurrence=0)),
    )
    gold = GoldDocumentStructure(
        document_id="docx-pilot-02",
        source=_source(file_name, payload, document_class="table_heavy_report"),
        elements=elements,
        logical_units=(
            GoldLogicalUnit(id="lu_outer", type=LogicalUnitType.TABLE_BLOCK, element_ids=("e02", "e03", "e04", "e05", "e06", "e07")),
            GoldLogicalUnit(id="lu_nested", type=LogicalUnitType.TABLE_BLOCK, element_ids=("e08", "e09", "e10")),
        ),
        evaluated_logical_unit_types=(LogicalUnitType.TABLE_BLOCK,),
        context_nodes=(GoldContextNode(id="ctx1", anchor_element_id="e01", type="HEADING", level=1),),
        regions=(
            GoldRegion(id="r1", element_ids=("e01",), category="narrative"),
            GoldRegion(id="r2", element_ids=("e02", "e03", "e04", "e05", "e06", "e07", "e08", "e09", "e10"), category="table"),
            GoldRegion(id="r3", element_ids=("e11", "e12"), category="narrative"),
        ),
        relations=(GoldRelation(id="rel_nested", type=RelationType.PART_OF, source_id="lu_nested", target_id="lu_outer"),),
        evaluated_relation_types=(RelationType.PART_OF,),
        expected_structure_mode=StructureMode.MIXED,
        expected_structural_ready=True,
        metadata={"focus": "nested table integrity, content-control wrapper, native PART_OF"},
    )
    return GeneratedCase(gold.document_id, file_name, payload, gold, BenchmarkSplit.DEV, ("tables", "nested_table", "content_control"))


def build_case_03() -> GeneratedCase:
    file_name = "03_notes_sections_headers.docx"
    section_para = '''<w:p><w:pPr><w:sectPr><w:type w:val="continuous"/><w:headerReference w:type="default" r:id="rHeader"/><w:footerReference w:type="default" r:id="rFooter"/></w:sectPr></w:pPr><w:r><w:t>Section transition paragraph.</w:t></w:r></w:p>'''
    footnote_ref = '<w:p><w:r><w:t>Main body refers to footnote one.</w:t><w:footnoteReference w:id="1"/></w:r></w:p>'
    endnote_ref = '<w:p><w:r><w:t>See endnote two.</w:t><w:endnoteReference w:id="2"/></w:r></w:p>'
    final_sect = '<w:sectPr><w:headerReference w:type="default" r:id="rHeader"/><w:footerReference w:type="default" r:id="rFooter"/></w:sectPr>'
    body = "".join([_paragraph("Operational Notes", style="Heading1"), footnote_ref, section_para, _paragraph("Second section content."), endnote_ref, final_sect])
    footnotes = f'''<?xml version="1.0" encoding="UTF-8"?><w:footnotes xmlns:w="{W_NS}"><w:footnote w:id="-1"><w:p><w:r><w:t>separator</w:t></w:r></w:p></w:footnote><w:footnote w:id="1"><w:p><w:r><w:t>Footnote one explains the operational note.</w:t></w:r></w:p></w:footnote></w:footnotes>'''
    endnotes = f'''<?xml version="1.0" encoding="UTF-8"?><w:endnotes xmlns:w="{W_NS}"><w:endnote w:id="-1"><w:p><w:r><w:t>separator</w:t></w:r></w:p></w:endnote><w:endnote w:id="2"><w:p><w:r><w:t>Endnote two contains a final clarification.</w:t></w:r></w:p></w:endnote></w:endnotes>'''
    header = f'''<?xml version="1.0" encoding="UTF-8"?><w:hdr xmlns:w="{W_NS}"><w:p><w:r><w:t>Confidential Benchmark Header</w:t></w:r></w:p></w:hdr>'''
    footer = f'''<?xml version="1.0" encoding="UTF-8"?><w:ftr xmlns:w="{W_NS}"><w:p><w:r><w:t>Page Footer Benchmark</w:t></w:r></w:p></w:ftr>'''
    rels = [
        ("rHeader", REL_HEADER, "header1.xml", False),
        ("rFooter", REL_FOOTER, "footer1.xml", False),
        ("rFootnotes", REL_FOOTNOTE, "footnotes.xml", False),
        ("rEndnotes", REL_ENDNOTE, "endnotes.xml", False),
    ]
    extra = {"word/footnotes.xml": footnotes, "word/endnotes.xml": endnotes, "word/header1.xml": header, "word/footer1.xml": footer}
    extra_types = {"word/footnotes.xml": FOOTNOTES_CT, "word/endnotes.xml": ENDNOTES_CT, "word/header1.xml": HEADER_CT, "word/footer1.xml": FOOTER_CT}
    payload = _zip(_base_entries(_document(body), styles=True, rels=rels, extra_parts=extra, extra_types=extra_types))
    elements = (
        _element("e01", 0, ElementType.HEADING, "Operational Notes", anchor=_anchor(), heading_level=1),
        _element("e02", 1, ElementType.PARAGRAPH, "Main body refers to footnote one.", anchor=_anchor()),
        _element("e03", 2, ElementType.PARAGRAPH, "Section transition paragraph.", anchor=_anchor()),
        _element("e04", 3, ElementType.SEPARATOR, None, anchor=_anchor(source_kind="separator:section_break", occurrence=0)),
        _element("e05", 4, ElementType.PARAGRAPH, "Second section content.", anchor=_anchor()),
        _element("e06", 5, ElementType.PARAGRAPH, "See endnote two.", anchor=_anchor()),
        _element("e07", 6, ElementType.SEPARATOR, None, anchor=_anchor(source_kind="separator:section_break", occurrence=1)),
        _element("e08", 7, ElementType.FOOTNOTE, "Footnote one explains the operational note.", anchor=_anchor(part="word/footnotes.xml", zone="footnote", source_kind="note:footnote", native=("footnote", "1"))),
        _element("e09", 8, ElementType.FOOTNOTE, "Endnote two contains a final clarification.", anchor=_anchor(part="word/endnotes.xml", zone="endnote", source_kind="note:endnote", native=("endnote", "2"))),
        _element("e10", 9, ElementType.PARAGRAPH, "Page Footer Benchmark", anchor=_anchor(part="word/footer1.xml", zone="footer")),
        _element("e11", 10, ElementType.PARAGRAPH, "Confidential Benchmark Header", anchor=_anchor(part="word/header1.xml", zone="header")),
    )
    gold = GoldDocumentStructure(
        document_id="docx-pilot-03",
        source=_source(file_name, payload, document_class="policy_document"),
        elements=elements,
        context_nodes=(GoldContextNode(id="ctx1", anchor_element_id="e01", type="HEADING", level=1),),
        regions=(
            GoldRegion(id="r1", element_ids=("e01", "e02", "e03", "e04", "e05", "e06", "e07", "e08", "e09"), category="narrative"),
            GoldRegion(id="r2", element_ids=("e10", "e11"), category="boilerplate"),
        ),
        relations=(
            GoldRelation(id="rel_footnote", type=RelationType.FOOTNOTE_OF, source_id="e08", target_id="e02"),
            GoldRelation(id="rel_endnote", type=RelationType.FOOTNOTE_OF, source_id="e09", target_id="e06"),
        ),
        evaluated_relation_types=(RelationType.FOOTNOTE_OF,),
        expected_structure_mode=StructureMode.LOCAL,
        expected_structural_ready=True,
        metadata={"focus": "notes, paragraph section break, header/footer stories"},
    )
    return GeneratedCase(gold.document_id, file_name, payload, gold, BenchmarkSplit.DEV, ("footnote", "endnote", "section", "header", "footer"))


def build_case_04() -> GeneratedCase:
    file_name = "04_narrative_faq_mixed.docx"
    body = "".join([
        _paragraph("Support Guide", style="Heading1"),
        _paragraph("This guide starts with a short narrative introduction."),
        _paragraph("Q: How do I reset the cache?"),
        _paragraph("A: Open settings and choose Clear Cache."),
        _paragraph("Q: Where are logs stored?"),
        _paragraph("A: Logs are stored in the diagnostics directory."),
        _paragraph("Closing narrative paragraph."),
        _sectpr(),
    ])
    payload = _zip(_base_entries(_document(body), styles=True))
    elements = (
        _element("e01", 0, ElementType.HEADING, "Support Guide", anchor=_anchor(), heading_level=1),
        _element("e02", 1, ElementType.PARAGRAPH, "This guide starts with a short narrative introduction.", anchor=_anchor()),
        _element("e03", 2, ElementType.PARAGRAPH, "Q: How do I reset the cache?", anchor=_anchor()),
        _element("e04", 3, ElementType.PARAGRAPH, "A: Open settings and choose Clear Cache.", anchor=_anchor()),
        _element("e05", 4, ElementType.PARAGRAPH, "Q: Where are logs stored?", anchor=_anchor()),
        _element("e06", 5, ElementType.PARAGRAPH, "A: Logs are stored in the diagnostics directory.", anchor=_anchor()),
        _element("e07", 6, ElementType.PARAGRAPH, "Closing narrative paragraph.", anchor=_anchor()),
        _element("e08", 7, ElementType.SEPARATOR, None, anchor=_anchor(source_kind="separator:section_break", occurrence=0)),
    )
    gold = GoldDocumentStructure(
        document_id="docx-pilot-04",
        source=_source(file_name, payload, document_class="faq_guide"),
        elements=elements,
        logical_units=(
            GoldLogicalUnit(id="lu_qa1", type=LogicalUnitType.QA_PAIR, element_ids=("e03", "e04")),
            GoldLogicalUnit(id="lu_qa2", type=LogicalUnitType.QA_PAIR, element_ids=("e05", "e06")),
        ),
        evaluated_logical_unit_types=(LogicalUnitType.QA_PAIR,),
        context_nodes=(GoldContextNode(id="ctx1", anchor_element_id="e01", type="HEADING", level=1),),
        regions=(
            GoldRegion(id="r1", element_ids=("e01", "e02"), category="narrative"),
            GoldRegion(id="r2", element_ids=("e03", "e04", "e05", "e06"), category="qa"),
            GoldRegion(id="r3", element_ids=("e07", "e08"), category="narrative"),
        ),
        relations=(
            GoldRelation(id="rel_qa1", type=RelationType.QUESTION_ANSWER, source_id="e03", target_id="e04"),
            GoldRelation(id="rel_qa2", type=RelationType.QUESTION_ANSWER, source_id="e05", target_id="e06"),
        ),
        evaluated_relation_types=(RelationType.QUESTION_ANSWER,),
        expected_structure_mode=StructureMode.MIXED,
        expected_structural_ready=True,
        metadata={
            "focus": "lexical QA grouping and grouping-aware region routing",
            "expected_baseline_gap": "QA LogicalUnits can be inferred while region segmentation still sees PARAGRAPH ElementTypes only",
        },
    )
    return GeneratedCase(gold.document_id, file_name, payload, gold, BenchmarkSplit.DEV, ("faq", "qa", "mixed", "known_gap"))


def build_case_05() -> GeneratedCase:
    file_name = "05_revisions_comments_altchunk.docx"
    revision_para = '''<w:p><w:r><w:t>Current statement: </w:t></w:r><w:ins w:id="1" w:author="Benchmark"><w:r><w:t>Approved insertion text</w:t></w:r></w:ins><w:del w:id="2" w:author="Benchmark"><w:r><w:delText>Deleted old text</w:delText></w:r></w:del></w:p>'''
    controlled = f'''<w:sdt><w:sdtPr><w:tag w:val="controlled-value"/><w:alias w:val="Controlled Value"/></w:sdtPr><w:sdtContent>{_paragraph("Controlled content value.")}</w:sdtContent></w:sdt>'''
    commented = '<w:p><w:r><w:t>Commented statement.</w:t><w:commentReference w:id="0"/></w:r></w:p>'
    alt_chunk = '<w:altChunk r:id="rAlt"/>'
    body = "".join([_paragraph("Change Controlled Document", style="Heading1"), revision_para, controlled, commented, alt_chunk, _sectpr()])
    comments = f'''<?xml version="1.0" encoding="UTF-8"?><w:comments xmlns:w="{W_NS}"><w:comment w:id="0" w:author="Benchmark Reviewer" w:date="2026-01-01T00:00:00Z"><w:p><w:r><w:t>Comment zero is valid and must be preserved.</w:t></w:r></w:p></w:comment></w:comments>'''
    alt_html = b"<html><body><p>Opaque imported HTML content.</p></body></html>"
    rels = [("rComments", REL_COMMENTS, "comments.xml", False), ("rAlt", REL_ALTCHUNK, "chunks/alt1.html", False)]
    extra = {"word/comments.xml": comments, "word/chunks/alt1.html": alt_html}
    extra_types = {"word/comments.xml": COMMENTS_CT}
    payload = _zip(_base_entries(_document(body), styles=True, rels=rels, extra_parts=extra, extra_types=extra_types, html=True))
    elements = (
        _element("e01", 0, ElementType.HEADING, "Change Controlled Document", anchor=_anchor(), heading_level=1),
        _element("e02", 1, ElementType.PARAGRAPH, "Current statement: Approved insertion text", anchor=_anchor()),
        _element("e03", 2, ElementType.PARAGRAPH, "Controlled content value.", anchor=_anchor()),
        _element("e04", 3, ElementType.PARAGRAPH, "Commented statement.", anchor=_anchor()),
        _element("e05", 4, ElementType.UNKNOWN, None, anchor=_anchor(source_kind="alt_chunk", occurrence=0)),
        _element("e06", 5, ElementType.SEPARATOR, None, anchor=_anchor(source_kind="separator:section_break", occurrence=0)),
        _element("e07", 6, ElementType.FOOTNOTE, "Comment zero is valid and must be preserved.", anchor=_anchor(part="word/comments.xml", zone="comment", source_kind="note:comment", native=("comment", "0"))),
    )
    gold = GoldDocumentStructure(
        document_id="docx-pilot-05",
        source=_source(file_name, payload, document_class="change_controlled_document"),
        elements=elements,
        context_nodes=(GoldContextNode(id="ctx1", anchor_element_id="e01", type="HEADING", level=1),),
        regions=(
            GoldRegion(id="r1", element_ids=("e01", "e02", "e03", "e04"), category="narrative"),
            GoldRegion(id="r2", element_ids=("e05", "e06"), category="unknown"),
            GoldRegion(id="r3", element_ids=("e07",), category="narrative"),
        ),
        expected_diagnostics=(ExpectedAdapterDiagnostic(code="OPAQUE_ALT_CHUNK", min_count=1, affects_structural_completeness=True),),
        unsupported_constructs=(UnsupportedConstruct(construct_type="altChunk", expected_behavior="PRESERVE_OPAQUE_REFERENCE_AND_DIAGNOSE", expected_diagnostic_code="OPAQUE_ALT_CHUNK"),),
        expected_structure_mode=StructureMode.LOCAL,
        expected_structural_ready=False,
        metadata={"focus": "revision view, content control, comment id 0, opaque altChunk"},
    )
    return GeneratedCase(gold.document_id, file_name, payload, gold, BenchmarkSplit.TEST, ("revisions", "comments", "content_control", "altchunk", "unsupported"))


BUILDERS: tuple[Callable[[], GeneratedCase], ...] = (
    build_case_01,
    build_case_02,
    build_case_03,
    build_case_04,
    build_case_05,
)


def build_pilot_cases() -> tuple[GeneratedCase, ...]:
    return tuple(builder() for builder in BUILDERS)


def build_manifest(cases: tuple[GeneratedCase, ...]) -> BenchmarkManifest:
    return BenchmarkManifest(
        name="DOCX Structure Gold Benchmark V0.1 Pilot",
        generator_id=GENERATOR_ID,
        generator_seed=GENERATOR_SEED,
        cases=tuple(
            BenchmarkCase(
                document_id=item.document_id,
                source_file=f"documents/{item.file_name}",
                annotation_file=f"annotations/{item.document_id}.json",
                sha256=item.gold.source.sha256,
                split=item.split,
                tags=item.tags,
            )
            for item in cases
        ),
        metadata={
            "pilot": True,
            "case_count": len(cases),
            "source_files_are_deterministically_generated": True,
        },
    )


def materialize(output_dir: Path) -> BenchmarkManifest:
    cases = build_pilot_cases()
    manifest = build_manifest(cases)
    documents = output_dir / "documents"
    annotations = output_dir / "annotations"
    documents.mkdir(parents=True, exist_ok=True)
    annotations.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (documents / case.file_name).write_bytes(case.payload)
        (annotations / f"{case.document_id}.json").write_text(
            json.dumps(case.gold.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "materialized",
    )
    args = parser.parse_args()
    manifest = materialize(args.output)
    print(
        json.dumps(
            {
                "benchmark": manifest.name,
                "version": manifest.benchmark_version,
                "cases": len(manifest.cases),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
