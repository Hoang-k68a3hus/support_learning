# Real PDF Table Benchmark v0.1

This is a deliberately small **real-PDF structural pilot** for the native PDF M2 table pipeline. It exists to stop recall work from silently degrading source fidelity or precision.

## Separation of concerns

The benchmark freezes four independent facts and never conflates them:

1. **Source truth** — table counts only when the upstream oracle actually establishes a page-level count.
2. **Structural oracle** — table shape and selected/exact cell content when upstream tests publish them.
3. **Topology oracle** — only coarse span facts independently established by the upstream fixture purpose, currently `ROW_SPAN` and `COLUMN_SPAN`.
4. **Current capability expectation** — whether PDF M2 must structure a case now, must preserve it unstructured, or is still observation-only.

`source_truth_table_count: null` is valid. It means the upstream material proves a target table's structure/content but does **not** prove the total number of tables on that page. Count metrics exclude those cases rather than turning an inference into gold.

Topology gold is intentionally weaker than production metadata. For example, the row-span fixture requires **at least one real row span**, but the benchmark does not invent exact merged-cell coordinates unless an independent upstream oracle establishes them.

The gold/evaluator do not import the production PDF detector. Production output is converted to a small page/table prediction at the runner boundary and only then scored.

## Corpus

The pilot pins immutable PDF fixtures from exact upstream commits. PDF binaries are **not stored in this repository**. `sources.json` pins:

- upstream repository + exact commit;
- exact fixture path and raw URL;
- Git blob SHA-1 and byte count;
- a rights note that avoids claiming ownership of third-party fixture content.

Downloads are fail-closed: byte count, Git blob identity, `%PDF-` signature, and maximum size are verified before parsing. SHA-256 is computed into the benchmark report for audit.

The current pilot includes:

- Camelot page-level count fixtures;
- Camelot row-span and column-span challenge fixtures;
- an image-only native-text hard negative;
- PyMuPDF `strict-yes-no.pdf`, whose upstream `lines_strict`/Markdown regression publishes an exact 5x3 table.

Pinned Camelot benchmark CSVs independently establish the current M2.4 merged-table shapes:

- `row_span_1.pdf` → one 40x4 table and a row-span challenge;
- `column_span_2.pdf` → one 11x7 table and a column-span challenge.

This is **not representative coverage** of arbitrary PDFs.

## Capability contracts

- `SUPPORTED_REQUIRED`: the published source/count/structural/topology oracle must be satisfied.
- `MUST_PRESERVE_UNSTRUCTURED`: the native pipeline must not invent supported structure for a known fail-closed case; source truth is still retained separately.
- `OBSERVE`: the case contributes audit/recall evidence but is not yet a release gate.

Current required positives are:

- PyMuPDF `strict-yes-no.pdf`: exact 5x3 structure and all published cell anchors;
- Camelot `row_span_1.pdf`: exactly one 40x4 table with at least one rectangular row span;
- Camelot `column_span_2.pdf`: exactly one 11x7 table with at least one rectangular column span.

`foo.pdf` remains fail-closed because source blocks cross the candidate boundary. `twotables_2.pdf` remains observation-only because M2.4 still does not expose a defensible strict-line candidate for those two legitimate tables.

## Run

```bash
python -m benchmarks.pdf_tables_real_v0_1.run_benchmark \
  --output /tmp/pdf-table-benchmark.json \
  --enforce-capability-gate
```

CI uploads the JSON report so rejected-candidate diagnostics, source hashes, table shapes, and emitted non-trivial span facts remain inspectable.

## OCR boundary and non-goals

OCR is **not part of M2.4**. Image-only PDFs remain native-text misses and are preserved as such. OCR/VLM/rendered-text recovery is deferred to a later optional extension with its own provenance and evaluation.

M2.4 also does not claim support for arbitrary irregular/L-shaped merges, overlapping cells, cross-page table continuation, semantic header inference, or visual-only tables. Those remain later milestones and must be added with independent gold before expanding parser behavior.
