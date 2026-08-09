# M2.1/M2.2 validation contracts

This package deterministically compares a `SemanticWorkingRecord` and
`WorkingBatch` with one exact `CanonicalDocument` revision. It reports
structured source, target, text-snapshot, evidence, batch, and review-chain
issues without mutating or repairing any input.

The review hash-chain check proves continuity between recorded hashes and that
the terminal hash equals the current decisions. It does not prove a replayable
audit history because M2.1 does not store historical decision snapshots.

M2.2 also validates supplied dataset split-group topology and resolves valid
records through a separate `DatasetSplitManifest`; it never writes split state
into a working record or batch. It depends on the correctness of supplied
family/group identities and does not perform fuzzy or semantic near-duplicate
detection.

These milestones intentionally do not provide persistence, JSONL repositories,
gold compilation or eligibility policy, dataset freezing, Argilla integration,
services, or a CLI. Those remain later milestones.
