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


class DocxTextMixin:
    def _heading_level(self, ppr: ET.Element | None, style_def: object | None) -> int | None:
        direct = ppr.find("w:outlineLvl", NS) if ppr is not None else None
        level = int_attr(direct, "val")
        if level is None and style_def is not None:
            level = style_def.outline_level
        if level is not None:
            return level + 1
        if style_def is not None and style_def.name:
            match = re.fullmatch(r"Heading\s+(\d+)", style_def.name.strip(), re.I)
            if match:
                return int(match.group(1))
        return None

    def _effective_num_pr(
        self,
        ppr: ET.Element | None,
        style_def: object | None,
    ) -> tuple[str | None, int]:
        direct = ppr.find("w:numPr", NS) if ppr is not None else None
        num_id, ilvl = self._num_pr(direct)
        if num_id == "0":
            # In WordprocessingML, numId=0 explicitly suppresses numbering for
            # this paragraph. Do not inherit a list style or expose it as an
            # active LIST_ITEM downstream.
            return None, 0
        if num_id is not None:
            return num_id, ilvl
        if style_def is not None and style_def.num_id is not None:
            if style_def.num_id == "0":
                return None, 0
            return style_def.num_id, style_def.ilvl or 0
        return None, 0

    def _paragraph_text(self, paragraph: ET.Element) -> str:
        chunks: list[str] = []

        def visit(node: ET.Element, revision: str | None = None) -> None:
            name = local_name(node.tag)
            next_revision = revision
            if name in {"ins", "del", "moveFrom", "moveTo"}:
                next_revision = name
                if not self._include_revision(name):
                    return
            if name in {"t", "delText"} and node.text:
                chunks.append(node.text)
                return
            if name == "tab":
                chunks.append("\t")
                return
            if name in {"br", "cr"}:
                chunks.append("\n")
                return
            for child in list(node):
                visit(child, next_revision)

        visit(paragraph)
        return "".join(chunks)

    def _node_text(self, node: ET.Element) -> str:
        chunks: list[str] = []
        for p in node.findall(".//w:p", NS):
            value = self._paragraph_text(p)
            if value.strip():
                chunks.append(value)
        return "\n".join(chunks)

    def _include_revision(self, revision: str) -> bool:
        view = self.policy.revision_view
        if view == RevisionView.ALL:
            return True
        if view == RevisionView.FINAL:
            return revision in {"ins", "moveTo"}
        return revision in {"del", "moveFrom"}

    def _revision_info(self, paragraph: ET.Element) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for node in paragraph.iter():
            name = local_name(node.tag)
            if name not in {"ins", "del", "moveFrom", "moveTo"}:
                continue
            item: dict[str, object] = {"kind": name, "included": self._include_revision(name)}
            for attr in ("id", "author", "date"):
                value = node.attrib.get(W + attr)
                if value is not None:
                    item[attr] = value
            output.append(item)
        return output

    def _style_info(self, paragraph: ET.Element, style_def: object | None) -> StyleInfo | None:
        ppr = paragraph.find("w:pPr", NS)
        align = None
        indent = None
        if ppr is not None:
            jc = ppr.find("w:jc", NS)
            align = jc.attrib.get(W + "val") if jc is not None else None
            ind = ppr.find("w:ind", NS)
            if ind is not None:
                raw = ind.attrib.get(W + "left") or ind.attrib.get(W + "start")
                if raw:
                    try:
                        indent = float(raw)
                    except ValueError:
                        pass
        bold_values: list[bool] = []
        sizes: list[float] = []
        for rpr in paragraph.findall(".//w:rPr", NS):
            bold = on_off(rpr.find("w:b", NS))
            if bold is not None:
                bold_values.append(bold)
            size = half_points(rpr.find("w:sz", NS))
            if size is not None:
                sizes.append(size)
        bold = True if bold_values and all(bold_values) else None
        font_size = max(sizes) if sizes else None
        if all(value is None for value in (bold, font_size, indent, align)):
            return None
        return StyleInfo(
            bold=bold,
            font_size=font_size,
            indentation=indent,
            alignment=align,
        )

    def _source_references(self, paragraph: ET.Element) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        for local, kind in (("footnoteReference", "footnote"), ("endnoteReference", "endnote")):
            for node in paragraph.findall(f".//w:{local}", NS):
                ref_id = node.attrib.get(W + "id")
                if ref_id is not None:
                    output.append({"kind": kind, "id": ref_id})
        return output

    def _hyperlinks(self, paragraph: ET.Element, rels: dict[str, object]) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for node in paragraph.findall(".//w:hyperlink", NS):
            rel_id = node.attrib.get(R + "id")
            item: dict[str, object] = {"text": self._paragraph_text(node)}
            if rel_id:
                item["relationship_id"] = rel_id
                rel = rels.get(rel_id)
                if rel is not None:
                    item["target"] = rel.target
                    item["external"] = rel.external
            anchor = node.attrib.get(W + "anchor")
            if anchor:
                item["anchor"] = anchor
            output.append(item)
        return output

    def _asset_ids_in_node(self, node: ET.Element, part: str) -> list[str]:
        output: list[str] = []
        for blip in node.findall(".//a:blip", NS):
            rel_id = blip.attrib.get(R + "embed") or blip.attrib.get(R + "link")
            asset_id = self._asset_id_by_rel.get((part, rel_id)) if rel_id else None
            if asset_id and asset_id not in output:
                output.append(asset_id)
        return output

    @staticmethod
    def _drawing_alt_text(node: ET.Element) -> list[str]:
        output: list[str] = []
        for docpr in node.findall(".//wp:docPr", NS):
            for key in ("descr", "title", "name"):
                value = docpr.attrib.get(key)
                if value and value.strip() and value.strip() not in output:
                    output.append(value.strip())
        return output

    @staticmethod
    def _bookmarks(paragraph: ET.Element) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for node in paragraph.findall(".//w:bookmarkStart", NS):
            item: dict[str, object] = {}
            if (value := node.attrib.get(W + "id")) is not None:
                item["id"] = value
            if (value := node.attrib.get(W + "name")) is not None:
                item["name"] = value
            if item:
                output.append(item)
        return output

    @staticmethod
    def _reference_ids(paragraph: ET.Element, local: str) -> list[str]:
        output: list[str] = []
        for node in paragraph.findall(f".//w:{local}", NS):
            value = node.attrib.get(W + "id")
            if value is not None and value not in output:
                output.append(value)
        return output

    @staticmethod
    def _field_instructions(paragraph: ET.Element) -> list[str]:
        output: list[str] = []
        for node in paragraph.findall(".//w:fldSimple", NS):
            value = node.attrib.get(W + "instr")
            if value and value.strip():
                output.append(value.strip())
        for node in paragraph.findall(".//w:instrText", NS):
            if node.text and node.text.strip():
                output.append(node.text.strip())
        return output

    @staticmethod
    def _explicit_breaks(paragraph: ET.Element) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for node in paragraph.findall(".//w:br", NS):
            output.append({
                "type": node.attrib.get(W + "type", "textWrapping"),
                "clear": node.attrib.get(W + "clear"),
            })
        return output

    @staticmethod
    def _sdt_properties(node: ET.Element) -> dict[str, object]:
        props = node.find("w:sdtPr", NS)
        output: dict[str, object] = {}
        if props is None:
            return output
        for tag in ("tag", "alias", "id", "lock"):
            child = props.find(f"w:{tag}", NS)
            if child is not None and (value := child.attrib.get(W + "val")) is not None:
                output[tag] = value
        return output