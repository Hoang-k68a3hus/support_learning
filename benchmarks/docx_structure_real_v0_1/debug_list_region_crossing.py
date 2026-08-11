from __future__ import annotations

import json

from source_understanding.adapters import DocxAdapter, SourceAdapterRunner
from source_understanding.pipeline import (
    SourceUnderstandingPipeline,
    SourceUnderstandingPipelinePolicy,
)
from source_understanding.profiling.regions import ContentRegionSegmenter

from ._corpus import FIXED_EVALUATION_TIME, SOURCES, _download


def main() -> None:
    rows: list[dict[str, object]] = []
    pipeline = SourceUnderstandingPipeline(
        policy=SourceUnderstandingPipelinePolicy(auto_segment_regions=False)
    )
    for source in SOURCES:
        payload = _download(str(source["url"]))
        result = SourceAdapterRunner(pipeline=pipeline).understand_bytes(
            payload,
            adapter=DocxAdapter(),
            document_id=str(source["id"]),
            source_name=str(source["file_name"]),
            processed_at=FIXED_EVALUATION_TIME,
        )
        understanding = result.understanding
        regions = ContentRegionSegmenter().segment(
            understanding.document.elements,
            understanding.hierarchy_result,
            understanding.grouping_result,
        )
        region_by_element = {
            element_id: region
            for region in regions.regions
            for element_id in region.element_ids
        }
        order = {
            element.id: element.order for element in understanding.document.elements
        }
        for unit in understanding.grouping_result.logical_units:
            touched = {
                region_by_element[element_id].id for element_id in unit.element_ids
            }
            if len(touched) <= 1:
                continue
            member_orders = [order[element_id] for element_id in unit.element_ids]
            start = min(member_orders)
            end = max(member_orders)
            span_elements = [
                element
                for element in understanding.document.elements
                if start <= element.order <= end
            ]
            rows.append(
                {
                    "document_id": source["id"],
                    "unit_id": unit.id,
                    "unit_type": unit.type.value,
                    "unit_member_ids": list(unit.element_ids),
                    "unit_metadata": unit.metadata,
                    "region_ids": sorted(touched),
                    "span": [
                        {
                            "id": element.id,
                            "order": element.order,
                            "type": element.type.value,
                            "text": element.raw_text,
                            "routing_region": region_by_element[element.id].id,
                            "routing_category": region_by_element[element.id].metadata.get(
                                "routing_category"
                            ),
                            "numbering_id": element.attributes.get("numbering_id"),
                            "numbering_level": element.attributes.get("numbering_level"),
                            "number_format": element.attributes.get("number_format"),
                            "integrity_group_id": element.attributes.get(
                                "integrity_group_id"
                            ),
                            "indentation": (
                                None
                                if element.style is None
                                else element.style.indentation
                            ),
                        }
                        for element in span_elements
                    ],
                }
            )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
