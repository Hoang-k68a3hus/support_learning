from __future__ import annotations

import base64
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from ai_data_studio.repositories import JsonlWorkingRecordRepository
from ai_data_studio.review.application import (
    ArgillaReviewApplication,
    ArgillaReviewApplicationContext,
    ArgillaReviewReadiness,
    MappingArgillaReviewContextResolver,
    StaticArgillaReviewReadinessProbe,
)
from ai_data_studio.review.argilla_exchange import task_to_argilla_record
from ai_data_studio.review.argilla_orchestration import ArgillaReviewOrchestrator
from ai_data_studio.review.argilla_remote import ArgillaSyncReport
from ai_data_studio.review.contracts import HumanReviewTask
from ai_data_studio.review.fastapi_app import create_argilla_review_fastapi_app
from ai_data_studio.review.webhook_transport import (
    ArgillaWebhookTransportConfig,
    StandardArgillaWebhookVerifier,
)
from ai_data_studio.schemas import WorkingRecordStatus

from tests.ai_data_studio._validation_fixtures import (
    NOW,
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
)


class _CapturingRemote:
    def __init__(self) -> None:
        self.tasks = ()

    def sync_tasks(self, tasks, *, guidelines):
        del guidelines
        self.tasks = tuple(tasks)
        return ArgillaSyncReport(
            dataset_name="semantic-review",
            total=len(self.tasks),
            created=len(self.tasks),
            updated=0,
            skipped=0,
        )


class ArgillaReviewApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repository = JsonlWorkingRecordRepository(
            Path(self.temp_dir.name) / "working.jsonl"
        )
        self.document = canonical_document()
        self.batch = working_batch()
        self.record = working_record(
            self.document,
            decisions=(positive_definition(),),
            status=WorkingRecordStatus.REVIEW_REQUIRED,
        )
        self.repository.save(self.record)
        self.remote = _CapturingRemote()
        orchestrator = ArgillaReviewOrchestrator(self.repository, self.remote)
        context = ArgillaReviewApplicationContext(
            batch=self.batch,
            documents={self.document.document_id: self.document},
        )
        resolver = MappingArgillaReviewContextResolver(
            {self.batch.batch_id: context}
        )
        self.secret_bytes = b"0123456789abcdef0123456789abcdef"
        secret = base64.b64encode(self.secret_bytes).decode("ascii")
        verifier = StandardArgillaWebhookVerifier(
            ArgillaWebhookTransportConfig(webhook_secret=SecretStr(secret))
        )
        self.application = ArgillaReviewApplication(
            orchestrator=orchestrator,
            context_resolver=resolver,
            webhook_verifier=verifier,
            readiness_probe=StaticArgillaReviewReadinessProbe(
                ArgillaReviewReadiness(
                    ready=True,
                    dependency="argilla",
                    detail="configured",
                )
            ),
        )

    def payload(self) -> dict[str, object]:
        task = HumanReviewTask(
            record=self.record,
            guideline_version=self.batch.guideline_version,
            expected_decision_hash=self.record.decision_hash,
        )
        exported = task_to_argilla_record(task)
        metadata = dict(exported["metadata"])
        return {
            "type": "response.created",
            "version": 1,
            "timestamp": (NOW + timedelta(minutes=1)).isoformat(),
            "data": {
                "id": "response-application-1",
                "status": "submitted",
                "updated_at": (NOW + timedelta(minutes=1)).isoformat(),
                "values": {
                    "review_outcome": {"value": "ACCEPT"},
                    "review_decisions_json": {"value": ""},
                    "review_notes": {"value": "Reviewed through API."},
                },
                "record": {"id": "remote-record", "metadata": metadata},
                "user": {"id": "reviewer-1", "username": "reviewer"},
            },
        }

    def sign(self, payload: dict[str, object]):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        webhook_id = "msg_application_1"
        timestamp = str(int(time.time()))
        message = b".".join(
            (webhook_id.encode("utf-8"), timestamp.encode("utf-8"), body)
        )
        digest = hmac.new(self.secret_bytes, message, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
        return body, {
            "webhook-id": webhook_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": f"v1,{signature}",
            "content-type": "application/json",
        }

    def test_application_exports_authoritative_batch_context(self) -> None:
        report = self.application.export_batch(
            batch_id=self.batch.batch_id,
            guidelines="Review semantic roles using roles-v1.",
        )

        self.assertEqual(report.created, 1)
        self.assertEqual(len(self.remote.tasks), 1)
        self.assertEqual(self.remote.tasks[0].record, self.record)

    def test_signed_webhook_applies_once_and_preserves_webhook_id(self) -> None:
        body, headers = self.sign(self.payload())

        result = self.application.handle_signed_webhook(body, headers)

        self.assertEqual(result.webhook_id, "msg_application_1")
        self.assertTrue(result.applied)
        self.assertFalse(result.duplicate)
        stored = self.repository.get(self.record.record_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, WorkingRecordStatus.PASS)

    def test_fastapi_health_and_webhook_status_mapping(self) -> None:
        client = TestClient(create_argilla_review_fastapi_app(self.application))

        live = client.get("/health/live")
        ready = client.get("/health/ready")
        body, headers = self.sign(self.payload())
        accepted = client.post("/webhooks/argilla", content=body, headers=headers)
        invalid = client.post(
            "/webhooks/argilla",
            content=body + b" ",
            headers=headers,
        )

        self.assertEqual(live.status_code, 200)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["applied"])
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("signature", invalid.text.lower())

    def test_readiness_false_maps_to_503(self) -> None:
        application = ArgillaReviewApplication(
            orchestrator=ArgillaReviewOrchestrator(self.repository, self.remote),
            context_resolver=MappingArgillaReviewContextResolver({}),
            webhook_verifier=self.application._webhook_verifier,
            readiness_probe=StaticArgillaReviewReadinessProbe(
                ArgillaReviewReadiness(
                    ready=False,
                    dependency="argilla",
                    detail="unreachable",
                )
            ),
        )
        client = TestClient(create_argilla_review_fastapi_app(application))

        response = client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ready"])


if __name__ == "__main__":
    unittest.main()
