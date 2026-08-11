from __future__ import annotations

from importlib import import_module
from typing import Any

from .application import ArgillaReviewApplication
from .errors import (
    ArgillaRemoteError,
    ArgillaReviewContextNotFoundError,
    ArgillaWebhookAuthenticationError,
    ArgillaWebhookTransportError,
    ReviewContractError,
    ReviewStateError,
    StaleArgillaReviewTaskError,
    StaleReviewSubmissionError,
)


ARGILLA_WEBHOOK_PATH = "/webhooks/argilla"
REVIEW_LIVENESS_PATH = "/health/live"
REVIEW_READINESS_PATH = "/health/ready"


def create_argilla_review_fastapi_app(application: ArgillaReviewApplication) -> Any:
    """Create the minimal FastAPI transport for review webhook + health endpoints."""

    fastapi = _load_fastapi()
    app = fastapi.FastAPI(title="Support Learning AI Data Studio Review API", version="1")

    @app.get(REVIEW_LIVENESS_PATH)
    async def liveness() -> dict[str, object]:
        return {"status": "ok"}

    @app.get(REVIEW_READINESS_PATH)
    async def readiness() -> Any:
        status = application.readiness()
        body = status.model_dump(mode="json")
        if status.ready:
            return body
        return fastapi.responses.JSONResponse(status_code=503, content=body)

    @app.post(ARGILLA_WEBHOOK_PATH)
    async def argilla_webhook(request: Any) -> Any:
        body = await request.body()
        try:
            result = application.handle_signed_webhook(body, request.headers)
        except ArgillaWebhookAuthenticationError:
            raise fastapi.HTTPException(status_code=401, detail="invalid webhook signature")
        except (ArgillaWebhookTransportError, ReviewContractError) as exc:
            raise fastapi.HTTPException(status_code=400, detail=str(exc))
        except ArgillaReviewContextNotFoundError as exc:
            raise fastapi.HTTPException(status_code=404, detail=str(exc))
        except (
            ReviewStateError,
            StaleArgillaReviewTaskError,
            StaleReviewSubmissionError,
        ) as exc:
            raise fastapi.HTTPException(status_code=409, detail=str(exc))
        except ArgillaRemoteError:
            raise fastapi.HTTPException(status_code=503, detail="review dependency unavailable")
        return result.model_dump(mode="json")

    return app


def _load_fastapi() -> Any:
    try:
        return import_module("fastapi")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            'FastAPI transport requires "fastapi>=0.115,<1"'
        ) from exc
