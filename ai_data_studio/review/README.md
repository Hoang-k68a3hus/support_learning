# M3 Human Review Integration

`SemanticWorkingRecord` remains the source of truth. Argilla is an external
review surface used to present review tasks and collect human decisions; it never
becomes the authoritative dataset model.

## M3.1 — Review boundary

```text
WorkingRecordRepository
        ↓
HumanReviewWorkflow.build_task
        ↓ immutable task + expected_decision_hash
review surface
        ↓ HumanReviewSubmission
HumanReviewWorkflow.apply_submission
        ↓ stale-hash check + ReviewAttempt + cross-object validation
WorkingRecordRepository
        ↓
SemanticGoldCompiler + freeze
```

Safety invariants:

- only `REVIEW_REQUIRED` records can be exported/applied;
- every task binds the exact current `decision_hash`;
- stale submissions fail before mutation;
- review guideline must match the authoritative `WorkingBatch`;
- `ACCEPT` cannot change decisions and `MODIFY` must change them;
- accepted/modified records become `PASS`, conflicts stay `REVIEW_REQUIRED`,
  rejects become `REJECT`;
- every applied review appends a `HUMAN` `ReviewAttempt`;
- the resulting record must pass `WorkingRecordValidator` against the exact
  canonical document and batch before persistence.

## M3.2 — Real Argilla synchronization

The concrete integration uses the Argilla 2.x SDK public API:

- `rg.Argilla(api_url=..., api_key=...)` for the remote client;
- `rg.Settings` + `rg.TextField` + `rg.LabelQuestion`/`rg.TextQuestion` for the
  review dataset contract;
- `rg.Dataset(...).create()` to create the review dataset when absent;
- `rg.Record(id=<working_record_id>, ...)` and `dataset.records.log(...)` for
  stable external-id upserts.

CI pins `argilla==2.8.0` so SDK construction drift is caught by the test suite.
The runtime module still imports Argilla lazily so non-review RAG workflows do
not require the SDK merely to import `ai_data_studio`.

### Runtime configuration

`ArgillaReviewConfig.from_env()` reads:

```text
ARGILLA_API_URL             required
ARGILLA_API_KEY             required
ARGILLA_WORKSPACE           default: argilla
ARGILLA_REVIEW_DATASET      default: support-learning-semantic-review
ARGILLA_TIMEOUT_SECONDS     default: 60
ARGILLA_RETRIES             default: 5
```

The API key is stored as Pydantic `SecretStr` and is not included as plain text
in normal model representations.

### Dataset contract

The integration creates exactly three fields:

1. `raw_text`
2. `normalized_text`
3. `review_context_json`

and exactly three questions:

1. `review_outcome` — `ACCEPT/MODIFY/CONFLICT/REJECT`;
2. `review_decisions_json` — optional canonical `AnnotationDecision[]` JSON;
3. `review_notes` — optional reviewer notes.

Existing datasets are fail-closed validated before reuse. Field/question drift,
outcome-label drift, or disabled extra metadata causes
`ArgillaDatasetContractError` rather than silently writing into an incompatible
annotation project.

### Idempotent task synchronization

Each exported record contains both:

- `expected_decision_hash` — protects the reviewed decision revision;
- `review_task_hash` — SHA-256 fingerprint of the full immutable
  `HumanReviewTask`, including source/target snapshot and guideline.

`ArgillaReviewRemote.sync_tasks()` therefore behaves as follows:

```text
remote id missing                    → create
same review_task_hash                → skip
changed review_task_hash, no review  → update
changed review_task_hash, active UI response → fail closed
```

The last rule prevents a new local source/task revision from silently replacing
what a human is currently reviewing.

### Response synchronization and provenance

The public `rg.Response` SDK object exposes user/value/status but not the review
resource timestamp. M3.2 therefore does **not** invent `reviewed_at` during a
polling import. The provenance-preserving import path is an Argilla webhook:

```text
response.created / response.updated webhook
        ↓
parse_argilla_response_webhook
        ↓ response updated_at + stable Argilla user id + exported metadata
ArgillaReviewOrchestrator.apply_response_webhook
        ↓ compare review_task_hash against current local task
HumanReviewWorkflow.apply_submission
        ↓
WorkingRecordRepository
```

