from __future__ import annotations

import json
import os
from collections.abc import Mapping
from importlib import import_module
from typing import Any

from pydantic import Field, SecretStr, model_validator

from source_understanding.schemas.context import Identifier, JsonObject, SchemaModel

from .errors import (
    ArgillaWebhookAuthenticationError,
    ArgillaWebhookTransportError,
)


DEFAULT_ARGILLA_WEBHOOK_MAX_BODY_BYTES = 256 * 1024
_REQUIRED_STANDARD_WEBHOOK_HEADERS = (
    "webhook-id",
    "webhook-timestamp",
    "webhook-signature",
)


class ArgillaWebhookTransportConfig(SchemaModel):
    webhook_secret: SecretStr
    max_body_bytes: int = Field(
        default=DEFAULT_ARGILLA_WEBHOOK_MAX_BODY_BYTES,
        ge=1024,
        le=4 * 1024 * 1024,
    )

    @model_validator(mode="after")
    def validate_config(self) -> "ArgillaWebhookTransportConfig":
        if not self.webhook_secret.get_secret_value().strip():
            raise ValueError("webhook_secret must not be blank")
        return self

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "ArgillaWebhookTransportConfig":
        values = os.environ if env is None else env
        secret = values.get("ARGILLA_WEBHOOK_SECRET")
        if secret is None or not secret.strip():
            raise ValueError(
                "required environment variable ARGILLA_WEBHOOK_SECRET is missing or blank"
            )
        max_body_raw = values.get("ARGILLA_WEBHOOK_MAX_BODY_BYTES")
        max_body = DEFAULT_ARGILLA_WEBHOOK_MAX_BODY_BYTES
        if max_body_raw is not None:
            try:
                max_body = int(max_body_raw)
            except ValueError as exc:
                raise ValueError(
                    "environment variable ARGILLA_WEBHOOK_MAX_BODY_BYTES must be an integer"
                ) from exc
        return cls(webhook_secret=SecretStr(secret.strip()), max_body_bytes=max_body)


class VerifiedArgillaWebhook(SchemaModel):
    webhook_id: Identifier
    payload: JsonObject


class _VerifiedPayload(SchemaModel):
    payload: JsonObject


class StandardArgillaWebhookVerifier:
    """Verify the exact raw request body before exposing a parsed Argilla event."""

    def __init__(
        self,
        config: ArgillaWebhookTransportConfig,
        *,
        webhook_cls: Any | None = None,
    ) -> None:
        self.config = config
        self._webhook_cls = webhook_cls or _load_standard_webhook_class()

    def verify(
        self,
        body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedArgillaWebhook:
        if not body:
            raise ArgillaWebhookTransportError("Argilla webhook request body must not be empty")
        if len(body) > self.config.max_body_bytes:
            raise ArgillaWebhookTransportError(
                "Argilla webhook request body exceeds configured size limit"
            )

        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        for name in _REQUIRED_STANDARD_WEBHOOK_HEADERS:
            value = normalized_headers.get(name)
            if value is None or not value.strip():
                raise ArgillaWebhookAuthenticationError(
                    f"Argilla webhook is missing required Standard Webhooks header {name!r}"
                )

        try:
            verifier = self._webhook_cls(
                whsecret=self.config.webhook_secret.get_secret_value()
            )
            verified = verifier.verify(body, normalized_headers)
        except Exception as exc:
            raise ArgillaWebhookAuthenticationError(
                "Argilla webhook signature verification failed"
            ) from exc

        if isinstance(verified, Mapping):
            raw_payload: object = dict(verified)
        elif isinstance(verified, (str, bytes, bytearray)):
            try:
                raw_payload = json.loads(verified)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                raise ArgillaWebhookTransportError(
                    "verified Argilla webhook payload is not valid JSON"
                ) from exc
        else:
            raise ArgillaWebhookTransportError(
                "verified Argilla webhook payload must be a JSON object"
            )
        if not isinstance(raw_payload, dict):
            raise ArgillaWebhookTransportError(
                "verified Argilla webhook payload must be a JSON object"
            )

        try:
            payload = _VerifiedPayload(payload=raw_payload).payload
        except ValueError as exc:
            raise ArgillaWebhookTransportError(
                "verified Argilla webhook payload is not JSON-safe"
            ) from exc
        return VerifiedArgillaWebhook(
            webhook_id=normalized_headers["webhook-id"].strip(),
            payload=payload,
        )


def _load_standard_webhook_class() -> Any:
    try:
        module = import_module("standardwebhooks.webhooks")
        return module.Webhook
    except (ModuleNotFoundError, AttributeError) as exc:
        raise ArgillaWebhookTransportError(
            'Standard Webhooks verification requires "standardwebhooks>=1,<2"'
        ) from exc
