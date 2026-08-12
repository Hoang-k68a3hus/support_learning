# Real PDF Table Benchmark v0.1

This is a deliberately small **real-PDF structural pilot** for the native PDF M2 table pipeline. It exists to stop recall work from silently degrading source fidelity or precision.

## Separation of concerns

The benchmark freezes four independent facts and never conflates them:

1. **Source truth** — table counts only when the upstream oracle actually establishes a page-level count.
2. **Structural oracle** — table shape and selected/exact cell content when upstream tests publish them.
3. **Topology oracle** — only coarse span facts independently established by the upstream fixture purpose, currently `ROW_SPAN` and `COLUMN_SPAN`.
4. **Current capability expectation** — whether PDF M2 must structure a case now or must preserve it unstructured.

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
- Camelot `twotables_2.pdf`, whose regression asserts two tables and whose two published CSVs establish two independent 13x8 structures and cell content;
- an image-only native-text hard negative;
- PyMuPDF `strict-yes-no.pdf`, whose upstream `lines_strict`/Markdown regression publishes an exact 5x3 table.

Pinned Camelot benchmark CSVs independently establish:

- `row_span_1.pdf` → one 40x4 table and a row-span challenge;
- `column_span_2.pdf` → one 11x7 table and a column-span challenge;
- `twotables_2.pdf` → two 13x8 tables with independently published cell content.

This is **not representative coverage** of arbitrary PDFs.

## Capability contracts

- `SUPPORTED_REQUIRED`: the published source/count/structural/topology oracle must be satisfied.
- `MUST_PRESERVE_UNSTRUCTURED`: the native pipeline must not invent supported structure for a known fail-closed case; source truth is still retained separately.
- `OBSERVE` remains a valid schema state for future evidence collection, but no current pilot case relies on it after M2.5.

Current required positives are:

- PyMuPDF `strict-yes-no.pdf`: exact 5x3 structure and all published cell anchors;
- Camelot `row_span_1.pdf`: exactly one 40x4 table with at least one rectangular row span;
- Camelot `column_span_2.pdf`: exactly one 11x7 table with at least one rectangular column span;
- Camelot `twotables_2.pdf`: exactly two 13x8 tables, distinguished by independently published body-cell anchors.

`foo.pdf` remains fail-closed because a native source block crosses the candidate boundary. The image-only fixture remains a native-text hard negative because OCR is outside this milestone.

## M2.5 evidence

M2.5 does not trust permissive PyMuPDF `strategy="lines"` topology directly. It requires disconnected source-vector regions, rebuilds logical row/column boundaries from actual PDF vector strokes, trims unstable caption/gutter geometry, and then sends the normalized candidate through the existing source-span and rectangular-topology verifier.

The release-gated real-pilot result after M2.5 is:

- known-count expected tables: `5`;
- predicted known-count tables: `4`;
- false-positive known-count tables: `0`;
- source-truth precision: `1.0`;
- source-truth recall: `0.8`;
- remaining known-count miss: only `camelot-foo`.

These numbers describe this small pinned pilot only; they are not a claim about arbitrary PDF table extraction quality.

## Run

```bash
python -m benchmarks.pdf_tables_real_v0_1.run_benchmark \
  --output /tmp/pdf-table-benchmark.json \
  --enforce-capability-gate
```

CI uploads the JSON report so rejected-candidate diagnostics, source hashes, table shapes, and emitted non-trivial span facts remain inspectable.

## OCR boundary and non-goals

OCR is **not part of M2.5**. Image-only PDFs remain native-text misses and are preserved as such. OCR/VLM/rendered-text recovery is deferred to a later optional extension with its own provenance and evaluation.

M2.5 also does not claim support for arbitrary irregular/L-shaped merges, overlapping cells, arbitrary source-block splitting across table boundaries, cross-page table continuation, semantic header inference, or visual-only tables. Those remain later milestones and must be added with independent gold before expanding parser behavior.