Only webhook responses with `status=submitted` are accepted. The parser requires
the response `updated_at` timestamp and converts the reviewer identity to the
stable `argilla:<user-id>` form. Duplicate delivery of the same applied review is
recognized from the review-chain terminal transition and becomes a no-op rather
than appending a second `ReviewAttempt`.

A later edit of an already imported terminal Argilla response is intentionally
fail-closed and requires explicit reconciliation; M3.2 does not rewrite a
previous human adjudication silently.

### M3.2 orchestration example

```python
from ai_data_studio.review import (
    ArgillaReviewConfig,
    ArgillaReviewOrchestrator,
    ArgillaReviewRemote,
)

config = ArgillaReviewConfig.from_env()
remote = ArgillaReviewRemote(config)
orchestrator = ArgillaReviewOrchestrator(repository, remote)

orchestrator.export_batch(
    batch=batch,
    documents=documents,
    guidelines="Apply semantic-role guideline roles-v1.",
)
```

## M3.3 — Authenticated application/API boundary

M3.3 moves webhook trust out of the domain parser and into an explicit transport
boundary. Argilla implements Standard Webhooks, so the application verifies the
**exact raw HTTP body** together with the `webhook-id`, `webhook-timestamp`, and
`webhook-signature` headers before any JSON payload reaches
`parse_argilla_response_webhook()`.

```text
Argilla HTTP POST
        ↓ raw body + Standard Webhooks headers
StandardArgillaWebhookVerifier
        ↓ authenticated JsonObject + webhook_id
ArgillaReviewApplication
        ↓ resolve authoritative WorkingBatch + CanonicalDocument snapshot
ArgillaReviewOrchestrator
        ↓ stale/task/review-chain validation
WorkingRecordRepository
```

Transport configuration:

```text
ARGILLA_WEBHOOK_SECRET           required
ARGILLA_WEBHOOK_MAX_BODY_BYTES   default: 262144
```

The secret is stored as `SecretStr`. Signature failures expose only a generic
401 response and never include the signing secret or calculated signature.
The body-size limit is checked before signature verification.

### Application service

`ArgillaReviewApplication` owns the trusted application-level operations:

- `export_batch(batch_id=..., guidelines=...)` resolves the authoritative batch
  and source-document snapshot before delegating to M3.2 remote sync;
- `handle_signed_webhook(body, headers)` verifies transport authenticity before
  resolving batch/document context and applying the review;
- `readiness()` delegates to an injected readiness probe so deployment health
  policy remains outside the domain model.

`ArgillaReviewContextResolver` is deliberately a protocol. M3.3 does not invent a
new batch/document persistence system; production deployments can resolve review
context from the storage layer they actually own. `MappingArgillaReviewContextResolver`
is provided for deterministic local/test snapshots.

### FastAPI transport

`create_argilla_review_fastapi_app(application)` exposes only:

```text
GET  /health/live
GET  /health/ready
POST /webhooks/argilla
```

The webhook endpoint maps authentication failures to 401, malformed/unsupported
payloads to 400, missing review context to 404, stale/state conflicts to 409, and
remote dependency failures to 503. No admin batch-export HTTP endpoint is exposed
here because authorization for operational/admin actions belongs to the owning
application/backend boundary rather than to the AI Data Studio domain package.

FastAPI and Standard Webhooks are transport dependencies; they are not required
to import the source-understanding or base review-domain modules. CI installs and
checks them explicitly.

## Current boundary

```text
SOURCE FACTS / CanonicalDocument
        ↓
WorkingRecord + WorkingBatch
        ↓
M3.1 HumanReviewWorkflow
        ↓
M3.2 Argilla remote synchronization
        ↓
M3.3 authenticated HTTP/application boundary
        ↓
validated WorkingRecord
        ↓
SemanticGoldCompiler + immutable freeze
```

## Remaining operational work

- configure a real Argilla webhook and store its returned signing secret in the
  deployment secret manager;
- provide the concrete production `ArgillaReviewContextResolver` backed by the
  chosen batch/document storage;
- run a live Argilla Server HTTP E2E in the local/Docker integration environment;
- wire admin/operations authorization from the owning application backend rather
  than exposing unauthenticated mutation endpoints from this package.
