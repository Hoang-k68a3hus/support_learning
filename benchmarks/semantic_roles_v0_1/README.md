# Semantic roles benchmark contract v0.3

This is a small adjudicated development benchmark for the optional semantic
enrichment stage. It is intentionally separate from DOCX parsing gold: parser
quality must be established before semantic predictions are scored.

Targets are source-stable signatures:

- `ELEMENT` targets use one canonical element order;
- `LOGICAL_UNIT` targets use the ordered member-element orders.

Runtime IDs are never gold identities. Every case pins the canonical exact-source
`content_hash` separately from a deterministic `element_snapshot_hash`. The
evaluator refuses to score a prediction from a different document, source
revision, or ordered text/type snapshot.

Schema V3 stores `raw_text` and `normalized_text` independently for every gold
element, and validates each evidence span against its declared text view. Its
evaluation mask is target-scoped: a prediction is scored only when the exact
target has a scope containing that annotation type. Predictions outside that
scope are ignored rather than treated as false positives.

Run the deterministic baseline from the repository root:

```powershell
python -m benchmarks.semantic_roles_v0_1.run_benchmark
```

The pilot covers English and Vietnamese explicit role markers plus negative
examples where role words occur without an accepted leading marker. It is a
development fixture, not evidence that the heuristic generalizes to natural
semantic phrasing.

Cases carry an explicit `dev` or locked `test` split. Retrieval quality gates can
only be built from the `test` report; a DEV report is diagnostic and cannot
authorize semantic projection. This pilot predates independent test collection,
so its TEST split validates gate mechanics but is not an unbiased generalization
estimate.
