from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from source_understanding.adapters.docx import DocxAdapter
from source_understanding.adapters.runner import SourceAdapterRunner


FIXED_EVALUATION_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)
USER_AGENT = "support-learning-structure-benchmark/0.1 (+https://github.com/Hoang-k68a3hus/support_learning)"

SOURCES = (
    {
        "id": "real-docx-01-flexible-policy",
        "file_name": "example-flexible-working-policy.docx",
        "document_class": "policy_template",
        "url": "https://improve-workload-and-wellbeing-for-school-staff.education.gov.uk/assets/files/example-flexible-working-policy.docx",
        "source_page": "https://improve-workload-and-wellbeing-for-school-staff.education.gov.uk/flexible-working-toolkit/create-a-flexible-working-strategy/example-flexible-working-policy/",
        "license": "Open Government Licence v3.0",
    },
    {
        "id": "real-docx-02-academy-form",
        "file_name": "Academy_trust_chair_suitability_check_application_form_-_July_2025.docx",
        "document_class": "application_form",
        "url": "https://assets.publishing.service.gov.uk/media/685e5f6362b2e559cbd75333/Academy_trust_chair_suitability_check_application_form_-_July_2025.docx",
        "source_page": "https://www.gov.uk/government/publications/academy-trust-chair-suitability-checks/academy-trust-chair-suitability-checks-guidance-for-applicants",
        "license": "Open Government Licence v3.0",
    },
    {
        "id": "real-docx-03-ivd-tabular",
        "file_name": "Tabular_Summary_input__template__for_non_marked_IVD_devices_20-8-25.docx",
        "document_class": "table_heavy_template",
        "url": "https://assets.publishing.service.gov.uk/media/68a7290d2f18566482155760/Tabular_Summary_input__template__for_non_marked_IVD_devices_20-8-25.docx",
        "source_page": "https://www.gov.uk/government/publications/clinical-trials-that-include-an-in-vitro-diagnostic-device/clinical-trials-that-include-an-in-vitro-diagnostic-device",
        "license": "Open Government Licence v3.0",
    },
    {
        "id": "real-docx-04-eps-guidance",
        "file_name": "ukceps-guidance-note-data-tables.docx",
        "document_class": "legacy_guidance",
        "url": "https://assets.publishing.service.gov.uk/media/5a7efc74e5274a2e8ab4971f/ukceps-guidance-note-data-tables.docx",
        "source_page": "https://www.gov.uk/government/statistics/employer-perspectives-survey-local-data",
        "license": "Open Government Licence v3.0",
    },
    {
        "id": "real-docx-05-contractor-licence",
        "file_name": "Public_Sector_Contractor_Licence_Template__1_.docx",
        "document_class": "legal_template",
        "url": "https://assets.publishing.service.gov.uk/media/646dde827dd6e70012a9b2b2/Public_Sector_Contractor_Licence_Template__1_.docx",
        "source_page": "https://www.gov.uk/government/publications/project-gigabit-supporting-document-templates",
        "license": "Open Government Licence v3.0",
    },
)


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.openxmlformats-officedocument.wordprocessingml.document,*/*;q=0.8"})
    with urlopen(request, timeout=45) as response:
        payload = response.read()
    if not payload.startswith(b"PK"):
        raise RuntimeError(f"downloaded payload from {url!r} is not an OPC ZIP package")
    return payload


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _package_inventory(payload: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        word_xml = [name for name in names if name.startswith("word/") and name.endswith(".xml")]
        part_counts: Counter[str] = Counter()
        selected_counts: Counter[str] = Counter()
        selected = {
            "p", "tbl", "tr", "tc", "sdt", "ins", "del", "altChunk", "drawing", "pict",
            "oMath", "oMathPara", "footnoteReference", "endnoteReference", "commentReference",
            "hyperlink", "bookmarkStart", "fldChar", "sectPr", "headerReference", "footerReference",
        }
        for name in word_xml:
            try:
                root = ET.fromstring(archive.read(name))
            except ET.ParseError:
                part_counts["xml_parse_error"] += 1
                continue
            part_counts[name] = sum(1 for _ in root.iter())
            for node in root.iter():
                local = _local_name(node.tag)
                if local in selected:
                    selected_counts[local] += 1
        return {
            "package_entry_count": len(names),
            "word_xml_parts": word_xml,
            "selected_ooxml_tag_counts": dict(sorted(selected_counts.items())),
            "part_node_counts": dict(sorted(part_counts.items())),
        }


def _short_text(value: object, limit: int = 180) -> object:
    if not isinstance(value, str):
        return value
    collapsed = value.replace("\r", "\\r").replace("\n", "\\n")
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _element_record(element: object) -> dict[str, object]:
    attrs = dict(getattr(element, "attributes", {}))
    interesting_keys = (
        "opc_part", "source_zone", "heading_level", "style_id", "paragraph_style_id",
        "numbering_id", "numbering_level", "native_integrity_kind", "integrity_group_id",
        "integrity_parent_group_id", "row_index", "cell_index", "separator_kind", "note_kind",
        "source_anchor", "source_references", "alt_chunk_relationship_id", "revision_kind",
        "content_control", "comment_reference_ids", "footnote_reference_ids", "endnote_reference_ids",
    )
    reduced = {key: attrs[key] for key in interesting_keys if key in attrs}
    element_type = getattr(element, "type", None)
    if element_type is None:
        element_type = getattr(element, "type_hint", None)
    if hasattr(element_type, "value"):
        element_type = element_type.value
    return {
        "id": getattr(element, "id", None),
        "order": getattr(element, "order", None),
        "type": element_type,
        "text": _short_text(getattr(element, "raw_text", getattr(element, "text", None))),
        "attributes": reduced,
    }


def _unit_record(unit: object) -> dict[str, object]:
    unit_type = getattr(unit, "type", None)
    if hasattr(unit_type, "value"):
        unit_type = unit_type.value
    return {
        "id": getattr(unit, "id", None),
        "type": unit_type,
        "element_ids": list(getattr(unit, "element_ids", ())),
        "region_id": getattr(unit, "region_id", None),
        "label": getattr(unit, "label", None),
    }


def _context_record(node: object) -> dict[str, object]:
    return {
        "id": getattr(node, "id", None),
        "label": getattr(node, "label", None),
        "level": getattr(node, "level", None),
        "parent_id": getattr(node, "parent_id", None),
        "attributes": dict(getattr(node, "attributes", {})),
    }


def _region_record(region: object) -> dict[str, object]:
    return {
        "id": getattr(region, "id", None),
        "element_ids": list(getattr(region, "element_ids", ())),
        "dominant_type": getattr(region, "dominant_type", None),
        "profile": dict(getattr(region, "profile", {})),
        "metadata": dict(getattr(region, "metadata", {})),
    }


def _relation_record(relation: object) -> dict[str, object]:
    relation_type = getattr(relation, "type", None)
    if hasattr(relation_type, "value"):
        relation_type = relation_type.value
    return {
        "id": getattr(relation, "id", None),
        "type": relation_type,
        "source_id": getattr(relation, "source_id", None),
        "target_id": getattr(relation, "target_id", None),
    }


def discover_source(source: dict[str, str]) -> dict[str, object]:
    payload = _download(source["url"])
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    package = _package_inventory(payload)

    adapter = DocxAdapter()
    adapted = adapter.adapt(payload, source_name=source["file_name"])
    output: dict[str, object] = {
        **source,
        "bytes": len(payload),
        "sha256": digest,
        "package": package,
        "adapter": {
            "raw_element_count": len(adapted.raw_elements),
            "type_counts": dict(sorted(Counter(str(item.type_hint) for item in adapted.raw_elements).items())),
            "diagnostics": [
                {
                    "code": item.code,
                    "level": item.level.value if hasattr(item.level, "value") else str(item.level),
                    "affects_structural_completeness": item.affects_structural_completeness,
                    "message": item.message,
                }
                for item in adapted.diagnostics
            ],
        },
    }

    try:
        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=adapter,
            document_id=source["id"],
            source_name=source["file_name"],
            processed_at=FIXED_EVALUATION_TIME,
        )
    except Exception as exc:  # discovery must report pipeline failures rather than hide sources
        output["pipeline"] = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        # Raw adapter inventory still lets us adjudicate adapter-level failures.
        elements = adapted.raw_elements
        output["elements"] = [_element_record(item) for item in elements]
        return output

    understanding = result.understanding
    document = understanding.document
    output["pipeline"] = {
        "status": "ok",
        "structure_mode": document.structure.mode.value,
        "structural_ready": understanding.completion_report.structural_ready,
        "element_count": len(document.elements),
        "logical_unit_count": len(document.logical_units),
        "context_node_count": len(document.context_nodes),
        "region_count": len(document.regions),
        "relation_count": len(document.relations),
        "quality": document.quality.model_dump(mode="json"),
    }
    output["elements"] = [_element_record(item) for item in document.elements]
    output["logical_units"] = [_unit_record(item) for item in document.logical_units]
    output["context_nodes"] = [_context_record(item) for item in document.context_nodes]
    output["regions"] = [_region_record(item) for item in document.regions]
    output["relations"] = [_relation_record(item) for item in document.relations]
    output["adapter_diagnostics"] = [item.model_dump(mode="json") for item in result.adapter_result.diagnostics]
    return output


def main() -> None:
    report = {"benchmark": "real-docx-v0.1-discovery", "sources": []}
    for source in SOURCES:
        print(f"DISCOVERY_START {source['id']}", flush=True)
        try:
            item = discover_source(source)
        except Exception as exc:
            item = {
                **source,
                "download_or_discovery_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        report["sources"].append(item)
        print("DISCOVERY_SOURCE_JSON=" + json.dumps(item, ensure_ascii=False, sort_keys=True), flush=True)
        print(f"DISCOVERY_END {source['id']}", flush=True)
    print("REAL_DOCX_DISCOVERY_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
