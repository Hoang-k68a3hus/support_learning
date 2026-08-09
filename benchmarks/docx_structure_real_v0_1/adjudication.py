from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from source_understanding.evaluation.schemas import (
    BenchmarkSourceKind,
    GoldDocumentStructure,
)
from source_understanding.schemas.context import (
    ContentHash,
    Identifier,
    JsonObject,
    SchemaModel,
)

from ._corpus import SOURCES, _download
from .discover import discover_payload
from .source_audit import AUDIT_VERSION, audit_payload


HERE = Path(__file__).resolve().parent
ADJUDICATION_SCHEMA_VERSION = "0.1"
PRODUCTION_DISCOVERY_VERSION = "real-docx-production-discovery:1"
BUNDLE_ARTIFACT_KIND = "DOCX_STRUCTURE_ADJUDICATION_BUNDLE"
DECISION_ARTIFACT_KIND = "DOCX_STRUCTURE_REVIEW_DECISION"


class ReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class ReviewCoverageStatus(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class ReviewMethod(StrEnum):
    SOURCE_DOCUMENT_INSPECTION = "SOURCE_DOCUMENT_INSPECTION"
    INDEPENDENT_OOXML_AUDIT = "INDEPENDENT_OOXML_AUDIT"
    PRODUCTION_OUTPUT_COMPARISON = "PRODUCTION_OUTPUT_COMPARISON"


class AdjudicationSource(SchemaModel):
    id: Identifier
    file_name: str = Field(min_length=1, max_length=1024)
    document_class: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=8192)
    source_page: str = Field(min_length=1, max_length=8192)
    license: str = Field(min_length=1, max_length=1024)
    bytes: int = Field(ge=1)
    sha256: ContentHash

    @model_validator(mode="after")
    def validate_file_name(self) -> "AdjudicationSource":
        path = PurePosixPath(self.file_name)
        if len(path.parts) != 1 or path.name != self.file_name or "\\" in self.file_name:
            raise ValueError("adjudication source file_name must be a base file name")
        return self


class AdjudicationBundlePayload(SchemaModel):
    artifact_kind: Literal["DOCX_STRUCTURE_ADJUDICATION_BUNDLE"] = (
        BUNDLE_ARTIFACT_KIND
    )
    schema_version: str = ADJUDICATION_SCHEMA_VERSION
    benchmark_version: str = Field(min_length=1, max_length=64)
    source: AdjudicationSource
    independent_audit_version: str = AUDIT_VERSION
    production_discovery_version: str = PRODUCTION_DISCOVERY_VERSION
    independent_evidence: JsonObject
    production_prediction: JsonObject
    review_instructions: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle_payload(self) -> "AdjudicationBundlePayload":
        if self.schema_version != ADJUDICATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported adjudication schema_version {self.schema_version!r}"
            )
        if self.independent_audit_version != AUDIT_VERSION:
            raise ValueError(
                "independent audit version does not match the bundle schema"
            )
        if self.production_discovery_version != PRODUCTION_DISCOVERY_VERSION:
            raise ValueError(
                "production discovery version does not match the bundle schema"
            )
        self._validate_revision_record(
            "independent_evidence", self.independent_evidence
        )
        self._validate_revision_record(
            "production_prediction", self.production_prediction
        )
        if self.independent_evidence.get("audit_version") != AUDIT_VERSION:
            raise ValueError(
                "independent evidence does not declare the expected audit version"
            )
        return self

    def _validate_revision_record(
        self,
        name: str,
        record: dict[str, object],
    ) -> None:
        expected = {
            "id": self.source.id,
            "bytes": self.source.bytes,
            "sha256": self.source.sha256,
        }
        actual = {key: record.get(key) for key in expected}
        if actual != expected:
            raise ValueError(
                f"{name} source revision disagrees with bundle source: "
                f"expected={expected}, actual={actual}"
            )


class AdjudicationBundle(SchemaModel):
    payload: AdjudicationBundlePayload
    bundle_sha256: ContentHash

    @model_validator(mode="after")
    def validate_fingerprint(self) -> "AdjudicationBundle":
        actual = bundle_payload_hash(self.payload)
        if self.bundle_sha256 != actual:
            raise ValueError(
                "adjudication bundle fingerprint mismatch: "
                f"declared={self.bundle_sha256}, actual={actual}"
            )
        return self


