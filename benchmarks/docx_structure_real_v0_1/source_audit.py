from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from io import BytesIO
from xml.etree import ElementTree as ET

from ._corpus import SOURCES, _download


AUDIT_VERSION = "real-docx-independent-ooxml-audit:2"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
R = "{" + R_NS + "}"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL = "{" + RELS_NS + "}"


def _source(source_id: str) -> dict[str, object]:
    for item in SOURCES:
        if item["id"] == source_id:
            return item
    raise SystemExit(f"unknown source id: {source_id}")


def _text(node: ET.Element) -> str:
    chunks: list[str] = []
    for child in node.iter():
        local = child.tag.rsplit("}", 1)[-1]
        if local == "t" and child.text:
            chunks.append(child.text)
        elif local == "tab":
            chunks.append("\t")
        elif local in {"br", "cr"}:
            chunks.append("\n")
    return "".join(chunks)


def _style_catalog(archive: zipfile.ZipFile) -> dict[str, dict[str, object]]:
    if "word/styles.xml" not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read("word/styles.xml"))
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for style in root.findall(W + "style"):
        style_id = style.attrib.get(W + "styleId")
        if not style_id:
            continue
        name_node = style.find(W + "name")
        based = style.find(W + "basedOn")
        outline = style.find(W + "pPr/" + W + "outlineLvl")
        grouped[style_id].append(
            {
                "name": None if name_node is None else name_node.attrib.get(W + "val"),
                "based_on": None if based is None else based.attrib.get(W + "val"),
                "outline": None if outline is None else outline.attrib.get(W + "val"),
            }
        )
    merged: dict[str, dict[str, object]] = {}
    for style_id, defs in grouped.items():
        names = [item["name"] for item in defs if item["name"]]
        based = [item["based_on"] for item in defs if item["based_on"]]
        outlines = [item["outline"] for item in defs if item["outline"] is not None]
        merged[style_id] = {
            "name": names[-1] if names else None,
            "based_on": based[-1] if based else None,
            "outline": outlines[-1] if outlines else None,
            "definition_count": len(defs),
        }
    return merged


def _normalized_style_token(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s_-]+", "", value).casefold()


def _navigation_role(
    style_id: str | None,
    styles: dict[str, dict[str, object]],
) -> str | None:
    style = styles.get(style_id or "", {})
    keys = {
        _normalized_style_token(style_id),
        _normalized_style_token(style.get("name")),
    }
    if keys & {"tocheading", "tableofcontentsheading"}:
        return "toc_title"
    if any(
        re.fullmatch(r"toc[1-9]", key)
        or re.fullmatch(r"tableofcontents[1-9]", key)
        for key in keys
        if key
    ):
        return "toc_entry"
    return None


def _heading_level(style_id: str | None, styles: dict[str, dict[str, object]]) -> int | None:
    if not style_id:
        return None
    seen: set[str] = set()
    current = style_id
    while current and current not in seen:
        seen.add(current)
        item = styles.get(current)
        if item is None:
            break
        outline = item.get("outline")
        if isinstance(outline, str) and outline.isdigit():
            value = int(outline) + 1
            if 1 <= value <= 9:
                return value
        name = item.get("name")
        if isinstance(name, str):
            match = re.fullmatch(r"heading\s*([1-9])", name.strip(), re.IGNORECASE)
            if match:
                return int(match.group(1))
        based_on = item.get("based_on")
        current = based_on if isinstance(based_on, str) else ""
    match = re.fullmatch(r"Heading([1-9])", style_id, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _relationships(archive: zipfile.ZipFile, rel_path: str) -> dict[str, tuple[str, str]]:
    if rel_path not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read(rel_path))
    output: dict[str, tuple[str, str]] = {}
    for node in root.findall(REL + "Relationship"):
        rel_id = node.attrib.get("Id")
        target = node.attrib.get("Target")
        rel_type = node.attrib.get("Type")
        if rel_id and target and rel_type:
            output[rel_id] = (rel_type.rsplit("/", 1)[-1], target)
    return output


def _iter_blocks(parent: ET.Element):
    for child in list(parent):
        local = child.tag.rsplit("}", 1)[-1]
        if local in {"p", "tbl", "sectPr", "altChunk"}:
            yield child
        elif local in {"sdt", "customXml", "ins", "del", "moveFrom", "moveTo"}:
            container = child.find(W + "sdtContent") if local == "sdt" else child
            if container is not None:
                yield from _iter_blocks(container)


def _paragraph_record(node: ET.Element, styles: dict[str, dict[str, object]]) -> dict[str, object]:
    ppr = node.find(W + "pPr")
    style_id = None
    if ppr is not None:
        style = ppr.find(W + "pStyle")
        if style is not None:
            style_id = style.attrib.get(W + "val")
    return {
        "text": _text(node),
        "style_id": style_id,
        "heading_level": _heading_level(style_id, styles),
        "navigation_role": _navigation_role(style_id, styles),
        "has_numPr": ppr is not None and ppr.find(W + "numPr") is not None,
    }


