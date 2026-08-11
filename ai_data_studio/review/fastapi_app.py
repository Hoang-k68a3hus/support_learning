from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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


def create_argilla_review_fastapi_app(application: ArgillaReviewApplication) -> FastAPI:
    """Create the minimal FastAPI transport for review webhook + health endpoints."""

    app = FastAPI(title="Support Learning AI Data Studio Review API", version="1")

    @app.get(REVIEW_LIVENESS_PATH)
    async def liveness() -> dict[str, object]:
        return {"status": "ok"}

    @app.get(REVIEW_READINESS_PATH)
    async def readiness() -> object:
        status = application.readiness()
        body = status.model_dump(mode="json")
        if status.ready:
            return body
        return JSONResponse(status_code=503, content=body)

    @app.post(ARGILLA_WEBHOOK_PATH)
    async def argilla_webhook(request: Request) -> object:
        body = await request.body()
        try:
            result = application.handle_signed_webhook(body, request.headers)
        except ArgillaWebhookAuthenticationError as exc:
            raise HTTPException(status_code=401, detail="invalid webhook signature") from exc
        except (ArgillaWebhookTransportError, ReviewContractError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ArgillaReviewContextNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            ReviewStateError,
            StaleArgillaReviewTaskError,
            StaleReviewSubmissionError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArgillaRemoteError as exc:
            raise HTTPException(
                status_code=503,
                detail="review dependency unavailable",
            ) from exc
        return result.model_dump(mode="json")

    return app
