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

- Camelot `foo.pdf`, whose quickstart/fixture material establishes one 7x7 ruled table and published content anchors;
- Camelot page-level count fixtures;
- Camelot row-span and column-span challenge fixtures;
- Camelot `twotables_2.pdf`, whose regression asserts two tables and whose two published CSVs establish two independent 13x8 structures and cell content;
- an image-only native-text hard negative;
- PyMuPDF `strict-yes-no.pdf`, whose upstream `lines_strict`/Markdown regression publishes an exact 5x3 table.

Pinned Camelot benchmark material independently establishes:

- `foo.pdf` → one 7x7 table with published cell content;
- `row_span_1.pdf` → one 40x4 table and a row-span challenge;
- `column_span_2.pdf` → one 11x7 table and a column-span challenge;
- `twotables_2.pdf` → two 13x8 tables with independently published cell content.

This is **not representative coverage** of arbitrary PDFs.

## Capability contracts

- `SUPPORTED_REQUIRED`: the published source/count/structural/topology oracle must be satisfied.
- `MUST_PRESERVE_UNSTRUCTURED`: the native pipeline must not invent supported structure for a known fail-closed case; source truth is still retained separately.
- `OBSERVE` remains a valid schema state for future evidence collection, but no current pilot case relies on it after M2.6.

Current required positives are:

- Camelot `foo.pdf`: exactly one 7x7 table with its published content anchors, while the following native paragraph remains preserved despite sharing one TextPage block with the table's final row;
- PyMuPDF `strict-yes-no.pdf`: exact 5x3 structure and all published cell anchors;
- Camelot `row_span_1.pdf`: exactly one 40x4 table with at least one rectangular row span;
- Camelot `column_span_2.pdf`: exactly one 11x7 table with at least one rectangular column span;
- Camelot `twotables_2.pdf`: exactly two 13x8 tables, distinguished by independently published body-cell anchors.

The image-only fixture remains a native-text hard negative because OCR is outside this milestone.

## M2.6 source-ownership evidence

`foo.pdf` was not promoted merely because a detector returned the expected shape. M2.6 first established an independent source-ownership contract for the one native TextPage block that crosses the table boundary:

- the table-owned text is a contiguous prefix of complete native lines;
- the following paragraph is a residual suffix of complete native lines;
- no character, word, span, or native line is split;
- every nonblank span must be wholly on one side of the candidate boundary;
- mixed/partial overlap fails closed;
- table spans and residual spans are disjoint;
- their union must equal the original crossing block's source spans exactly;
- the residual is emitted with fragment-scoped source identity and fragment-union bbox rather than pretending to be the original whole TextPage block;
- derived cell text may remove outer whitespace for structural comparison, while exact source-span text remains unchanged in provenance.

On the pinned `foo.pdf`, the crossing block's table prefix ends at native line `80`. Residual lines `81–83`, including source span orders `92–94`, are preserved once as a paragraph fragment. This measurement is corpus evidence, not a fixture-specific production rule: production code contains no `foo.pdf` coordinates, text, line numbers, or expected table dimensions.

## Release-gated pilot result after M2.6

```text
known-count expected tables     5
predicted known-count tables    5
false-positive tables           0
missed source-truth tables      0
source-truth precision        1.0
source-truth recall           1.0
structural contracts            6
structural matches              6
capability cases                6
capability passes               6
```

These numbers describe this small pinned pilot only; they are **not** a claim about arbitrary PDF table extraction quality.

## Run

```bash
python -m benchmarks.pdf_tables_real_v0_1.run_benchmark \
  --output /tmp/pdf-table-benchmark.json \
  --enforce-capability-gate
```

CI uploads the JSON report so rejected-candidate diagnostics, source hashes, table shapes, and emitted non-trivial span facts remain inspectable.

## OCR boundary and non-goals

OCR is **not part of M2.6**. Image-only PDFs remain native-text misses and are preserved as such. OCR/VLM/rendered-text recovery is deferred to a later optional extension with its own provenance and evaluation.

M2.6 also does not claim support for arbitrary irregular/L-shaped merges, overlapping cells, character/span splitting across table boundaries, table-in-the-middle source-block partitioning, outside-prefix/table-suffix partitioning, cross-page table continuation, semantic header inference, or visual-only tables. Those remain later milestones and require independent evidence before parser behavior expands.

M2.7 continuation evidence is versioned separately from this M2.6 table-shape
pilot. This benchmark has no pinned cross-page continuation source truth and
must not be used to promote `CONTINUES` capability. The M2.7 structural tests
therefore keep synthetic observations separate from this real-PDF gold until an
independently adjudicated adjacent-page corpus is pinned.
