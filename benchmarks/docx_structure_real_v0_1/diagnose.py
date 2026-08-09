from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import defaultdict
from io import BytesIO
from xml.etree import ElementTree as ET

from source_understanding.adapters.docx import DocxAdapter
from source_understanding.atomic.normalizer import ElementNormalizer
from source_understanding.structure.boundary import BoundaryScorer
from source_understanding.structure.signals import StructureSignalExtractor

from .discover import SOURCES, _download

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _source(source_id: str) -> dict[str, str]:
    for item in SOURCES:
        if item["id"] == source_id:
            return item
    raise SystemExit(f"unknown source id: {source_id}")


def _attr(node: ET.Element | None, name: str) -> str | None:
    return None if node is None else node.attrib.get(W + name)


def duplicate_styles(payload: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        root = ET.fromstring(archive.read("word/styles.xml"))
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for index, style in enumerate(root.findall(W + "style")):
        style_id = _attr(style, "styleId")
        if not style_id:
            continue
        name = style.find(W + "name")
        based_on = style.find(W + "basedOn")
        ppr = style.find(W + "pPr")
        outline = ppr.find(W + "outlineLvl") if ppr is not None else None
        num_pr = ppr.find(W + "numPr") if ppr is not None else None
        num_id = num_pr.find(W + "numId") if num_pr is not None else None
        ilvl = num_pr.find(W + "ilvl") if num_pr is not None else None
        xml = ET.tostring(style, encoding="utf-8")
        grouped[style_id].append(
            {
                "index": index,
                "type": _attr(style, "type"),
                "default": _attr(style, "default"),
                "name": _attr(name, "val"),
                "based_on": _attr(based_on, "val"),
                "outline_level": _attr(outline, "val"),
                "num_id": _attr(num_id, "val"),
                "ilvl": _attr(ilvl, "val"),
                "xml_sha256": hashlib.sha256(xml).hexdigest(),
                "xml_chars": len(xml),
            }
        )
    return {key: values for key, values in grouped.items() if len(values) > 1}


def heading_boundaries(payload: bytes, *, source: dict[str, str]) -> list[dict[str, object]]:
    adapted = DocxAdapter().adapt(payload, source_name=source["file_name"])
    normalized = ElementNormalizer().normalize(adapted.raw_elements, document_id=source["id"])
    elements = normalized.elements
    signals = StructureSignalExtractor().extract(elements)
    boundaries = BoundaryScorer().score(elements, signals).boundaries
    before = {item.right_element_id: item for item in boundaries}
    output = []
    for element in elements:
        if element.type.value != "HEADING":
            continue
        boundary = before.get(element.id)
        output.append(
            {
                "id": element.id,
                "order": element.order,
                "text": element.raw_text,
                "provenance_source": element.provenance.source.value,
                "attributes": dict(element.attributes),
                "before": None
                if boundary is None
                else {
                    "classification": boundary.classification.value,
                    "score": boundary.score,
                    "reasons": [reason.value for reason in boundary.reasons],
                    "components": boundary.components.model_dump(mode="json"),
                },
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    source = _source(args.source)
    payload = _download(source["url"])
    report: dict[str, object] = {
        "id": source["id"],
        "bytes": len(payload),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "duplicate_styles": duplicate_styles(payload),
    }
    try:
        report["headings"] = heading_boundaries(payload, source=source)
    except Exception as exc:
        report["heading_diagnostic_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    print("REAL_DOCX_DIAGNOSE_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
