# PDF M2.3 — Table Recall Foundation

M2.3 expands native-PDF table recall without weakening the source-preservation boundary established by M1/M2.

## Scope

Detection order is intentionally precision-first:

1. `lines_strict` remains the primary path for simple vector-line tables.
2. An accepted line table always owns the page region and prevents a competing text projection.
3. If no line table is accepted, M2.3 inspects page vector evidence. Strong rectilinear evidence keeps the page on the line/topology path; an incidental rejected line candidate alone does not block text fallback.
4. Text-aligned fallback is allowed only when the page does **not** show strong rectilinear vector-table evidence.
5. The fallback works only from native TextPage spans. It does not render, OCR, call a VLM, or infer missing source text.

M2.3 intentionally does **not** call full-page `find_tables(strategy="text")`: on prose-heavy real PDFs that strategy can form very large virtual grids. The adapter instead uses a smaller source-near alignment contract below.

## Text-aligned acceptance contract

A borderless candidate must have all of the following:

- at least three rows and three columns by default;
- the same column count across a contiguous visual row run;
- repeated left- or right-edge alignment for every column;
- positive whitespace between neighboring columns;
- sufficient vertical whitespace between rows;
- no repeated punctuation/operator lane such as `=` or `:`;
- complete ownership of every nonblank span in each consumed native source block;
- contiguous consumed source blocks;
- no overlap with another accepted table's source ownership.

The table, rows and cells are `DERIVED` structure. Cell text is reconstructed only from the exact native spans assigned to that cell, and those spans remain in `pdf_source_spans` audit metadata.

## Fail-closed behavior

M2.3 deliberately keeps the original M1 blocks instead of projecting a table when evidence is ambiguous. Important failure classes include:

- `complex_or_merged_cells`;
- `rectilinear_evidence_no_strict_candidate`;
- `text_aligned_insufficient_column_gap`;
- `text_aligned_dense_row_spacing`;
- `text_aligned_rows_too_far_apart`;
- `text_aligned_operator_lane`;
- `text_aligned_source_block_crosses_boundary`;
- `text_aligned_source_blocks_noncontiguous`.

The real-PDF benchmark aggregates these diagnostics only **after independent gold has established a known-count miss**. `m2_3_failure_audit.failure_class_case_counts` counts how many missed source/page cases expose each class, while `candidate_reason_occurrences` keeps raw candidate counts. Production diagnostics explain misses; they never define source truth.

CI requires every remaining known-count missed case in the pilot to have a diagnostic failure classification. This makes recall work debuggable without lowering the table acceptance threshold.

## OCR boundary

OCR is **not part of M2.3**. Image-only pages remain unparsed for text and continue to produce the existing image/native-text diagnostics. OCR may be added later as an optional extension with its own provenance, quality gates and benchmark; M2.3 must not depend on it.

## Evaluation

The existing `pdf_tables_real_v0_1` benchmark remains authoritative for its frozen source truth and capability contracts. M2.3 may improve recall only when independent gold supports the new behavior; it must not rewrite source-truth labels to match parser output.

The current pilot still has no real borderless fixture promoted to `SUPPORTED_REQUIRED`. Candidate real fixtures were inspected, but none provided both a compatible source layout and an independent full-page oracle strong enough to freeze as new positive gold. Synthetic tests therefore lock the borderless detector's invariants, while real-corpus recall remains visible rather than being improved through speculative annotation or threshold relaxation.
