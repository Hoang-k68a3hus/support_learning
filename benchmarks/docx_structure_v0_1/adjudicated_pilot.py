from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_understanding.evaluation.schemas import (
    BenchmarkManifest,
    GoldDocumentStructure,
    GoldElement,
    GoldRegion,
    GoldSourceAnchor,
)
from source_understanding.schemas.element import ElementType

from .generate_pilot import (
    GENERATOR_ID,
    GENERATOR_SEED,
    GeneratedCase,
    build_manifest,
    build_pilot_cases as build_raw_pilot_cases,
)


GOLD_ADJUDICATION_VERSION = "0.1"


def build_pilot_cases() -> tuple[GeneratedCase, ...]:
    """Return generated DOCX sources paired with reviewed structural gold.

    Source generation and gold adjudication are deliberately separate. Reviewing
    a gold interpretation must not rewrite source bytes or silently move the
    benchmark target toward current parser output.
    """

    return tuple(_adjudicate(case) for case in build_raw_pilot_cases())


def build_adjudicated_manifest(
    cases: tuple[GeneratedCase, ...] | None = None,
) -> BenchmarkManifest:
    resolved = cases if cases is not None else build_pilot_cases()
    manifest = build_manifest(resolved)
    metadata = dict(manifest.metadata)
    metadata.update(
        {
            "gold_adjudication_version": GOLD_ADJUDICATION_VERSION,
            "source_generator_id": GENERATOR_ID,
            "source_generator_seed": GENERATOR_SEED,
        }
    )
    return manifest.model_copy(update={"metadata": metadata})


def materialize(output_dir: Path) -> BenchmarkManifest:
    cases = build_pilot_cases()
    manifest = build_adjudicated_manifest(cases)
    documents = output_dir / "documents"
    annotations = output_dir / "annotations"
    documents.mkdir(parents=True, exist_ok=True)
    annotations.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (documents / case.file_name).write_bytes(case.payload)
        (annotations / f"{case.document_id}.json").write_text(
            json.dumps(
                case.gold.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def _adjudicate(case: GeneratedCase) -> GeneratedCase:
    if case.document_id == "docx-pilot-03":
        return _adjudicate_story_boundaries(case)
    return case


def _adjudicate_story_boundaries(case: GeneratedCase) -> GeneratedCase:
    """Record source-story delimiters and bridge-region policy in case 03 gold.

    Review found that the DOCX adapter intentionally emits a source-zone boundary
    before each referenced header/footer story. Those delimiters are part of the
    canonical source-near view and were missing from the initial handwritten
    gold. Review also confirmed that BOILERPLATE and SEPARATOR are bridge
    categories in ContentRegionPolicy: they attach to an adjacent material region
    instead of inventing a standalone semantic/routing region.
    """

    gold = case.gold
    old_by_id = {item.id: item for item in gold.elements}
    retained = tuple(old_by_id[f"e{index:02d}"] for index in range(1, 10))

    footer_boundary = GoldElement(
        id="e10",
        order=9,
        anchor=GoldSourceAnchor(
            opc_part="word/footer1.xml",
            source_zone="footer",
            source_kind="separator:source_zone_boundary",
            occurrence=0,
        ),
        text=None,
        type=ElementType.SEPARATOR,
        metadata={
            "adjudication": "adapter source-story boundary",
            "adjudication_version": GOLD_ADJUDICATION_VERSION,
        },
    )
    footer = old_by_id["e10"].model_copy(update={"id": "e11", "order": 10})
    header_boundary = GoldElement(
        id="e12",
        order=11,
        anchor=GoldSourceAnchor(
            opc_part="word/header1.xml",
            source_zone="header",
            source_kind="separator:source_zone_boundary",
            occurrence=0,
        ),
        text=None,
        type=ElementType.SEPARATOR,
        metadata={
            "adjudication": "adapter source-story boundary",
            "adjudication_version": GOLD_ADJUDICATION_VERSION,
        },
    )
    header = old_by_id["e11"].model_copy(update={"id": "e13", "order": 12})
    elements = (*retained, footer_boundary, footer, header_boundary, header)

    metadata = dict(gold.metadata)
    metadata.update(
        {
            "gold_adjudication_version": GOLD_ADJUDICATION_VERSION,
            "adjudication_decisions": [
                "include explicit source_zone_boundary elements before footer/header stories",
                "treat boilerplate/separator as bridge material attached to the adjacent narrative region",
            ],
        }
    )
    reviewed = gold.model_copy(
        update={
            "elements": elements,
            "regions": (
                GoldRegion(
                    id="r1",
                    element_ids=tuple(item.id for item in elements),
                    category="narrative",
                    metadata={
                        "bridge_policy": "boilerplate_and_separator_attach_to_adjacent_material_region"
                    },
                ),
            ),
            "metadata": metadata,
        }
    )
    # Re-run all cross-reference, region-cover, and order validators after the
    # adjudication rather than trusting model_copy's unvalidated intermediate.
    validated = GoldDocumentStructure.model_validate(reviewed.model_dump(mode="json"))
    return GeneratedCase(
        document_id=case.document_id,
        file_name=case.file_name,
        payload=case.payload,
        gold=validated,
        split=case.split,
        tags=tuple((*case.tags, "adjudicated_gold")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize generated DOCX sources with adjudicated V0.1 gold."
    )
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
                "gold_adjudication_version": GOLD_ADJUDICATION_VERSION,
                "cases": len(manifest.cases),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
