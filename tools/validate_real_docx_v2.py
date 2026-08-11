from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
import zipfile
from xml.etree import ElementTree as ET

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.schemas.element import ElementType


RECORDS = (
    ("govuk-1a382a0cd581fa47", 39886, "9962f7c7151bc1d8a5ce997f50d983d51ee291ed760a5d9d060a42a0856e6a80", "https://assets.publishing.service.gov.uk/media/69b42cb1cf4af9cad362b40d/form-cic36__6_.docx"),
    ("govuk-1a3f7004eccf30f1", 45863, "2274d4d3bee8aa01e0f6ddc3cad1b32e0a48e216813f194d306fbd0c60f38e0b", "https://assets.publishing.service.gov.uk/media/69b42cfc9d8b52961a62b41a/form-cic36-Welsh-version_7.docx"),
    ("govuk-1fa35c84f6560de7", 87736, "0a36f0ad5ee1a33d104fd9555dfed023da93146fe5006c40a153cfd6d3c5b026", "https://assets.publishing.service.gov.uk/media/662b63c5fee48e2ee6b81e62/_2757029-v2-V3_National_Product_Information_Template.docx"),
    ("govuk-260936eec8588bf8", 258053, "e06b7b755fc9761a664d8ac0efadb22b8ba7f8f9051f86322e47f1d32f8defee", "https://assets.publishing.service.gov.uk/media/66fa5fdbc71e42688b65ee43/DAM_Issue_11.docx"),
    ("govuk-4de5f976159d247e", 107094, "075687121b9da54fb9264eb0366a2a8b18e0e8d11add1b65548c4c5a3c1360a0", "https://assets.publishing.service.gov.uk/media/6a05ebf75f39105e0848a2cb/02_Business_case_template_-_sustain_standard_of_service.docx"),
    ("govuk-534ad485d0bf12f0", 131360, "d018ff12da282030514dd1d25eaa13580612d566322dc59a5b5df26b3b78283a", "https://assets.publishing.service.gov.uk/media/6a05ebe497000cb6073e4e46/01_Business_case_template_-_fulfil_legal_obligations.docx"),
    ("govuk-5819c5f2f717d0ea", 256011, "b93e641b91de25883c28cec5a96134ad8e04b3f8b848895ee0eaf1d65d335f0b", "https://assets.publishing.service.gov.uk/media/5cc6dcabe5274a5a056b699e/10SC_PB_Complaint_FINAL.docx"),
    ("govuk-74e4cc9e1ba73f68", 100801, "261abe1a36ec4ad586dff029ac6935840bd818da3bd2131e9ac90e8de225b311", "https://assets.publishing.service.gov.uk/media/5d53da70e5274a42ce1791d4/Template_Transfer_Agreement__Mutual_.docx.DOCX"),
    ("govuk-7ed2710539785e1a", 406415, "f0dd38ae2a612e07e1cabc433c00df864a5ae9f7db64e6986993c87097261440", "https://assets.publishing.service.gov.uk/media/68a883c7969253904d1557c5/Early_years_employment_reference_template_2025.docx"),
    ("govuk-8145a59a6649c5e4", 618133, "c775f2e040772b3dd9e86b339a65d70e03a6469f62803c02432338e5d1555654", "https://assets.publishing.service.gov.uk/media/653122780b53920013a929ea/Asylum_Support_Application_Form_ASF1.docx"),
    ("govuk-83340b1279435ee6", 63491, "0c749acd6bc17bf6dac8471e650558e9427bc298a813d26b2ef6ceac2b779fa9", "https://assets.publishing.service.gov.uk/media/69a21aa2ec82ce45f05bd71d/Guidance_note_-_Female_Genital_Mutilation__FGM__and_breast_ironing.docx"),
    ("govuk-8517d950b4697554", 114906, "6027a52843818a0b9eb1e593a5e084dc870c39d0335ed81274cc51ba2c115d26", "https://assets.publishing.service.gov.uk/media/6a05ec05da82768016cb3fb7/03_Business_case_template_-_supported_change.docx"),
    ("govuk-88e0e77c8c9568ee", 120110, "57cfa7c5849a6aa992d6a41723ca511ffc781634b439172e752575722dfcdc29", "https://assets.publishing.service.gov.uk/media/6a5e2c5213cf36b2315a5e89/06_Business_case_template_complex_change.docx"),
    ("govuk-93046cdc17685431", 69935, "c08503e3c16871e9039cf4c4a3ee020db5b2710943b1cdab0f7e9cc9e4126bd9", "https://assets.publishing.service.gov.uk/media/5a804135ed915d74e33f95c1/16-17_tariff_consultation_-_survey_questions.docx"),
    ("govuk-97c10db5c1ec700f", 181131, "e318c4622d3c799345fcca28e180a5bea9456ba24311b3095ec201d8e605fdde", "https://assets.publishing.service.gov.uk/media/69a21a75286b6fdc85daeaf9/Guidance_note-_Multiple_facial_fractures.docx"),
    ("govuk-a07b0360611c211f", 25906, "d1697ced30fdc68d599c4120ab612fee5b44e1131178c3d44ae468c5bc73b648", "https://assets.publishing.service.gov.uk/media/6842c549e5a089417c8060aa/form-cic36-cic37-continuation-sheet.docx"),
    ("govuk-a29950ec7a52e550", 109245, "4cc99eca1c1f420c5196516e7fa9e47f3c1d9658a2907e6afae5d685a04ae081", "https://assets.publishing.service.gov.uk/media/5a81a78aed915d74e62336ea/PPN_8_16_StandardSQ_Template_v3.docx"),
    ("govuk-a773d5b58a931eb1", 2879579, "d5bb83fdcff69f9c77014e24b2a60066f608133f7d646beaed53a058e65b5f86", "https://assets.publishing.service.gov.uk/media/5d2da5fced915d2fec6a7aa1/weee-takeback-scheme-members-template.docx"),
    ("govuk-a7dd496f194a6b49", 67954, "aca731acf0eb0b69db4c1a5ee77bb2b6b5e20b83e020424c7ad21b94a7862056", "https://assets.publishing.service.gov.uk/media/67b887a94ad141d9083533da/Report_documentation_page_gov_uk_version.docx"),
    ("govuk-b922596dd80dcc77", 115809, "a5077259565043a943f47112de7e0da1a7ddede0e3dee7f5db5a93e92da7d020", "https://assets.publishing.service.gov.uk/media/686e6ff5fe1a249e937cbebc/impact-assessment-template-2023-reforms.docx"),
    ("govuk-c522040da106dabc", 52597, "5fa99e9cc37fae117a85f5a3bd68ea677d5a72b0be88e2563892415ff80de994", "https://assets.publishing.service.gov.uk/media/69a21a3c01cc32678a5bd72c/Guidance_note-_Scarring.docx"),
    ("govuk-c7c7c4481b8f9adb", 122717, "44f2d90bcb9b51885d00a7c51b05608de3397ba086b415afc12b80e8877a2941", "https://assets.publishing.service.gov.uk/media/6a05ec26c0cc74b4523e4e53/05_Business_case_template_-_SWIM.docx"),
    ("govuk-d2312510ceffc099", 130521, "530c03d2ecdc6c35309f06841435492d4f0fb09e83821a7bb2cbe1c11a89c135", "https://assets.publishing.service.gov.uk/media/69a21a8b286b6fdc85daeafa/Guidance_note-_Physical_abuse_of_children.docx"),
    ("govuk-d2b007806365a31d", 251566, "4cda5f47c038979eea4eca3cbea4a1d37c3257d694abbc1529ee92cb52ca6fad", "https://assets.publishing.service.gov.uk/media/67ed5038e9c76fa33048c6af/MHRA_Clinical_AR_Template.docx"),
    ("govuk-d4218b2c431d339d", 74032, "7ba35da3c165c66af8d177164151a060aaa8bab864c776567d61fafe6ca4d419", "https://assets.publishing.service.gov.uk/media/69cbfdbb2d120d9d5ec0f377/Complaints_Authority_to_Act_form_English__6_.docx"),
    ("govuk-dd47f6fc825ac963", 55062, "b9967d4633ca6f4fdd45391dfa5a1d7e5c8b1d95ede220ef70920f2fa72c0ee7", "https://assets.publishing.service.gov.uk/media/69a21abe286b6fdc85daeafb/Guidance_note-_Assessing_care_needs_and_costs.docx"),
    ("govuk-e5b62304af29d253", 67023, "3d709b94da96e91c83e7c901b3b1dca1b4d1403f0602696eff8c77973d2aae92", "https://assets.publishing.service.gov.uk/media/640067008fa8f527f4f54b37/Applicant_s_response_template.docx"),
    ("govuk-e6e611e8a7a9e2d3", 606206, "70731b6350337c6d66d8d3c99b5715257acd2f7758b47f9b6fe18f2cd6b9a122", "https://assets.publishing.service.gov.uk/media/5a80c289e5274a2e8ab52005/STC_consultation_questionnaire_May_2015.docx"),
    ("govuk-ecf03dad5e682c44", 106259, "848160f9057bd31a27bf62a03d70a176b67144ed0df01ff76ebcc1446c33cce7", "https://assets.publishing.service.gov.uk/media/6810a2f3ddb2b0afb5e041d0/options_assessment_template_2023_reforms.docx"),
    ("govuk-f5722a3c32b94583", 101861, "71fea99a9c73ca88fb144c00a2dc4797bd1d08baeae2e44bc955fcfffebe9def", "https://assets.publishing.service.gov.uk/media/5a7f7e8040f0b62305b877c7/Bribery_and_corruption_assessment_template.docx"),
)