def _table_shape(node: ET.Element) -> dict[str, object]:
    rows = [child for child in list(node) if child.tag == W + "tr"]
    row_cells = [
        [_text(child) for child in list(row) if child.tag == W + "tc"]
        for row in rows
    ]
    cell_counts = [len(cells) for cells in row_cells]
    return {
        "rows": len(rows),
        "cells": sum(cell_counts),
        "cells_per_row": cell_counts,
        "row_cells": row_cells,
    }


def _story_audit(
    root: ET.Element,
    styles: dict[str, dict[str, object]],
    *,
    opc_part: str,
) -> dict[str, object]:
    paragraphs: list[dict[str, object]] = []
    tables: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = []
    section_count = 0
    alt_chunk_count = 0
    for block_index, block in enumerate(_iter_blocks(root)):
        local = block.tag.rsplit("}", 1)[-1]
        locator = {
            "opc_part": opc_part,
            "top_level_block_index": block_index,
            "provenance": "DERIVED",
        }
        if local == "p":
            paragraph = _paragraph_record(block, styles)
            paragraphs.append(paragraph)
            blocks.append(
                {
                    "kind": "paragraph",
                    "audit_locator": locator,
                    **paragraph,
                }
            )
            ppr = block.find(W + "pPr")
            if ppr is not None and ppr.find(W + "sectPr") is not None:
                section_count += 1
        elif local == "tbl":
            table = _table_shape(block)
            tables.append(table)
            blocks.append(
                {
                    "kind": "table",
                    "audit_locator": locator,
                    **table,
                }
            )
        elif local == "sectPr":
            section_count += 1
            blocks.append(
                {
                    "kind": "section_properties",
                    "audit_locator": locator,
                }
            )
        elif local == "altChunk":
            alt_chunk_count += 1
            blocks.append(
                {
                    "kind": "alt_chunk",
                    "audit_locator": locator,
                    "relationship_id": block.attrib.get(R + "id"),
                }
            )
    headings = [
        item
        for item in paragraphs
        if item["heading_level"] is not None and item["navigation_role"] is None
    ]
    navigation = [item for item in paragraphs if item["navigation_role"] is not None]
    return {
        "opc_part": opc_part,
        "ordered_blocks": blocks,
        "paragraph_count": len(paragraphs),
        "nonempty_paragraph_count": sum(1 for item in paragraphs if str(item["text"]).strip()),
        "headings": headings,
        "navigation": navigation,
        "tables": tables,
        "section_property_count": section_count,
        "alt_chunk_count": alt_chunk_count,
    }


def audit_payload(
    source: dict[str, object],
    payload: bytes,
) -> dict[str, object]:
    """Audit one already-resolved source revision without using production code."""

    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        styles = _style_catalog(archive)
        document = ET.fromstring(archive.read("word/document.xml"))
        body = document.find(W + "body")
        if body is None:
            raise RuntimeError("word/document.xml has no body")
        result: dict[str, object] = {
            "audit_version": AUDIT_VERSION,
            "id": source["id"],
            "bytes": len(payload),
            "sha256": digest,
            "body": _story_audit(body, styles, opc_part="word/document.xml"),
            "style_duplicate_counts": {
                key: int(value["definition_count"])
                for key, value in styles.items()
                if int(value["definition_count"]) > 1
            },
        }
        rels = _relationships(archive, "word/_rels/document.xml.rels")
        referenced_parts: list[dict[str, str]] = []
        for node in document.iter():
            local = node.tag.rsplit("}", 1)[-1]
            if local not in {"headerReference", "footerReference"}:
                continue
            rel_id = node.attrib.get(R + "id")
            if not rel_id or rel_id not in rels:
                continue
            kind, target = rels[rel_id]
            part = "word/" + target.lstrip("/")
            referenced_parts.append({"kind": kind, "part": part})
        stories: dict[str, object] = {}
        for item in referenced_parts:
            part = item["part"]
            if part in archive.namelist():
                stories[part] = _story_audit(
                    ET.fromstring(archive.read(part)),
                    styles,
                    opc_part=part,
                )
        result["referenced_header_footer_stories"] = stories

        notes: dict[str, object] = {}
        for kind, part in (("footnote", "word/footnotes.xml"), ("endnote", "word/endnotes.xml"), ("comment", "word/comments.xml")):
            if part not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(part))
            ids: list[str] = []
            note_stories: list[dict[str, object]] = []
            for node in list(root):
                note_id = node.attrib.get(W + "id")
                if note_id is None:
                    continue
                if kind in {"footnote", "endnote"} and note_id in {"-1", "0"}:
                    continue
                ids.append(note_id)
                note_stories.append(
                    {
                        "id": note_id,
                        "story": _story_audit(
                            node,
                            styles,
                            opc_part=part,
                        ),
                    }
                )
            notes[kind] = {
                "count": len(ids),
                "ids": ids,
                "stories": note_stories,
            }
        result["notes"] = notes
        result["raw_tag_counts"] = dict(
            sorted(Counter(node.tag.rsplit("}", 1)[-1] for node in document.iter()).items())
        )
        return result


def audit_source(source: dict[str, object]) -> dict[str, object]:
    return audit_payload(source, _download(str(source["url"])))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    result = audit_source(_source(args.source))
    print("REAL_DOCX_SOURCE_AUDIT_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
