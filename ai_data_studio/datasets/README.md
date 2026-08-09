# M2.2 dataset split contract

Dataset splits are versioned construction decisions expressed at the
`split_group_id` level. They are not stored on `SemanticWorkingRecord` or
`WorkingBatch`. A source family must belong to one hard leakage group, and each
group resolves to exactly one `train`, `dev`, or `test` assignment.

The deterministic manifest content hash excludes audit-only `created_at`,
`created_by`, and metadata. M2.2 validates supplied family/group identities; it
does not discover mislabeled paraphrases, translations, minimal pairs, or other
near duplicates. It also does not plan ratios, rebalance labels, reshuffle
records, persist manifests, or freeze dataset artifacts.

M2.4 adds a fail-closed semantic gold compiler. It accepts exact canonical
documents, adjudicated working records, a split manifest, and an explicit
eligibility policy. Canonical documents own source text; working records own
target scopes and decisions; the split manifest alone owns split assignment.
The compiler emits target-scoped Gold V3 data and intentionally excludes
suggestions, rationales, reviewer details, decision confidence, and other
workflow state. It returns an in-memory candidate only; freezing remains M2.5.
Callers must run the M2.1 working-record/batch/canonical validation first; the
compiler deliberately does not duplicate evidence, review-chain, or target
snapshot validation. Dataset compilation does run M2.2 split resolution and
fails if that topology is invalid.
