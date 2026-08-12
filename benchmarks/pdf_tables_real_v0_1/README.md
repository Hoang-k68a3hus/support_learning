# Real PDF Table Benchmark v0.1

This is a deliberately small **real-PDF structural pilot** for PDF M2. It exists to stop table recall work from silently degrading source fidelity or precision.

## Separation of concerns

The benchmark freezes three independent facts and never conflates them:

1. **Source truth** — table counts only when the upstream oracle actually establishes a page-level count.
2. **Structural oracle** — table shape and selected/exact cell content when upstream tests publish them.
3. **Current capability expectation** — whether PDF M2 must structure a case now, must preserve it unstructured, or is still observation-only.

`source_truth_table_count: null` is valid. It means the upstream material proves a target table's structure/content but does **not** prove the total number of tables on that page. Count metrics exclude those cases rather than turning an inference into gold.

A merged-cell table remains a real source table even when M2 v1 intentionally refuses to project it into `TABLE/TABLE_ROW/TABLE_CELL`. We therefore report source-truth count metrics separately from the capability gate.

The gold/evaluator do not import the production PDF detector. Production output is converted to a small page/table prediction at the runner boundary and only then scored.

## Corpus

The pilot pins immutable PDF fixtures from exact upstream commits. PDF binaries are **not stored in this repository**. `sources.json` pins:

- upstream repository + exact commit;
- exact fixture path and raw URL;
- Git blob SHA-1 and byte count;
- a rights note that avoids claiming ownership of third-party fixture content.

Downloads are fail-closed: byte count, Git blob identity, `%PDF-` signature, and maximum size are verified before parsing. SHA-256 is computed into the benchmark report for audit.

The current pilot includes:

- Camelot page-level positive/count fixtures and merged-cell challenges;
- an image-only native-text hard negative;
- PyMuPDF `strict-yes-no.pdf`, whose upstream `lines_strict`/Markdown regression publishes an exact 5x3 table. This is the first real `SUPPORTED_REQUIRED` M2 contract.

This is **not representative coverage** of arbitrary PDFs.

## Capability contracts

- `SUPPORTED_REQUIRED`: the published source/count/structural oracle must be satisfied.
- `MUST_PRESERVE_UNSTRUCTURED`: M2 v1 must not invent a supported table for a known unsupported case; source truth is still retained separately.
- `OBSERVE`: the case contributes audit/recall evidence but is not yet a release gate.

The current fail-closed contracts cover the image-only fixture plus known merged/row-span/column-span challenges. `twotables_2.pdf` remains observation-only because the current detector does not expose enough evidence to classify why those legitimate tables are missed.

## Run

```bash
python -m benchmarks.pdf_tables_real_v0_1.run_benchmark \
  --output /tmp/pdf-table-benchmark.json \
  --enforce-capability-gate
```

CI uploads the JSON report so rejected-candidate diagnostics and source hashes remain inspectable.

## Explicit non-goals

This benchmark does not claim that PDF M2 v1 supports borderless tables, merged cells, row/column spans, cross-page continuations, OCR tables, semantic header inference, or arbitrary layout/VLM reconstruction. Those remain later milestones and must be added with independent gold before expanding parser behavior.
