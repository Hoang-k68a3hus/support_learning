# AI Data Studio dataset contracts

Dataset splits are versioned construction decisions expressed at the
`split_group_id` level. They are not stored on `SemanticWorkingRecord` or
`WorkingBatch`. A source family must belong to one hard leakage group, and each
group resolves to exactly one `train`, `dev`, or `test` assignment.

The deterministic split-manifest content hash excludes audit-only `created_at`,
`created_by`, and metadata. Split validation checks supplied family/group
identities; it does not discover mislabeled paraphrases, translations, minimal
pairs, or other semantic near duplicates.

Semantic gold compilation is fail closed. `SemanticGoldCompiler` validates each
working record against its exact canonical document and working-batch contract
before projecting any gold data. When the authoritative `WorkingBatch` mapping
is supplied, complete batch membership is validated as well. Legacy callers may
omit the batch mapping only when the compiler can deterministically reconstruct
one consistent reviewed batch from the records; ambiguous or unreviewed inputs
are rejected.

Canonical documents own source text; working records own target scopes and
adjudicated decisions; the split manifest alone owns split assignment. The
compiler emits target-scoped Gold V3 data and excludes suggestions, rationales,
reviewer identities, decision confidence, and other workflow noise. Compiled
dataset metadata records the exact guideline version, eligibility-policy
identity/hash, split-manifest hash, and a deterministic validated-working-set
hash.

`SemanticGoldFreezer` is the public release boundary. Before invoking the atomic
freezer it verifies that the caller-declared guideline and eligibility-policy
identity match compiler-owned metadata and requires both policy and validated
working-set hashes to be present. The underlying freeze implementation then
performs atomic publication and round-trip/hash verification.