REQUIRED_PARTS = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
EXPECTED_ANCHOR_TYPES = {ElementType.TITLE, ElementType.HEADING, ElementType.SEPARATOR}
INTEGRITY_TYPES = {
    ElementType.TABLE,
    ElementType.TABLE_ROW,
    ElementType.TABLE_CELL,
    ElementType.LIST,
    ElementType.LIST_ITEM,
    ElementType.CODE,
    ElementType.FORMULA,
    ElementType.KEY_VALUE,
}
OUTPUT_DIR = Path("validation")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def download(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "support-learning-real-docx-validation-v2/1.0"})
            with urlopen(request, timeout=45) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - validation harness records exact failure
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def validate_zip(payload: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        missing = REQUIRED_PARTS - names
        if missing:
            raise ValueError(f"missing required OOXML parts: {sorted(missing)}")
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC failure at {bad}")
        if any(name.lower().endswith("vbaproject.bin") for name in names):
            raise ValueError("macro-enabled VBA project found")


def effective_main_table_counts(payload: bytes) -> tuple[int, int, int]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    counts = {"tbl": 0, "tr": 0, "tc": 0}

    def selected_branch(node: ET.Element) -> ET.Element | None:
        children = list(node)
        for wanted in ("Choice", "Fallback"):
            for child in children:
                if local_name(child.tag) == wanted:
                    return child
        return None

    def walk(node: ET.Element) -> None:
        name = local_name(node.tag)
        if name == "AlternateContent":
            branch = selected_branch(node)
            if branch is not None:
                for child in list(branch):
                    walk(child)
            return
        if name in counts:
            counts[name] += 1
        for child in list(node):
            walk(child)

    walk(root)
    return counts["tbl"], counts["tr"], counts["tc"]


def status_priority(status: str) -> int:
    return {"PASS": 0, "WARN": 1, "FAIL": 2, "SKIPPED": 3}.get(status, 4)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    for candidate_id, expected_bytes, expected_sha, url in RECORDS:
        row: dict[str, object] = {
            "candidate_id": candidate_id,
            "overall_status": "PASS",
            "raw_status": "PASS",
            "adapter_status": "PASS",
            "normalizer_status": "PASS",
            "canonical_status": "PASS",
            "l0_status": "PASS",
            "l1_status": "PASS",
            "l2_status": "PASS",
            "l3_status": "PASS",
            "raw_elements": "",
            "canonical_elements": "",
            "logical_units": "",
            "regions": "",
            "structure_mode": "",
            "structural_ready": "",
            "expected_anchor_ungrouped": "",
            "ordinary_content_ungrouped": "",
            "integrity_sensitive_ungrouped": "",
            "unresolved_integrity": "",
            "table_count": "",
            "table_row_count": "",
            "table_cell_count": "",
            "independent_main_tables": "",
            "independent_main_rows": "",
            "independent_main_cells": "",
            "errors": 0,
            "warnings": 0,
        }

        def event(stage: str, severity: str, check: str, message: str) -> None:
            events.append(
                {
                    "candidate_id": candidate_id,
                    "stage": stage,
                    "severity": severity,
                    "check": check,
                    "message": message,
                }
            )
            key = "errors" if severity == "P0" else "warnings"
            row[key] = int(row[key]) + 1

        try:
            payload = download(url)
            actual_sha = hashlib.sha256(payload).hexdigest()
            if len(payload) != expected_bytes:
                raise ValueError(f"byte length mismatch {len(payload)} != {expected_bytes}")
            if actual_sha != expected_sha:
                raise ValueError(f"SHA-256 mismatch {actual_sha} != {expected_sha}")
            validate_zip(payload)
            independent_counts = effective_main_table_counts(payload)
            row["independent_main_tables"], row["independent_main_rows"], row["independent_main_cells"] = independent_counts
        except Exception as exc:  # noqa: BLE001 - fail closed with exact source error
            row["raw_status"] = "FAIL"
            row["adapter_status"] = "SKIPPED"
            row["normalizer_status"] = "SKIPPED"
            row["canonical_status"] = "SKIPPED"
            row["l0_status"] = "FAIL"
            row["l1_status"] = "SKIPPED"
            row["l2_status"] = "SKIPPED"
            row["l3_status"] = "SKIPPED"
            row["overall_status"] = "FAIL"
            event("RAW", "P0", "exact_source_revision", repr(exc))
            rows.append(row)
            print(f"{candidate_id}: RAW FAIL: {exc}")
            continue

        source_name = unquote(Path(urlparse(url).path).name)
        try:
            adapted = DocxAdapter().adapt(payload, source_name=source_name)
            row["raw_elements"] = len(adapted.raw_elements)
            if adapted.content_hash != f"sha256:{expected_sha}":
                raise ValueError(
                    f"adapter content hash mismatch {adapted.content_hash} != sha256:{expected_sha}"
                )
            row["table_count"] = sum(element.type_hint == "TABLE" for element in adapted.raw_elements)
            row["table_row_count"] = sum(element.type_hint == "TABLE_ROW" for element in adapted.raw_elements)
            row["table_cell_count"] = sum(element.type_hint == "TABLE_CELL" for element in adapted.raw_elements)
        except Exception as exc:  # noqa: BLE001
            row["adapter_status"] = "FAIL"
            row["normalizer_status"] = "SKIPPED"
            row["canonical_status"] = "SKIPPED"
            row["l0_status"] = "FAIL"
            row["l1_status"] = "SKIPPED"
            row["l2_status"] = "SKIPPED"
            row["l3_status"] = "SKIPPED"
            row["overall_status"] = "FAIL"
            event("ADAPTER", "P0", "adapter_execution", repr(exc))
            rows.append(row)
            print(f"{candidate_id}: ADAPTER FAIL: {exc}")
            continue

        if candidate_id == "govuk-8145a59a6649c5e4":
            expected = (39, 269, 708)
            independent = (
                int(row["independent_main_tables"]),
                int(row["independent_main_rows"]),
                int(row["independent_main_cells"]),
            )
            production = (
                int(row["table_count"]),
                int(row["table_row_count"]),
                int(row["table_cell_count"]),
            )
            if independent != expected:
                row["l0_status"] = "FAIL"
                event("L0", "P0", "independent_8145_effective_table_shape", f"{independent} != {expected}")
            if production != expected:
                row["l0_status"] = "FAIL"
                event("L0", "P0", "production_8145_table_shape", f"{production} != {expected}")

        try:
            result = SourceAdapterRunner().understand_bytes(
                payload,
                adapter=DocxAdapter(),
                document_id=candidate_id,
                source_name=source_name,
                processed_at=datetime(2026, 8, 12, tzinfo=UTC),
            )
            understanding = result.understanding
            document = understanding.structural_document
            completion = understanding.completion_report
            row["canonical_elements"] = len(document.elements)
            row["logical_units"] = len(document.logical_units)
            row["regions"] = len(document.regions)
            row["structure_mode"] = document.structure.mode.value
            row["structural_ready"] = completion.structural_ready
            if not result.preservation_report.fully_preserved:
                raise ValueError("runner returned non-preserved normalization result")
            if len(result.adapter_result.raw_elements) != len(document.elements):
                raise ValueError("RawElement -> Element cardinality changed")
        except Exception as exc:  # noqa: BLE001
            row["normalizer_status"] = "FAIL"
            row["canonical_status"] = "FAIL"
            row["l1_status"] = "FAIL"
            row["l2_status"] = "SKIPPED"
            row["l3_status"] = "SKIPPED"
            row["overall_status"] = "FAIL"
            event("CANONICAL", "P0", "production_pipeline_execution", repr(exc))
            rows.append(row)
            print(f"{candidate_id}: PIPELINE FAIL: {exc}")
            continue

        fabricated_location = [
            element.id
            for element in document.elements
            if element.location is not None
            and (element.location.page is not None or element.location.bbox is not None)
        ]
        if fabricated_location:
            row["l1_status"] = "FAIL"
            event("L1", "P0", "fabricated_docx_page_or_bbox", f"count={len(fabricated_location)}")

        by_id = {element.id: element for element in document.elements}
        ungrouped_ids = tuple(understanding.grouping_result.ungrouped_element_ids)
        anchor_ids = [element_id for element_id in ungrouped_ids if by_id[element_id].type in EXPECTED_ANCHOR_TYPES]
        integrity_ids = [element_id for element_id in ungrouped_ids if by_id[element_id].type in INTEGRITY_TYPES]
        ordinary_ids = [
            element_id
            for element_id in ungrouped_ids
            if by_id[element_id].type not in EXPECTED_ANCHOR_TYPES
            and by_id[element_id].type not in INTEGRITY_TYPES
        ]
        unresolved = tuple(completion.unresolved_integrity_boundary_ids)
        row["expected_anchor_ungrouped"] = len(anchor_ids)
        row["ordinary_content_ungrouped"] = len(ordinary_ids)
        row["integrity_sensitive_ungrouped"] = len(integrity_ids)
        row["unresolved_integrity"] = len(unresolved)

        if ordinary_ids:
            row["l2_status"] = "WARN"
            event("L2", "P1", "ordinary_content_ungrouped", f"count={len(ordinary_ids)}")
        if integrity_ids or unresolved:
            row["l2_status"] = "FAIL"
            event(
                "L2",
                "P0",
                "integrity_not_resolved",
                f"integrity_sensitive_ungrouped={len(integrity_ids)} unresolved={len(unresolved)}",
            )

        if not completion.structural_pipeline_complete:
            row["l3_status"] = "FAIL"
            event("L3", "P0", "structural_pipeline_incomplete", "completion report is false")
        if not completion.structural_ready:
            row["l3_status"] = "FAIL"
            event("L3", "P0", "structural_not_ready", json.dumps(completion.warnings))

        statuses = [
            str(row["raw_status"]),
            str(row["adapter_status"]),
            str(row["normalizer_status"]),
            str(row["canonical_status"]),
            str(row["l0_status"]),
            str(row["l1_status"]),
            str(row["l2_status"]),
            str(row["l3_status"]),
        ]
        if any(status == "FAIL" for status in statuses):
            row["overall_status"] = "FAIL"
        elif any(status == "WARN" for status in statuses):
            row["overall_status"] = "WARN"
        else:
            row["overall_status"] = "PASS"
        rows.append(row)
        print(
            f"{candidate_id}: {row['overall_status']} raw={row['raw_elements']} "
            f"elements={row['canonical_elements']} L0={row['l0_status']} "
            f"L2={row['l2_status']} L3={row['l3_status']}"
        )

    fields = list(rows[0])
    matrix_path = OUTPUT_DIR / "raw_parser_validation_matrix_v2.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    errors_path = OUTPUT_DIR / "raw_parser_errors_v2.jsonl"
    with errors_path.open("w", encoding="utf-8") as handle:
        for item in events:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    counts = {status: sum(row["overall_status"] == status for row in rows) for status in ("PASS", "WARN", "FAIL")}
    stage_names = ("raw_status", "adapter_status", "normalizer_status", "canonical_status", "l0_status", "l1_status", "l2_status", "l3_status")
    report_lines = [
        "# Raw DOCX + Production Source Understanding Validation V2",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        "- Production commit under test: de453dff1f36f3858113aab02064267c9502c6d8",
        "- Corpus: exact 30 pinned GOV.UK DOCX revisions from final_manifest.jsonl",
        "- Semantic provider: disabled",
        "- Raw bytes: downloaded only inside CI and verified against pinned byte length + SHA-256",
        "",
        "## Overall",
        "",
        f"PASS={counts['PASS']}, WARN={counts['WARN']}, FAIL={counts['FAIL']}",
        "",
        "## Stage counts",
        "",
        "| stage | PASS | WARN | FAIL | SKIPPED |",
        "|---|---:|---:|---:|---:|",
    ]
    for stage in stage_names:
        report_lines.append(
            f"| {stage} | {sum(row[stage] == 'PASS' for row in rows)} | "
            f"{sum(row[stage] == 'WARN' for row in rows)} | "
            f"{sum(row[stage] == 'FAIL' for row in rows)} | "
            f"{sum(row[stage] == 'SKIPPED' for row in rows)} |"
        )
    report_lines.extend(
        [
            "",
            "## Confirmed P0 regression targets",
            "",
        ]
    )
    for target in ("govuk-74e4cc9e1ba73f68", "govuk-8145a59a6649c5e4"):
        target_row = next(row for row in rows if row["candidate_id"] == target)
        report_lines.append(
            f"- `{target}`: overall={target_row['overall_status']}, adapter={target_row['adapter_status']}, L0={target_row['l0_status']}, tables/rows/cells={target_row['table_count']}/{target_row['table_row_count']}/{target_row['table_cell_count']}"
        )
    report_lines.extend(
        [
            "",
            "## L2 taxonomy",
            "",
            "Ungrouped TITLE/HEADING/SEPARATOR elements are expected structural anchors and do not create warnings. Ordinary ungrouped content creates WARN. Integrity-sensitive ungrouped content or unresolved integrity creates FAIL.",
            "",
            "## Events",
            "",
        ]
    )
    if events:
        for item in events:
            report_lines.append(
                f"- {item['severity']} `{item['candidate_id']}` {item['stage']}/{item['check']}: {item['message']}"
            )
    else:
        report_lines.append("No error/warning events.")
    report_lines.extend(
        [
            "",
            "## Scope note",
            "",
            "This V2 run validates exact source revision integrity, production adapter execution, RawElement->Element preservation, canonical graph construction, completion/integrity invariants, and the two confirmed P0 regressions. It is not human-adjudicated L2/L3 accuracy and does not treat structural_ready as accuracy.",
        ]
    )
    (OUTPUT_DIR / "raw_parser_validation_report_v2.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(json.dumps({"overall": counts, "events": len(events)}, sort_keys=True))
    return 0 if counts["WARN"] == 0 and counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
