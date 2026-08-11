from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import Field, model_validator

from ai_data_studio.schemas import WorkingBatch
from source_understanding.schemas.context import Identifier, SchemaModel
from source_understanding.schemas.document import CanonicalDocument

from .argilla_orchestration import ArgillaImportResult, ArgillaReviewOrchestrator
from .argilla_remote import ArgillaSyncReport
from .argilla_webhook import parse_argilla_response_webhook
from .errors import ArgillaReviewContextNotFoundError
from .webhook_transport import StandardArgillaWebhookVerifier


class ArgillaReviewApplicationContext(SchemaModel):
    batch: WorkingBatch
    documents: dict[Identifier, CanonicalDocument]

    @model_validator(mode="after")
    def validate_documents(self) -> "ArgillaReviewApplicationContext":
        for document_id, document in self.documents.items():
            if document.document_id != document_id:
                raise ValueError(
                    "review context document mapping key must equal CanonicalDocument.document_id"
                )
        return self


class ArgillaReviewContextResolver(Protocol):
    def resolve(self, batch_id: Identifier) -> ArgillaReviewApplicationContext | None:
        """Resolve the authoritative batch/document snapshot for one review batch."""
        ...


class ArgillaReviewReadinessProbe(Protocol):
    def check(self) -> "ArgillaReviewReadiness":
        """Return dependency readiness without mutating application state."""
        ...


class ArgillaReviewReadiness(SchemaModel):
    ready: bool
    dependency: str = Field(min_length=1, max_length=128)
    detail: str = Field(min_length=1, max_length=1024)


class ArgillaWebhookApplicationResult(SchemaModel):
    webhook_id: Identifier
    response_id: Identifier
    record_id: Identifier
    applied: bool
    duplicate: bool


class MappingArgillaReviewContextResolver:
    """Deterministic resolver useful for local services/tests and explicit snapshots."""

    def __init__(
        self,
        contexts: Mapping[Identifier, ArgillaReviewApplicationContext],
    ) -> None:
        self._contexts = dict(contexts)

    def resolve(self, batch_id: Identifier) -> ArgillaReviewApplicationContext | None:
        return self._contexts.get(batch_id)


class StaticArgillaReviewReadinessProbe:
    """Simple readiness probe for environments where remote health is checked elsewhere."""

    def __init__(self, readiness: ArgillaReviewReadiness) -> None:
        self._readiness = readiness

    def check(self) -> ArgillaReviewReadiness:
        return self._readiness


class ArgillaReviewApplication:
    """Application boundary for trusted review operations and signed webhooks."""

    def __init__(
        self,
        *,
        orchestrator: ArgillaReviewOrchestrator,
        context_resolver: ArgillaReviewContextResolver,
        webhook_verifier: StandardArgillaWebhookVerifier,
        readiness_probe: ArgillaReviewReadinessProbe,
    ) -> None:
        self._orchestrator = orchestrator
        self._context_resolver = context_resolver
        self._webhook_verifier = webhook_verifier
        self._readiness_probe = readiness_probe

    def export_batch(
        self,
        *,
        batch_id: Identifier,
        guidelines: str,
    ) -> ArgillaSyncReport:
        context = self._require_context(batch_id)
        return self._orchestrator.export_batch(
            batch=context.batch,
            documents=context.documents,
            guidelines=guidelines,
        )

    def handle_signed_webhook(
        self,
        body: bytes,
        headers: Mapping[str, str],
    ) -> ArgillaWebhookApplicationResult:
        verified = self._webhook_verifier.verify(body, headers)
        parsed = parse_argilla_response_webhook(verified.payload)
        context = self._require_context(parsed.submission.batch_id)
        imported = self._orchestrator.apply_response_webhook(
            verified.payload,
            batch=context.batch,
            documents=context.documents,
        )
        return _application_result(verified.webhook_id, imported)

    def readiness(self) -> ArgillaReviewReadiness:
        return self._readiness_probe.check()

    def _require_context(self, batch_id: Identifier) -> ArgillaReviewApplicationContext:
        context = self._context_resolver.resolve(batch_id)
        if context is None:
            raise ArgillaReviewContextNotFoundError(batch_id)
        if context.batch.batch_id != batch_id:
            raise ValueError(
                "review context resolver returned a batch whose batch_id does not match the lookup key"
            )
        return context


def _application_result(
    webhook_id: Identifier,
    imported: ArgillaImportResult,
) -> ArgillaWebhookApplicationResult:
    return ArgillaWebhookApplicationResult(
        webhook_id=webhook_id,
        response_id=imported.response_id,
        record_id=imported.record.record_id,
        applied=imported.applied,
        duplicate=imported.duplicate,
    )
