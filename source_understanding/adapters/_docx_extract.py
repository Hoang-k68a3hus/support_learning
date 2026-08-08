from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import Asset
from source_understanding.schemas.element import StyleInfo
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_REFERENCES_ATTRIBUTE,
)

from .base import AdapterDiagnostic, AdapterDiagnosticLevel, AdapterError, SourceAdapterResult
from ._docx_common import (
    A, M, NS, R, W, WP,
    DOCX_ADAPTER_VERSION, DOCX_MEDIA_TYPE, DOCX_POLICY_VERSION,
    DocxAdapterPolicy, Emitter, RevisionView,
    half_points, int_attr, local_name, on_off, stable_group_id,
)
from ._docx_package import DocxPackageMixin


class DocxExtractMixin:
    def _read_document(
        self,
        package: zipfile.ZipFile,
        emitter: Emitter,
        content_hash: str,
        content_types: dict[str, str],
    ) -> None:
        part = "word/document.xml"
        root = self._read_xml(package, part)
        if root is None:
            raise AdapterError("DOCX is missing word/document.xml")
        rels = self._relationships(package, part)
        self._register_assets(package, part, rels, content_hash, content_types)
        body = root.find("w:body", NS)
        if body is None:
            raise AdapterError("DOCX document.xml has no w:body")
        for index, node in enumerate(list(body)):
            self._emit_block(
                package, emitter, node, part=part, zone="body", rels=rels,
                content_hash=content_hash, content_types=content_types,
                path=f"body/{index}", parent_group=None,
            )

    def _emit_block(
        self,
        package: zipfile.ZipFile,
        emitter: Emitter,
        node: ET.Element,
        *,
        part: str,
        zone: str,
        rels: dict[str, object],
        content_hash: str,
        content_types: dict[str, str],
        path: str,
        parent_group: str | None,
        wrappers: tuple[dict[str, object], ...] = (),
    ) -> None:
        name = local_name(node.tag)
        if name == "p":
            self._emit_paragraph(
                emitter, node, part=part, zone=zone, rels=rels, wrappers=wrappers
            )
            return
        if name == "tbl":
            self._emit_table(
                package, emitter, node, part=part, zone=zone, rels=rels,
                content_hash=content_hash, content_types=content_types,
                path=path, parent_group=parent_group, wrappers=wrappers,
            )
            return
        if name == "sectPr":
            attrs = self._section_properties(node, rels)
            emitter.emit(
                text=None, type_hint="SEPARATOR", part=part,
                attributes={"zone": zone, "separator_kind": "section_break", **attrs},
            )
            return
        if name == "altChunk":
            rel_id = node.attrib.get(R + "id")
            rel = rels.get(rel_id) if rel_id else None
            attrs: dict[str, object] = {"zone": zone, "alt_chunk_relationship_id": rel_id}
            if rel is not None:
                attrs["alt_chunk_target"] = rel.target
                if not rel.external:
                    asset_id = self._register_part_asset(
                        package,
                        source_part=part,
                        target_part=rel.target,
                        content_hash=content_hash,
                        content_types=content_types,
                        missing_code="MISSING_ALT_CHUNK_PART",
                    )
                    if asset_id:
                        attrs["asset_ids"] = [asset_id]
            emitter.emit(text=None, type_hint="UNKNOWN", part=part, attributes=attrs)
            self._diagnostics.append(
                AdapterDiagnostic(
                    code="OPAQUE_ALT_CHUNK",
                    message="altChunk is preserved as an opaque referenced source part",
                    affects_structural_completeness=True,
                    part=part,
                    metadata={"relationship_id": rel_id},
                )
            )
            return
        if name in {"sdt", "customXml", "ins", "del", "moveFrom", "moveTo"}:
            revision = name if name in {"ins", "del", "moveFrom", "moveTo"} else None
            if revision and not self._include_revision(revision):
                return
            wrapper = {"kind": name}
            if name == "sdt":
                wrapper.update(self._sdt_properties(node))
            child_container = node.find("w:sdtContent", NS) if name == "sdt" else node
            if child_container is None:
                return
            for i, child in enumerate(list(child_container)):
                if local_name(child.tag) in {"sdtPr", "customXmlPr", "insPr", "delPr"}:
                    continue
                self._emit_block(
                    package, emitter, child, part=part, zone=zone, rels=rels,
                    content_hash=content_hash, content_types=content_types,
                    path=f"{path}/{name}/{i}", parent_group=parent_group,
                    wrappers=(*wrappers, wrapper),
                )
            return
        if name in {"bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd"}:
            return
        self._diagnostics.append(
            AdapterDiagnostic(
                code=f"UNHANDLED_BLOCK_{name.upper()}",
                message="DOCX block-level construct is not structurally interpreted",
                affects_structural_completeness=True,
                part=part,
                metadata={"local_name": name, "path": path},
            )
        )

    def _emit_paragraph(
        self,
        emitter: Emitter,
        paragraph: ET.Element,
        *,
        part: str,
        zone: str,
        rels: dict[str, object],
        wrappers: tuple[dict[str, object], ...] = (),
    ) -> None:
        text = self._paragraph_text(paragraph)
        ppr = paragraph.find("w:pPr", NS)
        style_id = None
        if ppr is not None:
            style_node = ppr.find("w:pStyle", NS)
            if style_node is not None:
                style_id = style_node.attrib.get(W + "val")
        style_def = self._styles.get(style_id) if style_id else None
        num_id, ilvl = self._effective_num_pr(ppr, style_def)
        heading_level = self._heading_level(ppr, style_def)
        is_formula = paragraph.find(".//m:oMath", NS) is not None or paragraph.find(".//m:oMathPara", NS) is not None
        if heading_level is not None:
            type_hint = "HEADING"
        elif num_id is not None:
            type_hint = "LIST_ITEM"
        elif is_formula and not (text or "").strip():
            type_hint = "FORMULA"
        else:
            type_hint = "PARAGRAPH"

        attrs: dict[str, object] = {"zone": zone}
        if style_id:
            attrs["paragraph_style_id"] = style_id
        if style_def and style_def.name:
            attrs["paragraph_style_name"] = style_def.name
        if heading_level is not None:
            attrs[HEADING_LEVEL_ATTRIBUTE] = heading_level
        if num_id is not None:
            attrs["numbering_id"] = num_id
            attrs["numbering_level"] = ilvl
            list_key = (part, zone)
            previous = self._list_run.get(list_key)
            if previous is None or previous[0] != num_id:
                group_id = stable_group_id("list", part, zone, num_id, str(len(emitter.elements)))
                self._list_run[list_key] = (num_id, group_id)
            else:
                group_id = previous[1]
            attrs[INTEGRITY_GROUP_ID_ATTRIBUTE] = group_id
            level = self._numbering.get((num_id, ilvl))
            if level:
                attrs["number_format"] = level.num_format
                attrs["number_level_text"] = level.level_text
        else:
            self._list_run.pop((part, zone), None)
        refs = self._source_references(paragraph)
        if refs:
            attrs[SOURCE_REFERENCES_ATTRIBUTE] = refs
        hyperlinks = self._hyperlinks(paragraph, rels)
        if hyperlinks:
            attrs["hyperlinks"] = hyperlinks
        bookmarks = self._bookmarks(paragraph)
        if bookmarks:
            attrs["bookmarks"] = bookmarks
        comments = self._reference_ids(paragraph, "commentReference")
        if comments:
            attrs["comment_reference_ids"] = comments
        field_instructions = self._field_instructions(paragraph)
        if field_instructions:
            attrs["field_instructions"] = field_instructions
        breaks = self._explicit_breaks(paragraph)
        if breaks:
            attrs["explicit_breaks"] = breaks
        asset_ids = self._asset_ids_in_node(paragraph, part)
        if asset_ids:
            attrs["asset_ids"] = asset_ids
        alt_text = self._drawing_alt_text(paragraph)
        if alt_text:
            attrs["drawing_alt_text"] = alt_text
        if wrappers:
            attrs["source_wrappers"] = list(wrappers)
        revisions = self._revision_info(paragraph)
        if revisions:
            attrs["revisions"] = revisions
        style = self._style_info(paragraph, style_def)
        emitter.emit(
            text=text,
            type_hint=type_hint,
            part=part,
            attributes=attrs,
            style=style,
        )

    def _emit_table(
        self,
        package: zipfile.ZipFile,
        emitter: Emitter,
        table: ET.Element,
        *,
        part: str,
        zone: str,
        rels: dict[str, object],
        content_hash: str,
        content_types: dict[str, str],
        path: str,
        parent_group: str | None,
        wrappers: tuple[dict[str, object], ...] = (),
    ) -> None:
        group_id = stable_group_id("table", part, zone, path)
        base_attrs: dict[str, object] = {
            "zone": zone,
            INTEGRITY_GROUP_ID_ATTRIBUTE: group_id,
            "native_integrity_kind": "table",
        }
        if parent_group:
            base_attrs[INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE] = parent_group
        if wrappers:
            base_attrs["source_wrappers"] = list(wrappers)
        emitter.emit(text=None, type_hint="TABLE", part=part, attributes=base_attrs)
        for row_index, (row, row_wrappers) in enumerate(self._iter_wrapped(table, "tr")):
            row_attrs = {**base_attrs, "row_index": row_index}
            if row_wrappers:
                row_attrs["source_wrappers"] = [*wrappers, *row_wrappers]
            emitter.emit(
                text=self._node_text(row), type_hint="TABLE_ROW", part=part,
                attributes=row_attrs,
            )
            for cell_index, (cell, cell_wrappers) in enumerate(self._iter_wrapped(row, "tc")):
                cell_attrs = {
                    **base_attrs,
                    "row_index": row_index,
                    "cell_index": cell_index,
                }
                tcpr = cell.find("w:tcPr", NS)
                if tcpr is not None:
                    span = tcpr.find("w:gridSpan", NS)
                    if span is not None and span.attrib.get(W + "val"):
                        cell_attrs["grid_span"] = span.attrib[W + "val"]
                    vmerge = tcpr.find("w:vMerge", NS)
                    if vmerge is not None:
                        cell_attrs["vertical_merge"] = vmerge.attrib.get(W + "val", "continue")
                if cell_wrappers:
                    cell_attrs["source_wrappers"] = [*wrappers, *row_wrappers, *cell_wrappers]
                emitter.emit(
                    text=self._node_text(cell), type_hint="TABLE_CELL", part=part,
                    attributes=cell_attrs,
                )
                for child_index, child in enumerate(list(cell)):
                    if local_name(child.tag) == "tcPr":
                        continue
                    if local_name(child.tag) == "tbl":
                        self._emit_table(
                            package, emitter, child, part=part, zone=zone, rels=rels,
                            content_hash=content_hash, content_types=content_types,
                            path=f"{path}/r{row_index}/c{cell_index}/tbl{child_index}",
                            parent_group=group_id,
                            wrappers=(*wrappers, *row_wrappers, *cell_wrappers),
                        )

    def _iter_wrapped(
        self,
        parent: ET.Element,
        target_name: str,
    ) -> list[tuple[ET.Element, tuple[dict[str, object], ...]]]:
        output: list[tuple[ET.Element, tuple[dict[str, object], ...]]] = []

        def walk(node: ET.Element, wrappers: tuple[dict[str, object], ...]) -> None:
            for child in list(node):
                name = local_name(child.tag)
                if name == target_name:
                    output.append((child, wrappers))
                elif name in {"sdt", "customXml", "ins", "del", "moveFrom", "moveTo"}:
                    revision = name if name in {"ins", "del", "moveFrom", "moveTo"} else None
                    if revision and not self._include_revision(revision):
                        continue
                    wrapper = {"kind": name}
                    if name == "sdt":
                        wrapper.update(self._sdt_properties(child))
                    container = child.find("w:sdtContent", NS) if name == "sdt" else child
                    if container is not None:
                        walk(container, (*wrappers, wrapper))
        walk(parent, ())
        return output

    def _read_notes(
        self,
        package: zipfile.ZipFile,
        emitter: Emitter,
        part: str,
        kind: str,
    ) -> None:
        root = self._read_xml(package, part)
        if root is None:
            return
        tag = {"footnote": "footnote", "endnote": "endnote", "comment": "comment"}[kind]
        seen: set[str] = set()
        for node in root.findall(f"w:{tag}", NS):
            note_id = node.attrib.get(W + "id")
            if note_id is None or note_id in {"-1", "0"}:
                continue
            if note_id in seen:
                raise AdapterError(f"duplicate {kind} id {note_id!r}")
            seen.add(note_id)
            complex_names = {
                local_name(item.tag)
                for item in node.iter()
                if local_name(item.tag) in {"tbl", "altChunk"}
            }
            if complex_names:
                self._diagnostics.append(
                    AdapterDiagnostic(
                        code=f"{kind.upper()}_COMPLEX_STRUCTURE_FLATTENED",
                        message=f"{kind} text was preserved but nested complex structure was flattened",
                        affects_structural_completeness=True,
                        part=part,
                        metadata={"id": note_id, "constructs": sorted(complex_names)},
                    )
                )
            attrs: dict[str, object] = {
                "zone": kind,
                "note_kind": kind,
                SOURCE_ANCHOR_ATTRIBUTE: {"kind": kind, "id": note_id},
            }
            if kind == "comment":
                author = node.attrib.get(W + "author")
                date = node.attrib.get(W + "date")
                if author:
                    attrs["author"] = author
                if date:
                    attrs["date"] = date
            emitter.emit(
                text=self._node_text(node), type_hint="FOOTNOTE", part=part,
                attributes=attrs,
            )

    def _read_header_footer_parts(
        self,
        package: zipfile.ZipFile,
        emitter: Emitter,
        content_hash: str,
        content_types: dict[str, str],
    ) -> None:
        for part in sorted(self._header_footer_parts):
            root = self._read_xml(package, part)
            if root is None:
                self._diagnostics.append(
                    AdapterDiagnostic(
                        code="MISSING_HEADER_FOOTER_PART",
                        message="referenced DOCX header/footer part is missing",
                        affects_structural_completeness=True,
                        part=part,
                    )
                )
                continue
            zone = "header" if "/header" in part else "footer"
            emitter.emit(
                text=None, type_hint="SEPARATOR", part=part,
                attributes={"zone": zone, "separator_kind": "source_zone_boundary"},
            )
            rels = self._relationships(package, part)
            self._register_assets(package, part, rels, content_hash, content_types)
            for i, child in enumerate(list(root)):
                self._emit_block(
                    package, emitter, child, part=part, zone=zone, rels=rels,
                    content_hash=content_hash, content_types=content_types,
                    path=f"{zone}/{i}", parent_group=None,
                )

    def _section_properties(
        self,
        sect: ET.Element,
        rels: dict[str, object],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        type_node = sect.find("w:type", NS)
        if type_node is not None and type_node.attrib.get(W + "val"):
            result["section_type"] = type_node.attrib[W + "val"]
        pg = sect.find("w:pgSz", NS)
        if pg is not None:
            result["page_size_twips"] = {
                key: value for key in ("w", "h", "orient")
                if (value := pg.attrib.get(W + key)) is not None
            }
        margins = sect.find("w:pgMar", NS)
        if margins is not None:
            result["page_margins_twips"] = {
                key: value for key in ("top", "right", "bottom", "left", "header", "footer", "gutter")
                if (value := margins.attrib.get(W + key)) is not None
            }
        refs: list[dict[str, object]] = []
        for kind in ("headerReference", "footerReference"):
            for ref in sect.findall(f"w:{kind}", NS):
                rel_id = ref.attrib.get(R + "id")
                if not rel_id:
                    continue
                rel = rels.get(rel_id)
                item: dict[str, object] = {
                    "kind": kind.removesuffix("Reference"),
                    "relationship_id": rel_id,
                    "type": ref.attrib.get(W + "type"),
                }
                if rel is not None:
                    item["target"] = rel.target
                    if not rel.external:
                        self._header_footer_parts.add(rel.target)
                refs.append(item)
        if refs:
            result["header_footer_references"] = refs
        return result
