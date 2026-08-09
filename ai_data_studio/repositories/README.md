# M2.3 working-record repository

`JsonlWorkingRecordRepository` is a deterministic local/pilot backend for the
current `SemanticWorkingRecord` aggregate snapshot. It uses one canonical JSON
object per line, lexical `record_id` ordering, whole-record upserts, and atomic
same-filesystem replacement. `save_many()` checks the complete input set before
one replacement, so a duplicate or identity-conflicting bulk update cannot
partially persist. Replacing a `record_id` cannot change its batch, document,
content hash, element snapshot hash, target kind/ID, or target element
membership/order. A new source or target identity requires a new `record_id`.

This backend assumes a single writer; concurrent writers can lose updates.
It performs local Pydantic deserialization only. It does not run semantic
cross-object validation, enforce workflow/status transitions, validate review
chains, migrate schema versions, compile gold data, freeze datasets, or retain
event history. Callers must orchestrate those responsibilities outside the
persistence layer.
