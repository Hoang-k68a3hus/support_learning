from __future__ import annotations

import json

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.schemas.logical_unit import LogicalUnitType

from ._corpus import FIXED_EVALUATION_TIME, SOURCES, _download
from .reviewed_gold import load_review_decisions


def _production_member(element) -> dict[str, object]:
    return {
        "order": element.order,
        "type": element.type.value,
        "text": element.raw_text,
        "numbering_id": element.attributes.get("numbering_id"),
        "numbering_level": element.attributes.get("numbering_level"),
        "number_format": element.attributes.get("number_format"),
        "integrity_group_id": element.attributes.get("integrity_group_id"),
        "indentation": None if element.style is None else element.style.indentation,
        "bold": None if element.style is None else element.style.bold,
    }


def main() -> None:
    decisions = {item.source_id: item for item in load_review_decisions()}
    rows: list[dict[str, object]] = []
    for source in SOURCES:
        document_id = str(source["id"])
        decision = decisions[document_id]
        gold = decision.gold
        if gold is None:
            continue
        gold_list_units = [
            unit for unit in gold.logical_units if unit.type == LogicalUnitType.LIST_GROUP
        ]
        if not gold_list_units:
            continue

        payload = _download(str(source["url"]))
        result = SourceAdapterRunner().understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id=document_id,
            source_name=str(source["file_name"]),
            processed_at=FIXED_EVALUATION_TIME,
        )
        document = result.understanding.document
        predicted_list_units = [
            unit
            for unit in document.logical_units
            if unit.type == LogicalUnitType.LIST_GROUP
        ]
        predicted_by_id = {element.id: element for element in document.elements}
        gold_by_id = {element.id: element for element in gold.elements}

        rows.append(
            {
                "document_id": document_id,
                "gold_groups": [
                    {
                        "id": unit.id,
                        "orders": [gold_by_id[element_id].order for element_id in unit.element_ids],
                        "members": [
                            {
                                "order": gold_by_id[element_id].order,
                                "type": gold_by_id[element_id].type.value,
                                "text": gold_by_id[element_id].text,
                            }
                            for element_id in unit.element_ids
                        ],
                    }
                    for unit in gold_list_units
                ],
                "predicted_groups": [
                    {
                        "id": unit.id,
                        "orders": [
                            predicted_by_id[element_id].order
                            for element_id in unit.element_ids
                        ],
                        "metadata": unit.metadata,
                        "members": [
                            _production_member(predicted_by_id[element_id])
                            for element_id in unit.element_ids
                        ],
                    }
                    for unit in predicted_list_units
                ],
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
