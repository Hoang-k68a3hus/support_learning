# PDF M2.3 — Table Recall Foundation

M2.3 expands native-PDF table recall without weakening the source-preservation boundary established by M1/M2.

## Scope

Detection order is intentionally precision-first:

1. `lines_strict` remains the primary path for simple vector-line tables.
2. If no supported/rejected line candidate exists, M2.3 inspects page vector evidence.
3. Text-aligned fallback is allowed only when the page does **not** show strong rectilinear vector-table evidence.
4. The fallback works only from native TextPage spans. It does not render, OCR, call a VLM, or infer missing source text.

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

- `rectilinear_evidence_no_strict_candidate`;
- `text_aligned_insufficient_column_gap`;
- `text_aligned_dense_row_spacing`;
- `text_aligned_rows_too_far_apart`;
- `text_aligned_operator_lane`;
- `text_aligned_source_block_crosses_boundary`;
- `text_aligned_source_blocks_noncontiguous`.

These diagnostics are intended to make future recall work measurable rather than hiding misses behind prompt or semantic heuristics.

## OCR boundary

OCR is **not part of M2.3**. Image-only pages remain unparsed for text and continue to produce the existing image/native-text diagnostics. OCR may be added later as an optional extension with its own provenance, quality gates and benchmark; M2.3 must not depend on it.

## Evaluation

The existing `pdf_tables_real_v0_1` benchmark remains authoritative for its frozen source truth and capability contracts. M2.3 may improve recall only when independent gold supports the new behavior; it must not rewrite source-truth labels to match parser output.