class ReviewLevel(SchemaModel):
    coverage: ReviewCoverageStatus = ReviewCoverageStatus.NOT_REVIEWED
    scope: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_scope(self) -> "ReviewLevel":
        if any(not item or item.strip() != item for item in self.scope):
            raise ValueError("review scope entries must be trimmed non-blank strings")
        if len(self.scope) != len(set(self.scope)):
            raise ValueError("review scope entries must be unique")
        if self.coverage == ReviewCoverageStatus.NOT_REVIEWED and self.scope:
            raise ValueError("NOT_REVIEWED level cannot claim an evaluated scope")
        if self.coverage != ReviewCoverageStatus.NOT_REVIEWED and not self.scope:
            raise ValueError("reviewed level requires an explicit scope")
        return self


class ReviewCoverage(SchemaModel):
    L0_source_fidelity: ReviewLevel = Field(default_factory=ReviewLevel)
    L1_element_understanding: ReviewLevel = Field(default_factory=ReviewLevel)
    L2_structural_grouping: ReviewLevel = Field(default_factory=ReviewLevel)
    L3_document_structure: ReviewLevel = Field(default_factory=ReviewLevel)


class ReviewDecision(SchemaModel):
    artifact_kind: Literal["DOCX_STRUCTURE_REVIEW_DECISION"] = DECISION_ARTIFACT_KIND
    schema_version: str = ADJUDICATION_SCHEMA_VERSION
    benchmark_version: str = Field(min_length=1, max_length=64)
    bundle_sha256: ContentHash
    source_id: Identifier
    source_sha256: ContentHash
    status: ReviewStatus = ReviewStatus.DRAFT
    reviewer_id: str | None = Field(default=None, min_length=1, max_length=256)
    reviewed_at: datetime | None = None
    review_methods: tuple[ReviewMethod, ...] = Field(default_factory=tuple)
    coverage: ReviewCoverage = Field(default_factory=ReviewCoverage)
    decision_notes: tuple[str, ...] = Field(default_factory=tuple)
    gold: GoldDocumentStructure | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "ReviewDecision":
        if self.schema_version != ADJUDICATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported adjudication schema_version {self.schema_version!r}"
            )
        if len(self.review_methods) != len(set(self.review_methods)):
            raise ValueError("review_methods must be unique")
        if self.reviewer_id is not None and (
            not self.reviewer_id or self.reviewer_id.strip() != self.reviewer_id
        ):
            raise ValueError("reviewer_id must be a trimmed non-blank string")
        if any(not item or item.strip() != item for item in self.decision_notes):
            raise ValueError("decision_notes must contain trimmed non-blank strings")
        if len(self.decision_notes) != len(set(self.decision_notes)):
            raise ValueError("decision_notes must be unique")
        if self.gold is not None:
            if self.gold.document_id != self.source_id:
                raise ValueError("gold document_id does not match decision source_id")
            if self.gold.source.sha256 != self.source_sha256:
                raise ValueError("gold source hash does not match decision source hash")
            if self.gold.benchmark_version != self.benchmark_version:
                raise ValueError(
                    "gold benchmark_version does not match review decision"
                )
        if self.status == ReviewStatus.FINAL:
            self._validate_final()
        return self

    def _validate_final(self) -> None:
        if self.reviewer_id is None:
            raise ValueError("FINAL review requires reviewer_id")
        if self.reviewed_at is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("FINAL review requires timezone-aware reviewed_at")
        required_methods = {
            ReviewMethod.SOURCE_DOCUMENT_INSPECTION,
            ReviewMethod.INDEPENDENT_OOXML_AUDIT,
        }
        missing_methods = required_methods - set(self.review_methods)
        if missing_methods:
            raise ValueError(
                "FINAL review is missing required methods: "
                f"{sorted(item.value for item in missing_methods)}"
            )
        if not self.decision_notes:
            raise ValueError("FINAL review requires at least one decision note")
        if self.gold is None:
            raise ValueError("FINAL review requires validated structural gold")
        if self.gold.source.source_kind != BenchmarkSourceKind.PUBLIC:
            raise ValueError("FINAL real-DOCX gold must declare source_kind PUBLIC")

        l2 = self.coverage.L2_structural_grouping.coverage
        l3 = self.coverage.L3_document_structure.coverage
        if l2 == ReviewCoverageStatus.NOT_REVIEWED and l3 == ReviewCoverageStatus.NOT_REVIEWED:
            raise ValueError("FINAL real-DOCX review must adjudicate L2 or L3")

        if l2 == ReviewCoverageStatus.NOT_REVIEWED:
            if self.gold.logical_units or self.gold.evaluated_logical_unit_types:
                raise ValueError(
                    "unreviewed L2 cannot export logical-unit gold or evaluation scope"
                )
        elif not self.gold.evaluated_logical_unit_types:
            raise ValueError(
                "reviewed L2 requires evaluated_logical_unit_types to make scope measurable"
            )

        l3_targets_present = bool(
            self.gold.context_nodes
            or self.gold.regions
            or self.gold.relations
            or self.gold.evaluated_relation_types
            or self.gold.expected_structure_mode is not None
            or self.gold.expected_structural_ready is not None
        )
        if l3 == ReviewCoverageStatus.NOT_REVIEWED and l3_targets_present:
            raise ValueError(
                "unreviewed L3 cannot export hierarchy/region/relation/readiness gold"
            )
        if l3 != ReviewCoverageStatus.NOT_REVIEWED and not l3_targets_present:
            raise ValueError("reviewed L3 requires at least one measurable target")


