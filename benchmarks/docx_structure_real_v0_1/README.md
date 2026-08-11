# DOCX Structure Real Pilot V0.1

This directory contains the first **real-world DOCX structural validation corpus** for Universal Source Understanding.

It is intentionally separate from `benchmarks/docx_structure_v0_1/`, which contains deterministic generated OOXML fixtures used to validate benchmark mechanics and known structural contracts.

## Scope

The real pilot contains five public Microsoft Word documents from official UK government sources. `sources.json` pins the exact URL, byte length and SHA-256 source revision used by the benchmark.

The selected landing pages state Open Government Licence v3.0. That does not create a blanket claim over third-party material that may be embedded in a source document; source licensing must still be reviewed before redistributing document bytes elsewhere.

The benchmark downloads the exact public source revision at execution time and verifies the pinned digest. The source documents are not vendored into this repository.

## Gold workflow

The evaluation oracle is **not** the production DOCX adapter.

```text
public DOCX source
    ↓
source-document inspection + independent OOXML audit
    ↓
review / adjudication
    ↓
FINAL reviewed structural gold
    ↓
production DOCX adapter + source-understanding pipeline
    ↓
comparison against frozen reviewed gold
```

`source_audit.py` is an annotation assistant. It is deliberately independent of `DocxAdapter`, but it is not automatically gold. `production_prediction` in an adjudication bundle is also not gold. A disagreement is resolved against the pinned source document and independent source evidence.

The older `gold_contracts.json` is retained as a frozen partial compatibility contract. SU4.1 reviewed L2/L3 gold is stored separately in `reviewed_gold/*.review.json`; those files preserve the FINAL review status, source/bundle fingerprints, declared coverage, decision notes and validated `GoldDocumentStructure` in one artifact.

## Evaluation layers

- **L0 — Source fidelity**: pinned revision, tables/rows/cells, notes, referenced stories and explicit structural-loss diagnostics. The existing frozen contract and real-corpus validation cover this layer.
- **L1 — Element understanding**: SU4.1 marks this `PARTIAL`; source-near facts needed to align reviewed L2/L3 targets are retained, and explicitly reviewed disagreements remain visible.
- **L2 — Structural grouping**: SU4.1 has `FULL` review coverage for the declared integrity-unit types in each of the five documents, including visible/native list groups, source-native table blocks and the labelled key-value form group where applicable.
- **L3 — Document structure**: SU4.1 has `FULL` review coverage for the declared context hierarchy, full-cover modality regions, supported positive structural relations, structure mode and structural readiness.

`FULL` means full coverage of the **declared SU4.1 scope on these five pinned documents**. It does not mean population-level accuracy and does not make this a statistically representative benchmark.

## Context/source-fact separation

A ContextNode is inferred structure; a `GoldElement` is source-near representation. They must not be collapsed into one label.

Native `TITLE`/`HEADING` anchors are preferred. A non-heading source element may anchor a reviewed ContextNode only when source rendering plus independent structural evidence makes the role defensible—for example, a numbered legal clause that functions as an outline section. The source-near element remains `PARAGRAPH` or `LIST_ITEM`; adjudication does not rewrite it into `HEADING` merely to make hierarchy convenient.

## TOC / outline policy

Word outline metadata does not automatically mean a paragraph is a canonical content heading.

Built-in table-of-contents styles are navigation material:

- `TOCHeading` / `TOC Heading` → `docx_navigation_role = "toc_title"`
- `TOC1` through `TOC9` → `docx_navigation_role = "toc_entry"`

Their source style/outline observations are preserved, but they remain source `PARAGRAPH` elements and do not become canonical content-hierarchy nodes merely because a TOC style carries `outlineLvl`.

## Running the frozen partial compatibility benchmark

The benchmark requires internet access because it verifies the pinned public source revisions:

```bash
python -m benchmarks.docx_structure_real_v0_1.run_benchmark \
  --fail-on-error \
  --report /tmp/docx-structure-real-v0.1-report.json
```

## Running the SU4.1 reviewed benchmark

```bash
python -m benchmarks.docx_structure_real_v0_1.run_reviewed_benchmark \
  --report /tmp/docx-structure-real-su4.1-report.json
```

Do **not** add `--fail-on-error` merely to get a green baseline. The purpose of SU4.1 is to expose production disagreements with frozen reviewed gold. After an implementation fix is independently justified, the strict option can be used as a regression gate:

```bash
python -m benchmarks.docx_structure_real_v0_1.run_reviewed_benchmark \
  --fail-on-error
```

The report contains the existing document-structure evaluator metrics plus reviewed-benchmark extensions for ContextNode anchor detection/level accuracy and LogicalUnit metrics broken down by evaluated type so large table blocks cannot hide list/key-value failures.

## Source inspection / adjudication commands

For independent source inspection:

```bash
python -m benchmarks.docx_structure_real_v0_1.source_audit \
  --source real-docx-01-flexible-policy
```

Create an adjudication bundle and a DRAFT review template:

```bash
python -m benchmarks.docx_structure_real_v0_1.adjudication create \
  --source real-docx-01-flexible-policy \
  --bundle /tmp/real-docx-01.bundle.json \
  --decision-template /tmp/real-docx-01.review.json
```

A reviewer must inspect the source document, use benchmark-only ids, fill a valid `GoldDocumentStructure`, state exact coverage and record decisions. Production ids in the bundle are debugging aids and must never be copied into gold. See `ADJUDICATION_GUIDELINE.md`.

Validate a completed decision:

```bash
python -m benchmarks.docx_structure_real_v0_1.adjudication validate \
  --bundle /tmp/real-docx-01.bundle.json \
  --decision /tmp/real-docx-01.review.json
```

`export-reviewed-gold` still refuses to overwrite `gold_contracts.json`; reviewed-gold integration is a separate code-review step.

## SU4.1 adjudication findings encoded in gold

The reviewed set intentionally preserves disagreements with the current implementation. Examples include:

- one visually continuous nested flexible-working list is a single gold `LIST_GROUP` even though Word changes `numId` internally;
- `numId=0` in the academy form disables numbering and therefore does not make those paragraphs gold `LIST_ITEM`s;
- the IVD form begins with a labelled `KEY_VALUE_GROUP`, not generic narrative text;
- the EPS guidance has a document-title/section hierarchy even though native heading levels are irregular;
- the contractor licence uses numbered legal clauses as defensible inferred context anchors while their source-near element type remains `LIST_ITEM`.

These are oracle decisions based on source inspection plus independent evidence, not post-hoc changes made to fit production.

## CI policy

Network-dependent corpus evaluation is intentionally separated from deterministic required CI.

- `source-understanding-ci.yml` runs unit tests and generated deterministic benchmarks without depending on external document hosts.
- `source-understanding-real-docx.yml` runs the pinned real corpus on relevant pull requests, weekly schedule and manual dispatch.
- The frozen partial benchmark remains strict on scheduled/manual runs.
- The SU4.1 reviewed benchmark should run as a measured comparison and publish its report; until the known gold disagreements are fixed, its non-zero structural disagreement count is expected evidence rather than a reason to change the oracle.
- A source-host/network outage must not be presented as a parser regression.

## Current limitations

SU4.1 is a **five-document, assistant-adjudicated real-world structural benchmark** with full declared L2/L3 coverage, not a human double-annotated corpus and not a statistically meaningful estimate of general real-world accuracy.

The next milestone is to use the reviewed metrics/error matrix to fix the weakest structural stage without changing gold, rerun the same frozen five documents, and then expand reviewed coverage toward roughly 30 diverse DOCX files before making broader accuracy claims.
