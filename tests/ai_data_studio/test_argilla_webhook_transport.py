from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import unittest

from ai_data_studio.review.errors import (
    ArgillaWebhookAuthenticationError,
    ArgillaWebhookTransportError,
)
from ai_data_studio.review.webhook_transport import (
    ArgillaWebhookTransportConfig,
    StandardArgillaWebhookVerifier,
)
from pydantic import SecretStr


class ArgillaWebhookTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_bytes = b"0123456789abcdef0123456789abcdef"
        self.secret = base64.b64encode(self.secret_bytes).decode("ascii")
        self.config = ArgillaWebhookTransportConfig(
            webhook_secret=SecretStr(self.secret),
            max_body_bytes=4096,
        )
        self.verifier = StandardArgillaWebhookVerifier(self.config)

    def signed_request(self, payload: dict[str, object]):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        webhook_id = "msg_test_1"
        timestamp = str(int(time.time()))
        signed = b".".join(
            (webhook_id.encode("utf-8"), timestamp.encode("utf-8"), body)
        )
        digest = hmac.new(self.secret_bytes, signed, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": f"v1,{signature}",
        }
        return body, headers

    def test_valid_standard_webhook_verifies_exact_raw_body(self) -> None:
        body, headers = self.signed_request(
            {"type": "response.created", "version": 1, "data": {"id": "r1"}}
        )

        verified = self.verifier.verify(body, headers)

        self.assertEqual(verified.webhook_id, "msg_test_1")
        self.assertEqual(verified.payload["type"], "response.created")

    def test_modified_body_and_missing_headers_fail_authentication(self) -> None:
        body, headers = self.signed_request({"type": "response.created"})

        with self.assertRaises(ArgillaWebhookAuthenticationError):
            self.verifier.verify(body + b" ", headers)

        incomplete = dict(headers)
        del incomplete["webhook-signature"]
        with self.assertRaises(ArgillaWebhookAuthenticationError):
            self.verifier.verify(body, incomplete)

    def test_size_limit_is_checked_before_signature_verification(self) -> None:
        verifier = StandardArgillaWebhookVerifier(
            ArgillaWebhookTransportConfig(
                webhook_secret=SecretStr(self.secret),
                max_body_bytes=1024,
            )
        )
        body, headers = self.signed_request({"blob": "x" * 2000})

        with self.assertRaises(ArgillaWebhookTransportError):
            verifier.verify(body, headers)

    def test_config_requires_secret_and_valid_integer_limit(self) -> None:
        with self.assertRaises(ValueError):
            ArgillaWebhookTransportConfig.from_env({})
        with self.assertRaises(ValueError):
            ArgillaWebhookTransportConfig.from_env(
                {
                    "ARGILLA_WEBHOOK_SECRET": self.secret,
                    "ARGILLA_WEBHOOK_MAX_BODY_BYTES": "not-an-int",
                }
            )


if __name__ == "__main__":
    unittest.main()
