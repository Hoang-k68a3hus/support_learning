# DOCX Structure Real Pilot V0.1

This directory contains the first **real-world DOCX structural validation corpus** for Universal Source Understanding.

It is intentionally separate from `benchmarks/docx_structure_v0_1/`, which contains deterministic generated OOXML fixtures used to validate benchmark mechanics and known structural contracts.

## Scope

The real pilot currently contains five public Microsoft Word documents from official UK government sources. `sources.json` pins the exact URL, byte length and SHA-256 source revision used by the benchmark.

The selected landing pages state Open Government Licence v3.0. That does not create a blanket claim over third-party material that may be embedded in a source document; source licensing must still be reviewed before redistributing document bytes elsewhere.

The benchmark currently downloads the exact public source revision at execution time and verifies the pinned digest. The source documents are not vendored into this repository.

## Gold workflow

The evaluation oracle is **not** the production DOCX adapter.

The intended workflow is:

```text
public DOCX source
    ↓
independent OOXML audit (`source_audit.py`)
    ↓
candidate structural observations
    ↓
review / adjudication
    ↓
`gold_contracts.json` (frozen)
    ↓
production DOCX adapter + pipeline
    ↓
comparison against frozen contracts
```

`source_audit.py` is an annotation assistant. It is deliberately independent of `DocxAdapter`, but it is **not evaluated dynamically as the gold oracle**. Changing audit code must not silently rewrite benchmark expectations. Adjudicated expectations live in `gold_contracts.json` and change only through an explicit benchmark-gold review.

## Evaluation layers

The real pilot reports errors by structural layer:

- **L0 — Source fidelity**: pinned source revision, tables/rows/cells, notes, referenced header/footer stories, structural-loss diagnostics and other source-preservation contracts.
- **L1 — Element understanding**: currently frozen heading/level and Word navigation-role expectations.
- **L2 — Structural grouping**: LogicalUnit/integrity grouping. Full real-document gold is not yet adjudicated in V0.1.
- **L3 — Document structure**: hierarchy/regions/relations/readiness. V0.1 currently freezes only selected readiness expectations; full hierarchy/region/relation gold remains future work.

The coverage flags in `gold_contracts.json` are part of the benchmark contract. A green V0.1 result therefore means **the frozen partial contracts pass**, not that all structural decisions across the documents are correct. In particular, `errors_by_level.L2_structural_grouping == 0` while L2 coverage is `NOT_YET_FULLY_ADJUDICATED` must not be interpreted as a measured L2 accuracy of 100%.

## TOC / outline policy

Word outline metadata does not automatically mean a paragraph is a canonical content heading.

Built-in table-of-contents styles are treated as navigation material:

- `TOCHeading` / `TOC Heading` → `docx_navigation_role = "toc_title"`
- `TOC1` through `TOC9` → `docx_navigation_role = "toc_entry"`

Their style and outline observations are preserved, but they remain source `PARAGRAPH` elements and do not become canonical document-hierarchy nodes merely because a TOC style carries `outlineLvl`.

This rule was adjudicated after the real flexible-working policy exposed `Contents` with style `TOCHeading`. Treating every outline-bearing paragraph as a content heading would incorrectly insert navigation structure into the document hierarchy. The frozen L1 contract includes the observed TOC title and TOC entries for the two real pilot documents that contain them.

## Running

The benchmark requires internet access because it verifies the pinned public source revisions:

```bash
python -m benchmarks.docx_structure_real_v0_1.run_benchmark \
  --fail-on-error \
  --report /tmp/docx-structure-real-v0.1-report.json
```

For source inspection during annotation/adjudication:

```bash
python -m benchmarks.docx_structure_real_v0_1.source_audit \
  --source real-docx-01-flexible-policy
```

## L2/L3 adjudication artifacts

Use the adjudication command when preparing full LogicalUnit, hierarchy,
region, or structural-relation gold. It downloads the pinned revision once,
verifies its byte length and SHA-256, and then records two deliberately separate
views of those exact bytes:

1. independent OOXML observations from `source_audit.py`;
2. the current production parser output, clearly labelled as a prediction.

Create a bundle and an explicitly non-gold review template:

```bash
python -m benchmarks.docx_structure_real_v0_1.adjudication create \
  --source real-docx-01-flexible-policy \
  --bundle /tmp/real-docx-01.bundle.json \
  --decision-template /tmp/real-docx-01.review.json
```

The generated review template has `status: DRAFT` and `gold: null`. A reviewer
must inspect the source document, use benchmark-only ids, fill a valid
`GoldDocumentStructure`, state the exact L2/L3 coverage, and record decisions.
The production ids in the bundle are debugging aids and must never be copied
into gold. See `ADJUDICATION_GUIDELINE.md` for the field-level workflow.

Validate a completed decision:

```bash
python -m benchmarks.docx_structure_real_v0_1.adjudication validate \
  --bundle /tmp/real-docx-01.bundle.json \
  --decision /tmp/real-docx-01.review.json
```

Export the reviewed per-document annotation to a new file for code review:

```bash
python -m benchmarks.docx_structure_real_v0_1.adjudication export-reviewed-gold \
  --bundle /tmp/real-docx-01.bundle.json \
  --decision /tmp/real-docx-01.review.json \
  --output /tmp/real-docx-01.gold.json
```

The command refuses to overwrite files and specifically refuses to write
`gold_contracts.json`. Export is not benchmark integration: the reviewed file
must still be inspected, versioned, and wired into evaluation in a separate
gold-contract change. This prevents a production run or an unreviewed draft from
silently changing the oracle.

## CI policy

Network-dependent corpus evaluation is intentionally separated from deterministic required CI.

- `source-understanding-ci.yml` runs unit tests and the generated reproducible DOCX benchmark without depending on external document hosts.
- `source-understanding-real-docx.yml` runs the pinned real corpus on relevant pull requests, weekly schedule and manual dispatch.
- On a pull request, the external-corpus benchmark step is non-blocking so a source-host/network outage cannot masquerade as a deterministic code regression. Review the benchmark JSON/exit status in its log rather than treating a green workflow badge alone as evidence that all real contracts passed.
- Scheduled/manual real-corpus runs remain strict and fail when a frozen contract fails.

## Current limitations

V0.1 is a **five-document, assistant-adjudicated, partial real-world structural contract**, not a statistically meaningful accuracy benchmark and not a human double-annotated corpus.

The next real-data milestone is to adjudicate full element/grouping/hierarchy/region/relation gold for these five documents, then expand coverage toward roughly 30 diverse DOCX files before making a real-world accuracy claim.
