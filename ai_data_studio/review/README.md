# M3.1 Human Review Workflow + Argilla Exchange

This package keeps `SemanticWorkingRecord` as the source of truth while allowing
review UIs such as Argilla to display review tasks and return human feedback.

## Boundary

```text
WorkingRecordRepository
        ↓
HumanReviewWorkflow.build_task
        ↓ immutable task + expected_decision_hash
Argilla / human review surface
        ↓ HumanReviewSubmission
HumanReviewWorkflow.apply_submission
        ↓ stale-hash check + ReviewAttempt + cross-object validation
WorkingRecordRepository
        ↓
SemanticGoldCompiler + freeze
```

Argilla is an external review surface, not the authoritative dataset model. The
exchange adapter is deliberately SDK-neutral so the core package does not take a
runtime dependency on a particular Argilla client version.

## Safety invariants

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

## Argilla exchange

`task_to_argilla_record()` produces an SDK-compatible record dictionary with:

- text fields for raw/normalized target text;
- canonical JSON context containing suggestions/current decisions;
- metadata binding `record_id`, `batch_id`, guideline, target and expected hash.

`argilla_settings_spec()` describes three questions:

1. `review_outcome` — one of `ACCEPT/MODIFY/CONFLICT/REJECT`;
2. `review_decisions_json` — optional canonical `AnnotationDecision[]` JSON;
3. `review_notes` — optional reviewer notes.

The explicit JSON decision payload is intentional in M3.1: it preserves the full
current decision contract (state, evidence, ontology, confidence, competing
labels) without reducing it to a UI-specific label schema. A richer task-specific
Argilla UI can be added later without changing the core workflow contract.
