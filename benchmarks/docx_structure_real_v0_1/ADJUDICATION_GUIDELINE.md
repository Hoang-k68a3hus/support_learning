# Real DOCX L2/L3 Adjudication Guideline V0.1

## Purpose

This workflow prepares reviewable structural gold for the pinned real-DOCX corpus. It does not generate gold automatically. The source document is the authority; independent OOXML audit records are evidence; production parser records are candidates to accept, reject, or amend.

The general element, LogicalUnit, ContextNode, ContentRegion, relation, and alignment rules in `../docx_structure_v0_1/ANNOTATION_GUIDELINE.md` apply here.

## Evidence boundaries

- `independent_evidence` is extracted directly from OOXML without importing or calling `DocxAdapter`. Its `audit_locator` values are derived review locators, not source facts and not canonical anchors.
- `production_prediction` is the current implementation output. Its ids are unstable implementation details and are forbidden in gold.
- Both views must have the same `id`, `bytes`, and `sha256` as the bundle source. The bundle fingerprint detects any later edit to either view.
- A review decision is bound to the exact bundle fingerprint and source hash. A source revision change requires a new bundle and a new review.
- Rendering is review evidence, not page/bbox provenance. Reflowable DOCX gold must not invent page locations from a particular renderer.

## Review procedure

1. Open the pinned DOCX in a renderer capable of showing tables, lists, headers/footers, notes, fields, and section boundaries.
2. Inspect `independent_evidence.body.ordered_blocks` and any referenced story or note records. Resolve discrepancies against the source package, not against the production prediction.
3. Create benchmark-only `GoldElement` ids and stable anchors. Preserve raw text and canonical source-story order; do not invent pages or bounding boxes.
4. Adjudicate L2 LogicalUnits only as structural/content-integrity units. Put definition, example, topic, exercise, and similar meaning in neither L2 nor L3 gold.
5. Adjudicate L3 ContextNodes, regions, and structural relations only from defensible evidence. Flat/unknown structure is valid. Do not repair sparse or irregular heading levels by inventing nodes.
6. Prefer native TITLE/HEADING context anchors, but allow a non-heading `GoldElement` to anchor inferred structure when source rendering plus independent structural evidence clearly supports the role. Keep the source-near element type unchanged, record the inference, and never promote arbitrary bullet/list/body items merely to complete a hierarchy.
7. Declare each level as `NOT_REVIEWED`, `PARTIAL`, or `FULL` and describe the measured scope. `PARTIAL` must name the included unit types, hierarchy area, region coverage, relation types, or readiness assertions.
8. Record disagreements and reasons in `decision_notes`. Include enough source locator/text context for another reviewer to reproduce the decision.
9. Set `status` to `FINAL` only after source-document inspection and independent OOXML audit are both listed in `review_methods`.

## Scope consistency enforced by validation

- A reviewed L2 decision must declare `evaluated_logical_unit_types`.
- An unreviewed L2 decision cannot carry LogicalUnit gold or an L2 evaluation scope.
- A reviewed L3 decision must contain at least one measurable hierarchy, region, relation, structure-mode, or readiness target.
- An unreviewed L3 decision cannot carry those targets.
- All `GoldDocumentStructure` reference, order, hierarchy-cycle, region-cover, relation-layer, source-hash, and immutability validators run before export.
- A `FINAL` decision requires a reviewer id, timezone-aware review time, review notes, source inspection, and independent audit.

## SU4.1 reviewed-gold integration

The five SU4.1 FINAL decisions live under `reviewed_gold/`. They are intentionally separate from the older frozen partial `gold_contracts.json`:

- `gold_contracts.json` remains the backwards-compatible partial L0/L1 contract;
- `reviewed_gold/*.review.json` carries the assistant-adjudicated L2/L3 oracle and its review provenance;
- `run_reviewed_benchmark.py` compares production against the reviewed decisions only after the gold is frozen.

The SU4.1 review is single-reviewer/assistant-adjudicated, not human double annotation. Its metrics therefore measure agreement on these five pinned documents and must not be presented as population-level real-world accuracy.

## Gold integration

`export-reviewed-gold` writes a new per-document annotation file only. It never updates the frozen partial `gold_contracts.json`. Integrate exported gold in a separate reviewed change that also:

- increments the relevant gold/adjudication version;
- updates coverage claims honestly;
- enables only metrics supported by the declared annotation scope;
- runs the parser after gold is frozen, never while choosing gold decisions;
- preserves the earlier frozen contracts unless the review documents a genuine gold correction.
