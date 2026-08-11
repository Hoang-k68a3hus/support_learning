# AI Data Studio validation contracts

This package deterministically compares a `SemanticWorkingRecord` and
`WorkingBatch` with one exact `CanonicalDocument` revision. It reports
structured source, target, text-snapshot, evidence, batch, and review-chain
issues without mutating or repairing any input.

The review hash-chain check proves continuity between recorded hashes and that
the terminal hash equals the current decisions. It does not prove a replayable
audit history because historical decision snapshots are not stored.

Dataset split validation resolves records through a separate
`DatasetSplitManifest`; split state is never written into a working record or
batch. Validation depends on the correctness of supplied family/group identities
and does not perform fuzzy or semantic near-duplicate detection.

Current milestone status:

- M2.1 cross-object working-record, batch, evidence, and review validation: complete;
- M2.2 split topology and leakage validation: complete;
- M2.3 deterministic JSONL working-record repository: complete for single-writer local/pilot use;
- M2.4 fail-closed semantic gold compilation: complete; compilation now runs mandatory cross-object validation instead of relying on caller convention;
- M2.5 atomic dataset freezing and verification: complete.

The JSONL repository is intentionally single-writer and is not a concurrent
annotation backend. Semantic near-duplicate discovery, Argilla integration,
workflow services, and a user-facing CLI remain separate future work.
