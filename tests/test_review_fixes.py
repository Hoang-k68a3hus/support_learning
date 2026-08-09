from __future__ import annotations

import io
import unittest
import zipfile
from datetime import UTC, datetime

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.completion import UnderstandingCompletionBuilder
from source_understanding.pipeline import SourceUnderstandingPipeline
from source_understanding.retrieval_units.builder import (
    RetrievalStrategy,
    RetrievalUnitBuilder,
)
from source_understanding.schemas.context import StructureMode, StructureSource
from source_understanding.schemas.document import (
    CanonicalDocument,
    ContentRegion,
    DocumentStructure,
    ProcessingManifest,
)
from source_understanding.schemas.element import (
    Element,
    ElementType,
    Provenance,
    SourceLocation,
)
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.schemas.retrieval_unit import SourceAnchor
from source_understanding.source_attributes import SOURCE_ZONE_ATTRIBUTE


HASH = "sha256:" + "a" * 64
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
</Types>"""


def make_docx(document: str, *, header: str | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        if header is not None:
            archive.writestr(
                "word/_rels/document.xml.rels",
                """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                <Relationship Id="rHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
                </Relationships>""",
            )
            archive.writestr("word/header1.xml", header)
    return output.getvalue()


def tokens(text: str) -> int:
    return max(1, len(text.split()))


def provenance() -> Provenance:
    return Provenance(
        source=StructureSource.EXPLICIT,
        extractor="review-test",
        confidence=1.0,
    )


def element(
    element_id: str,
    order: int,
    text: str,
    *,
    location: SourceLocation | None = None,
) -> Element:
    return Element(
        id=element_id,
        type=ElementType.PARAGRAPH,
        order=order,
        raw_text=text,
        normalized_text=text,
        location=location,
        provenance=provenance(),
    )


def logical(unit_id: str, element_ids: tuple[str, ...], *, region_id: str | None = None) -> LogicalUnit:
    return LogicalUnit(
        id=unit_id,
        type=LogicalUnitType.TEXT_BLOCK,
        element_ids=element_ids,
        region_id=region_id,
        source=StructureSource.DERIVED,
        confidence=1.0,
    )


def document(
    elements: tuple[Element, ...],
    *,
    units: tuple[LogicalUnit, ...] = (),
    regions: tuple[ContentRegion, ...] = (),
    mode: StructureMode = StructureMode.FLAT,
) -> CanonicalDocument:
    return CanonicalDocument(
        document_id="doc",
        content_hash=HASH,
        source_revision="rev1",
        processing=ProcessingManifest(
            adapter_name="review-test",
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        ),
        structure=DocumentStructure(
            mode=mode,
            source=StructureSource.DERIVED,
            confidence=1.0,
        ),
        elements=elements,
        logical_units=units,
        regions=regions,
    )


class CountingCompletionBuilder(UnderstandingCompletionBuilder):
    def __init__(self) -> None:
        self.calls = 0

    def build(self, *args: object, **kwargs: object):
        self.calls += 1
        return super().build(*args, **kwargs)


class ReviewFixRegressionTests(unittest.TestCase):
    def test_unsupported_docx_block_preserves_text_as_opaque_element(self) -> None:
        payload = make_docx(
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body>
              <w:customBlock><w:p><w:r><w:t>Opaque payload</w:t></w:r></w:p></w:customBlock>
            </w:body></w:document>"""
        )
        adapted = DocxAdapter().adapt(payload)
        opaque = next(
            item
            for item in adapted.raw_elements
            if item.attributes.get("opaque_block_local_name") == "customBlock"
        )
        self.assertEqual(opaque.type_hint, "UNKNOWN")
        self.assertEqual(opaque.text, "Opaque payload")
        diagnostic = next(
            item
            for item in adapted.diagnostics
            if item.code == "UNHANDLED_BLOCK_CUSTOMBLOCK"
        )
        self.assertTrue(diagnostic.affects_structural_completeness)
        self.assertTrue(diagnostic.metadata["text_preserved"])

        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="opaque-docx",
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
        self.assertTrue(
            any(
                item.raw_text == "Opaque payload"
                for item in result.understanding.document.elements
            )
        )
        self.assertFalse(result.understanding.completion_report.structural_ready)
        self.assertGreater(
            result.understanding.completion_report.metrics.adapter_structural_issue_count,
            0,
        )

    def test_header_is_preserved_canonically_but_excluded_from_retrieval(self) -> None:
        payload = make_docx(
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
            <w:body>
              <w:p><w:r><w:t>Main body</w:t></w:r></w:p>
              <w:sectPr><w:headerReference w:type="default" r:id="rHeader"/></w:sectPr>
            </w:body></w:document>""",
            header="""<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:p><w:r><w:t>Repeated header</w:t></w:r></w:p>
            </w:hdr>""",
        )
        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="header-docx",
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
        canonical = result.understanding.document
        header_ids = {
            item.id
            for item in canonical.elements
            if item.attributes.get(SOURCE_ZONE_ATTRIBUTE) == "header"
        }
        self.assertTrue(header_ids)
        self.assertTrue(any(item.raw_text == "Repeated header" for item in canonical.elements))

        projected = RetrievalUnitBuilder(tokens).build(canonical)
        self.assertTrue(header_ids.issubset(projected.skipped_excluded_element_ids))
        self.assertFalse(
            any(
                header_ids.intersection(unit.element_ids)
                for unit in projected.units
            )
        )
        self.assertTrue(any("Main body" in unit.retrieval_text for unit in projected.units))

    def test_table_projection_uses_cells_without_row_text_duplication(self) -> None:
        payload = make_docx(
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:tbl><w:tr>
              <w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>
              <w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc>
            </w:tr></w:tbl></w:body></w:document>"""
        )
        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="table-docx",
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
        projected = RetrievalUnitBuilder(tokens).build(result.understanding.document)
        table_unit = next(unit for unit in projected.units if unit.unit_type.value == "TABLE")
        self.assertEqual(table_unit.display_text, "Cell A\tCell B")
        self.assertEqual(table_unit.retrieval_text, "Cell A\tCell B")
        self.assertEqual(table_unit.retrieval_text.count("Cell A"), 1)
        self.assertEqual(table_unit.retrieval_text.count("Cell B"), 1)
        self.assertEqual(table_unit.metadata["content_projection"], "table_cells")

    def test_known_region_strategy_applies_without_global_mixed_mode(self) -> None:
        item = element("e0", 0, "Local content")
        region = ContentRegion(
            id="r0",
            element_ids=(item.id,),
            structure=DocumentStructure(
                mode=StructureMode.LOCAL,
                source=StructureSource.DERIVED,
                confidence=0.9,
            ),
            source=StructureSource.DERIVED,
            confidence=0.9,
        )
        canonical = document(
            (item,),
            units=(logical("u0", (item.id,), region_id=region.id),),
            regions=(region,),
            mode=StructureMode.FLAT,
        )
        projected = RetrievalUnitBuilder(tokens).build(canonical)
        self.assertEqual(projected.strategy, RetrievalStrategy.FLAT)
        self.assertEqual(projected.units[0].metadata["strategy"], "LOCAL")

    def test_fallback_element_uses_containing_region_strategy(self) -> None:
        item = element("e0", 0, "Grouped content")
        region = ContentRegion(
            id="r0",
            element_ids=(item.id,),
            structure=DocumentStructure(
                mode=StructureMode.GROUPED,
                source=StructureSource.DERIVED,
                confidence=0.9,
            ),
            source=StructureSource.DERIVED,
            confidence=0.9,
        )
        projected = RetrievalUnitBuilder(tokens).build(
            document((item,), regions=(region,), mode=StructureMode.FLAT)
        )
        self.assertEqual(projected.units[0].metadata["strategy"], "GROUPED")

    def test_sourced_canonical_location_projects_to_source_anchor(self) -> None:
        item = element(
            "e0",
            0,
            "located",
            location=SourceLocation(
                source=StructureSource.EXPLICIT,
                page=3,
                start_char=4,
                end_char=11,
            ),
        )
        canonical = document((item,), units=(logical("u0", (item.id,)),))
        unit = RetrievalUnitBuilder(tokens).build(canonical).units[0]
        anchor = unit.source_anchors[0]
        self.assertEqual(anchor.location_source, StructureSource.EXPLICIT)
        self.assertEqual(anchor.page, 3)
        self.assertEqual(anchor.start_char, 4)
        self.assertEqual(anchor.end_char, 11)
        self.assertEqual(unit.metadata["location_projection"], "canonical_source_location")

    def test_unsourced_location_stays_identity_only_and_cannot_be_forged(self) -> None:
        item = element(
            "e0",
            0,
            "legacy location",
            location=SourceLocation(page=3, start_char=4, end_char=19),
        )
        canonical = document((item,), units=(logical("u0", (item.id,)),))
        unit = RetrievalUnitBuilder(tokens).build(canonical).units[0]
        anchor = unit.source_anchors[0]
        self.assertIsNone(anchor.location_source)
        self.assertIsNone(anchor.page)
        self.assertEqual(unit.metadata["location_projection"], "element_identity_only")

        forged_anchor = SourceAnchor(
            source_id=canonical.document_id,
            content_hash=canonical.content_hash,
            source_revision=canonical.source_revision,
            element_id=item.id,
            location_source=StructureSource.EXPLICIT,
            page=3,
        )
        forged_unit = unit.model_copy(update={"source_anchors": (forged_anchor,)})
        with self.assertRaisesRegex(ValueError, "cannot claim location provenance"):
            forged_unit.validate_against_document(canonical)

    def test_completion_builder_has_one_owner_and_receives_adapter_diagnostics(self) -> None:
        payload = make_docx(
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:customBlock><w:p><w:r><w:t>Opaque</w:t></w:r></w:p></w:customBlock></w:body>
            </w:document>"""
        )
        counting = CountingCompletionBuilder()
        runner = SourceAdapterRunner(completion_builder=counting)
        result = runner.understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id="completion-owner",
            processed_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
        self.assertEqual(counting.calls, 1)
        self.assertGreater(
            result.understanding.completion_report.metrics.adapter_structural_issue_count,
            0,
        )

        with self.assertRaisesRegex(ValueError, "completion_builder"):
            SourceAdapterRunner(
                pipeline=SourceUnderstandingPipeline(),
                completion_builder=UnderstandingCompletionBuilder(),
            )


if __name__ == "__main__":
    unittest.main()
