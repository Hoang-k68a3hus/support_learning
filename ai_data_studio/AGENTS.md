# AI Data Studio engineering rules

This directory is a data-development bounded context downstream of
`source_understanding`.

## Dependency direction

```text
source_understanding  <-  ai_data_studio
```

- `source_understanding` must never import `ai_data_studio`.
- AI Data Studio may consume canonical source-understanding schemas and
  evaluation contracts.
- Runtime semantic providers belong in `source_understanding`; annotation
  workflows, gold production, training projections, workbench integrations,
  and dataset publication belong here.

## Layer responsibilities

```text
schemas
  -> validation
  -> repositories / dataset construction
  -> services
  -> integrations / CLI
```

Keep dependencies acyclic. Do not make schema modules import repositories,
services, training projections, or integrations. Generic dataset construction
must not depend on model-specific training packages.

## Gold-data invariants

- `SemanticWorkingRecord` is working/audit state; it is not frozen gold.
- Suggestions are proposals and must never become gold without adjudicated
  decisions.
- Cross-object validation is fail-closed and must never silently repair stale
  source, target, evidence, review, or split state.
- Dataset split assignment is owned by `DatasetSplitManifest`, not by working
  records or annotation batches.
- Source families, split groups, exact source revisions, documents, and physical
  targets must not leak across TRAIN/DEV/TEST.
- Gold compilation uses canonical documents as the source-text authority and
  preserves target-scoped evaluation so unreviewed targets are not treated as
  negatives.
- Frozen dataset versions are immutable. Corrections require a new version.
- Frozen split identity must use the same canonical semantic-gold hash as the
  evaluation report for that split.
- Stable source lineage (`source_family_id` and `split_group_id`), compiler
  identity, eligibility-policy identity/hash, guideline identity, and working
  schema identity are part of the compiled Gold case certification.

## Persistence and integrations

- Repositories persist aggregate snapshots; they do not decide semantic
  validity or workflow transitions.
- JSONL repository behavior is fail-closed on malformed or duplicate records and
  assumes a single writer unless a stronger backend is introduced.
- Argilla or another annotation workbench is an adapter/UI, never the source of
  truth. External responses must pass through project-owned review and
  validation contracts before becoming decisions.

## Testing

For AI Data Studio changes, keep fresh-process import tests, data corruption
cases, stale source/target tests, split leakage tests, deterministic compilation
and hashing tests, freeze/tamper tests, and dependency-boundary regressions.
When CI is available, `ai_data_studio/**` and `tests/ai_data_studio/**` must be
covered by compile, Ruff, Pyright, and unittest gates.