def bundle_payload_hash(payload: AdjudicationBundlePayload) -> str:
    rendered = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(rendered).hexdigest()


def build_adjudication_bundle(
    source: dict[str, object],
    pin: dict[str, object],
    payload: bytes,
) -> AdjudicationBundle:
    source_id = source.get("id")
    if source_id != pin.get("id"):
        raise ValueError(
            f"source/pin identity mismatch: source={source_id!r}, pin={pin.get('id')!r}"
        )
    for field in ("file_name", "document_class", "url", "source_page", "license"):
        if source.get(field) != pin.get(field):
            raise ValueError(
                f"source/pin field mismatch for {source_id!r}: {field}"
            )

    actual_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    actual_bytes = len(payload)
    if actual_hash != pin.get("sha256") or actual_bytes != pin.get("bytes"):
        raise ValueError(
            f"source revision mismatch for {source_id!r}: "
            f"expected bytes={pin.get('bytes')}, sha256={pin.get('sha256')}; "
            f"actual bytes={actual_bytes}, sha256={actual_hash}"
        )

    typed_source = {
        key: source[key]
        for key in (
            "id",
            "file_name",
            "document_class",
            "url",
            "source_page",
            "license",
        )
    }
    independent = audit_payload(typed_source, payload)
    production = discover_payload(typed_source, payload)
    bundle_payload = AdjudicationBundlePayload(
        benchmark_version=str(pin.get("benchmark_version", "0.1")),
        source=AdjudicationSource(
            **typed_source,
            bytes=actual_bytes,
            sha256=actual_hash,
        ),
        independent_evidence=independent,
        production_prediction=production,
        review_instructions=(
            "Treat independent_evidence as source-observation assistance, not automatic gold.",
            "Treat production_prediction only as a candidate to accept, reject, or amend.",
            "Inspect the pinned source document before making a FINAL decision.",
            "Use benchmark-only gold ids; never copy production ids into gold.",
            "Do not edit gold_contracts.json through this workflow; export reviewed gold separately for diff review.",
        ),
    )
    return AdjudicationBundle(
        payload=bundle_payload,
        bundle_sha256=bundle_payload_hash(bundle_payload),
    )


def build_review_template(bundle: AdjudicationBundle) -> ReviewDecision:
    return ReviewDecision(
        benchmark_version=bundle.payload.benchmark_version,
        bundle_sha256=bundle.bundle_sha256,
        source_id=bundle.payload.source.id,
        source_sha256=bundle.payload.source.sha256,
    )


def validate_review_decision(
    bundle: AdjudicationBundle,
    decision: ReviewDecision,
    *,
    require_final: bool = True,
) -> ReviewDecision:
    # Revalidate at this public boundary. Pydantic's model_copy intentionally
    # skips validation, so accepting a nominal model instance without this step
    # would let callers bypass FINAL-review invariants.
    validated_bundle = AdjudicationBundle.model_validate(
        bundle.model_dump(mode="json")
    )
    validated_decision = ReviewDecision.model_validate(
        decision.model_dump(mode="json")
    )
    if validated_decision.bundle_sha256 != validated_bundle.bundle_sha256:
        raise ValueError("review decision references a different adjudication bundle")
    if validated_decision.benchmark_version != validated_bundle.payload.benchmark_version:
        raise ValueError("review decision benchmark_version does not match bundle")
    if validated_decision.source_id != validated_bundle.payload.source.id:
        raise ValueError("review decision source_id does not match bundle")
    if validated_decision.source_sha256 != validated_bundle.payload.source.sha256:
        raise ValueError("review decision source hash does not match bundle")
    if require_final and validated_decision.status != ReviewStatus.FINAL:
        raise ValueError("review decision must be FINAL")
    if validated_decision.gold is not None:
        if (
            validated_decision.gold.source.file_name
            != validated_bundle.payload.source.file_name
        ):
            raise ValueError("gold source file_name does not match bundle")
        if (
            validated_decision.gold.source.document_class
            != validated_bundle.payload.source.document_class
        ):
            raise ValueError("gold source document_class does not match bundle")
    return validated_decision


