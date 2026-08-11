from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from pydantic import Field, model_validator

from source_understanding.evaluation.schemas import (
    BenchmarkCase,
    BenchmarkManifest,
    BenchmarkSplit,
)
from source_understanding.schemas.context import ContentHash, Identifier, SchemaModel

from ._corpus import HERE, SOURCES
from .adjudication import ReviewDecision, ReviewStatus


REVIEWED_GOLD_DIR = HERE / "reviewed_gold"
REVIEWED_GOLD_MANIFEST = REVIEWED_GOLD_DIR / "manifest.json"
REVIEWED_GOLD_ADJUDICATION_VERSION = "SU4.1-2026-08-12"
REVIEWED_GOLD_GENERATOR_ID = "assistant-adjudication:su4.1"


class ReviewedGoldEntry(SchemaModel):
    id: Identifier
    review_file: str = Field(min_length=1, max_length=1024)
    source_sha256: ContentHash
    bundle_sha256: ContentHash

    @model_validator(mode="after")
    def validate_review_file(self) -> "ReviewedGoldEntry":
        path = PurePosixPath(self.review_file)
        if len(path.parts) != 1 or path.name != self.review_file or "\\" in self.review_file:
            raise ValueError("review_file must be a base file name")
        if not self.review_file.endswith(".review.json"):
            raise ValueError("review_file must end with .review.json")
        return self


class ReviewedGoldManifest(SchemaModel):
    benchmark: str = Field(min_length=1, max_length=256)
    benchmark_version: str = Field(min_length=1, max_length=64)
    schema_version: str = Field(min_length=1, max_length=64)
    adjudication_version: str = Field(min_length=1, max_length=128)
    reviewer_model: str = Field(min_length=1, max_length=256)
    review_policy: str = Field(min_length=1, max_length=2048)
    documents: tuple[ReviewedGoldEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> "ReviewedGoldManifest":
        if self.benchmark != "docx_structure_real_v0_1":
            raise ValueError("unexpected reviewed-gold benchmark name")
        if self.benchmark_version != "0.1" or self.schema_version != "0.1":
            raise ValueError("reviewed-gold manifest version does not match V0.1 schemas")
        if self.adjudication_version != REVIEWED_GOLD_ADJUDICATION_VERSION:
            raise ValueError("unsupported reviewed-gold adjudication version")
        ids = [item.id for item in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("reviewed-gold manifest contains duplicate document ids")
        files = [item.review_file for item in self.documents]
        if len(files) != len(set(files)):
            raise ValueError("reviewed-gold manifest contains duplicate review files")
        return self


def load_reviewed_gold_manifest(
    path: Path = REVIEWED_GOLD_MANIFEST,
) -> ReviewedGoldManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReviewedGoldManifest.model_validate(payload)


def load_review_decisions(
    manifest: ReviewedGoldManifest | None = None,
) -> tuple[ReviewDecision, ...]:
    resolved = manifest if manifest is not None else load_reviewed_gold_manifest()
    source_by_id = {
        str(source["id"]): source
        for source in SOURCES
        if isinstance(source.get("id"), str)
    }
    expected_ids = set(source_by_id)
    actual_ids = {item.id for item in resolved.documents}
    if actual_ids != expected_ids:
        raise ValueError(
            "reviewed-gold document set must match the pinned real corpus exactly: "
            f"missing={sorted(expected_ids - actual_ids)}, "
            f"extra={sorted(actual_ids - expected_ids)}"
        )

    decisions: list[ReviewDecision] = []
    for entry in resolved.documents:
        source = source_by_id[entry.id]
        if source.get("sha256") != entry.source_sha256:
            raise ValueError(
                f"reviewed-gold source hash disagrees with sources.json for {entry.id!r}"
            )
        review_path = REVIEWED_GOLD_DIR / entry.review_file
        decision = ReviewDecision.model_validate_json(
            review_path.read_text(encoding="utf-8")
        )
        if decision.status != ReviewStatus.FINAL:
            raise ValueError(f"reviewed-gold decision {entry.id!r} is not FINAL")
        if decision.source_id != entry.id:
            raise ValueError(f"reviewed-gold decision identity mismatch for {entry.id!r}")
        if decision.source_sha256 != entry.source_sha256:
            raise ValueError(f"reviewed-gold decision source hash mismatch for {entry.id!r}")
        if decision.bundle_sha256 != entry.bundle_sha256:
            raise ValueError(f"reviewed-gold bundle hash mismatch for {entry.id!r}")
        if decision.gold is None:
            raise ValueError(f"reviewed-gold decision {entry.id!r} has no gold payload")
        gold_source = decision.gold.source
        for field_name in ("file_name", "document_class"):
            if getattr(gold_source, field_name) != source.get(field_name):
                raise ValueError(
                    f"reviewed-gold {field_name} disagrees with sources.json for {entry.id!r}"
                )
        decisions.append(decision)
    return tuple(decisions)


def build_reviewed_benchmark_manifest(
    decisions: tuple[ReviewDecision, ...] | None = None,
) -> BenchmarkManifest:
    resolved = decisions if decisions is not None else load_review_decisions()
    by_id = {decision.source_id: decision for decision in resolved}
    cases: list[BenchmarkCase] = []
    for source in SOURCES:
        document_id = str(source["id"])
        decision = by_id[document_id]
        if decision.gold is None:  # pragma: no cover - guarded by loader.
            raise ValueError(f"reviewed-gold decision {document_id!r} has no gold")
        cases.append(
            BenchmarkCase(
                document_id=document_id,
                source_file=str(source["file_name"]),
                annotation_file=f"reviewed_gold/{document_id}.review.json",
                sha256=decision.source_sha256,
                split=BenchmarkSplit.DEV,
                tags=(
                    "real_docx",
                    "assistant_adjudicated",
                    str(source["document_class"]),
                ),
            )
        )
    return BenchmarkManifest(
        name="docx_structure_real_v0_1_reviewed_su4_1",
        benchmark_version="0.1",
        schema_version="0.1",
        generator_id=REVIEWED_GOLD_GENERATOR_ID,
        generator_seed=0,
        cases=tuple(cases),
        metadata={
            "adjudication_version": REVIEWED_GOLD_ADJUDICATION_VERSION,
            "oracle_policy": (
                "source document inspection + independent OOXML audit; "
                "production output is comparison-only"
            ),
            "accuracy_claim_scope": (
                "five pinned public DOCX documents; not a population-level accuracy claim"
            ),
        },
    )
