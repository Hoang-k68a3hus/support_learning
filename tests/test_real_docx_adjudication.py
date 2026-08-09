from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from benchmarks.docx_structure_real_v0_1.adjudication import (
    AdjudicationBundle,
    ReviewCoverage,
    ReviewCoverageStatus,
    ReviewDecision,
    ReviewLevel,
    ReviewMethod,
    ReviewStatus,
    build_adjudication_bundle,
    build_review_template,
    export_reviewed_gold,
    validate_review_decision,
    _create,
)
from benchmarks.docx_structure_v0_1.adjudicated_pilot import build_pilot_cases
from source_understanding.evaluation.schemas import (
    BenchmarkSourceKind,
    GoldDocumentStructure,
    GoldSourceDescriptor,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_REAL_GOLD = (
    ROOT / "benchmarks" / "docx_structure_real_v0_1" / "gold_contracts.json"
)


class RealDocxAdjudicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        case = build_pilot_cases()[1]
        digest = "sha256:" + hashlib.sha256(case.payload).hexdigest()
        cls.payload = case.payload
        cls.source = {
            "id": "real-review-fixture",
            "file_name": "real-review-fixture.docx",
            "document_class": "table_fixture",
            "url": "https://example.invalid/real-review-fixture.docx",
            "source_page": "https://example.invalid/real-review-fixture",
            "license": "test-only",
        }
        cls.pin = {
            **cls.source,
            "bytes": len(case.payload),
            "sha256": digest,
        }
        cls.bundle = build_adjudication_bundle(cls.source, cls.pin, cls.payload)

        raw_gold = case.gold.model_dump(mode="json")
        raw_gold["document_id"] = cls.source["id"]
        raw_gold["source"] = GoldSourceDescriptor(
            file_name=cls.source["file_name"],
            sha256=digest,
            language="en",
            document_class=cls.source["document_class"],
            source_kind=BenchmarkSourceKind.PUBLIC,
            provenance={"purpose": "adjudication regression fixture"},
        ).model_dump(mode="json")
        cls.gold = GoldDocumentStructure.model_validate(raw_gold)

    def _final_decision_payload(self) -> dict[str, object]:
        template = build_review_template(self.bundle).model_dump(mode="json")
        template.update(
            {
                "status": ReviewStatus.FINAL.value,
                "reviewer_id": "reviewer-test",
                "reviewed_at": datetime(
                    2026, 8, 9, 10, 0, tzinfo=timezone.utc
                ).isoformat(),
                "review_methods": [
                    ReviewMethod.SOURCE_DOCUMENT_INSPECTION.value,
                    ReviewMethod.INDEPENDENT_OOXML_AUDIT.value,
                    ReviewMethod.PRODUCTION_OUTPUT_COMPARISON.value,
                ],
                "coverage": ReviewCoverage(
                    L2_structural_grouping=ReviewLevel(
                        coverage=ReviewCoverageStatus.PARTIAL,
                        scope=("TABLE_BLOCK exact membership",),
                    ),
                    L3_document_structure=ReviewLevel(
                        coverage=ReviewCoverageStatus.PARTIAL,
                        scope=("regions and selected structural relations",),
                    ),
                ).model_dump(mode="json"),
                "decision_notes": [
                    "Reviewed the source package and amended candidate structure independently."
                ],
                "gold": self.gold.model_dump(mode="json"),
            }
        )
        return template

    def test_bundle_binds_independent_and_production_views_to_one_revision(self) -> None:
        source = self.bundle.payload.source
        audit = self.bundle.payload.independent_evidence
        prediction = self.bundle.payload.production_prediction

        self.assertEqual(audit["sha256"], source.sha256)
        self.assertEqual(prediction["sha256"], source.sha256)
        self.assertEqual(audit["bytes"], source.bytes)
        self.assertEqual(prediction["bytes"], source.bytes)
        self.assertIn("ordered_blocks", audit["body"])
        self.assertEqual(audit["body"]["ordered_blocks"][0]["audit_locator"]["provenance"], "DERIVED")
        self.assertIn("row_cells", audit["body"]["tables"][0])
        self.assertIn("processing_manifest", prediction["pipeline"])

    def test_bundle_fingerprint_rejects_tampering(self) -> None:
        raw = self.bundle.model_dump(mode="json")
        raw["payload"]["review_instructions"].append("tampered")
        with self.assertRaisesRegex(ValidationError, "fingerprint mismatch"):
            AdjudicationBundle.model_validate(raw)

    def test_bundle_rejects_unpinned_source_bytes(self) -> None:
        with self.assertRaisesRegex(ValueError, "source revision mismatch"):
            build_adjudication_bundle(
                self.source,
                self.pin,
                self.payload + b"changed",
            )

    def test_review_template_is_explicitly_not_gold(self) -> None:
        decision = build_review_template(self.bundle)
        self.assertEqual(decision.status, ReviewStatus.DRAFT)
        self.assertIsNone(decision.gold)
        with self.assertRaisesRegex(ValueError, "must be FINAL"):
            validate_review_decision(self.bundle, decision)

    def test_final_review_requires_source_and_independent_audit(self) -> None:
        raw = self._final_decision_payload()
        raw["review_methods"] = [
            ReviewMethod.SOURCE_DOCUMENT_INSPECTION.value,
            ReviewMethod.PRODUCTION_OUTPUT_COMPARISON.value,
        ]
        with self.assertRaisesRegex(ValidationError, "missing required methods"):
            ReviewDecision.model_validate(raw)

    def test_final_review_rejects_blank_review_identity_and_scope(self) -> None:
        raw = self._final_decision_payload()
        raw["reviewer_id"] = " "
        with self.assertRaisesRegex(ValidationError, "reviewer_id"):
            ReviewDecision.model_validate(raw)

        raw = self._final_decision_payload()
        raw["coverage"]["L2_structural_grouping"]["scope"] = [" "]
        with self.assertRaisesRegex(ValidationError, "scope entries"):
            ReviewDecision.model_validate(raw)

    def test_final_real_review_requires_public_source_provenance(self) -> None:
        raw = self._final_decision_payload()
        raw["gold"]["source"]["source_kind"] = BenchmarkSourceKind.GENERATED.value
        with self.assertRaisesRegex(ValidationError, "source_kind PUBLIC"):
            ReviewDecision.model_validate(raw)

    def test_final_review_rejects_unreviewed_l2_gold(self) -> None:
        raw = self._final_decision_payload()
        raw["coverage"]["L2_structural_grouping"] = {
            "coverage": ReviewCoverageStatus.NOT_REVIEWED.value,
            "scope": [],
        }
        with self.assertRaisesRegex(ValidationError, "unreviewed L2"):
            ReviewDecision.model_validate(raw)

    def test_public_validator_rechecks_model_copy_that_skipped_validation(self) -> None:
        decision = ReviewDecision.model_validate(self._final_decision_payload())
        bypassed = decision.model_copy(update={"review_methods": ()})
        with self.assertRaisesRegex(ValidationError, "missing required methods"):
            validate_review_decision(self.bundle, bypassed)

    def test_valid_final_review_can_export_without_mutating_frozen_contract(self) -> None:
        decision = ReviewDecision.model_validate(self._final_decision_payload())
        self.assertEqual(
            validate_review_decision(self.bundle, decision),
            decision,
        )
        original = FROZEN_REAL_GOLD.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reviewed-gold.json"
            exported = export_reviewed_gold(self.bundle, decision, output)
            payload = json.loads(exported.read_text(encoding="utf-8"))
            self.assertEqual(payload["document_id"], self.source["id"])
            self.assertEqual(payload["source"]["sha256"], self.pin["sha256"])
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                export_reviewed_gold(self.bundle, decision, output)
        self.assertEqual(FROZEN_REAL_GOLD.read_bytes(), original)

    def test_export_api_refuses_direct_frozen_contract_target(self) -> None:
        decision = ReviewDecision.model_validate(self._final_decision_payload())
        with self.assertRaisesRegex(ValueError, "cannot overwrite gold_contracts"):
            export_reviewed_gold(self.bundle, decision, FROZEN_REAL_GOLD)

    def test_create_cli_rejects_same_bundle_and_decision_path_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "same.json"
            with self.assertRaisesRegex(ValueError, "must be different"):
                _create(
                    Namespace(
                        source="not-resolved",
                        bundle=str(output),
                        decision_template=str(output),
                    )
                )


if __name__ == "__main__":
    unittest.main()