def load_bundle(path: str | Path) -> AdjudicationBundle:
    return AdjudicationBundle.model_validate(_load_json(Path(path), "bundle"))


def load_review_decision(path: str | Path) -> ReviewDecision:
    return ReviewDecision.model_validate(_load_json(Path(path), "review decision"))


def export_reviewed_gold(
    bundle: AdjudicationBundle,
    decision: ReviewDecision,
    output: str | Path,
) -> Path:
    validated = validate_review_decision(bundle, decision, require_final=True)
    if validated.gold is None:  # guarded by FINAL validation; keeps typing explicit
        raise ValueError("FINAL review has no gold document")
    target = Path(output)
    if target.resolve() == (HERE / "gold_contracts.json").resolve():
        raise ValueError(
            "adjudication export cannot overwrite gold_contracts.json; "
            "export separately and review the diff"
        )
    _require_new_output(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            validated.gold.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def _source(source_id: str) -> dict[str, object]:
    for source in SOURCES:
        if source["id"] == source_id:
            return dict(source)
    raise ValueError(f"unknown source id: {source_id}")


def _pin(source_id: str) -> dict[str, object]:
    payload = _load_json(HERE / "sources.json", "source pins")
    documents = payload.get("documents") if isinstance(payload, dict) else None
    benchmark_version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(benchmark_version, str) or not benchmark_version:
        raise ValueError("sources.json must declare a benchmark version")
    if not isinstance(documents, list):
        raise ValueError("sources.json must contain a documents list")
    for item in documents:
        if isinstance(item, dict) and item.get("id") == source_id:
            return {**item, "benchmark_version": benchmark_version}
    raise ValueError(f"sources.json has no pin for {source_id!r}")


def _load_json(path: Path, kind: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {kind} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {kind} {path}: {exc}") from exc


def _require_new_output(path: Path) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite existing adjudication artifact: {path}")


def _write_new_json(path: Path, model: SchemaModel) -> None:
    _require_new_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _create(args: argparse.Namespace) -> dict[str, object]:
    bundle_path = Path(args.bundle)
    decision_path = Path(args.decision_template)
    if bundle_path.resolve() == decision_path.resolve():
        raise ValueError("bundle and decision-template paths must be different")
    _require_new_output(bundle_path)
    _require_new_output(decision_path)
    source = _source(args.source)
    pin = _pin(args.source)
    payload = _download(str(source["url"]))
    bundle = build_adjudication_bundle(source, pin, payload)
    template = build_review_template(bundle)
    _write_new_json(bundle_path, bundle)
    _write_new_json(decision_path, template)
    return {
        "status": "CREATED_NOT_GOLD",
        "source_id": bundle.payload.source.id,
        "source_sha256": bundle.payload.source.sha256,
        "bundle_sha256": bundle.bundle_sha256,
        "bundle": str(bundle_path),
        "decision_template": str(decision_path),
    }


def _validate(args: argparse.Namespace) -> dict[str, object]:
    bundle = load_bundle(args.bundle)
    decision = load_review_decision(args.decision)
    validate_review_decision(bundle, decision, require_final=True)
    return {
        "status": "VALID_FINAL_REVIEW",
        "source_id": decision.source_id,
        "source_sha256": decision.source_sha256,
        "bundle_sha256": decision.bundle_sha256,
    }


def _export(args: argparse.Namespace) -> dict[str, object]:
    bundle = load_bundle(args.bundle)
    decision = load_review_decision(args.decision)
    output = export_reviewed_gold(bundle, decision, args.output)
    return {
        "status": "EXPORTED_REVIEWED_GOLD_FOR_DIFF",
        "source_id": decision.source_id,
        "source_sha256": decision.source_sha256,
        "output": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create and validate real-DOCX adjudication artifacts without using "
            "production output as the gold oracle."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--source", required=True)
    create.add_argument("--bundle", required=True)
    create.add_argument("--decision-template", required=True)
    create.set_defaults(handler=_create)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--bundle", required=True)
    validate.add_argument("--decision", required=True)
    validate.set_defaults(handler=_validate)

    export = subparsers.add_parser("export-reviewed-gold")
    export.add_argument("--bundle", required=True)
    export.add_argument("--decision", required=True)
    export.add_argument("--output", required=True)
    export.set_defaults(handler=_export)

    args = parser.parse_args()
    result = args.handler(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
