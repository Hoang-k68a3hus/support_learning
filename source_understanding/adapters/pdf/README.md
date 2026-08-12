# PDF Adapter — M2 Structural Content

`source_understanding.adapters.pdf` is the born-digital/native-text PDF boundary. M1 preserves visible native text, geometry, reading order, and provenance. M2 adds structural content only when the PDF provides enough auditable evidence to do so. OCR, image understanding, and semantic classification remain separate concerns.

## Pipeline

```text
exact PDF bytes
  -> validate/open
  -> standard/XMP metadata + page geometry
  -> PyMuPDF TextPage DICT (sort=False)
  -> native text blocks / lines / spans
  -> paint-order visibility gate
  -> M2 table detection
       -> lines_strict: simple ruled rectangular tables
       -> lines_strict_merged: verified rectangular rowspan/colspan tables
       -> text_aligned: conservative borderless native-text fallback
       -> segmented vector fallback (M2.5)
            -> disconnected drawing regions
            -> bounded regional lines candidate
            -> source-vector logical-grid normalization
            -> existing simple/merged verifier
       -> boundary-safe source ownership retry (M2.6)
            -> retry only a crossing-block rejection
            -> partition at complete native-line boundaries only
            -> private table-prefix detection view
            -> existing merged topology/source-span verifier
            -> exact residual suffix projection
            -> span conservation invariant
       -> adjacent-page table continuation evidence (M2.7)
            -> evidence only; no cross-page table merge
       -> rejected/ambiguous: preserve native text + diagnostic
  -> deterministic fail-closed reading order for non-table content
  -> RawElement[]
  -> SourceAdapterRunner
  -> format-agnostic SourceUnderstandingPipeline
```

OCR is **not** part of this pipeline. It is deferred as an optional later extension.

## Source / inference boundary

PDF normally does not expose paragraph, heading, or table semantics as authoritative tags. Visible text blocks therefore remain `PARAGRAPH` hints with `DERIVED` provenance. M2 table elements are also explicitly `DERIVED`: they represent a high-confidence structural projection from PDF geometry/text alignment plus exact native text-span ownership, not an explicit source tag.

The adapter never converts weak layout evidence into a source fact. Unsupported or ambiguous candidates remain native PDF text observations.

## Simple ruled tables

The `lines_strict` path is precision-first. It accepts a candidate only when there is a stable simple rectangular grid, enough populated content, unique native-span cell ownership, no source block crossing the candidate boundary, contiguous consumed source blocks, and no overlapping table ownership.

A verified table replaces the consumed paragraph blocks rather than duplicating them:

```text
TABLE
TABLE_ROW
TABLE_CELL ...
TABLE_ROW
TABLE_CELL ...
```

All table elements share the format-agnostic `integrity_group_id`, allowing the existing integrity consolidator to build one `TABLE_BLOCK` downstream without PDF-specific grouping logic.

## M2.3 borderless native-text fallback

When the page does not contain strong rectilinear vector evidence, M2.3 may infer a borderless table from repeated native text alignment. This fallback requires repeated 3+ row / 3+ column geometry, stable column lanes, adequate whitespace, exact source ownership, and contiguous source blocks. Equation/form operator lanes such as `=` or `:`, dense parallel prose, and ambiguous layouts fail closed.

The adapter deliberately does **not** call a whole-page `find_tables(strategy="text")` and trust the result, because prose pages can otherwise become false mega-grids.

## M2.4 rectangular merged topology

M2.4 adds `lines_strict_merged` for ruled tables containing rectangular row spans or column spans. It only retries line-table candidates that the simple path rejected as complex/merged.

A PyMuPDF `None` cell slot is never treated as an ordinary empty cell. It is accepted only when one rectangular anchor cell can be proven to cover that logical slot. The detector reconstructs global row/column boundaries and requires all of these invariants:

- exact logical row/column boundary counts;
- each non-`None` cell is the top-left anchor of its logical rectangle;
- every logical slot is covered by exactly one anchor cell;
- no overlap and no unexplained hole;
- a real span exists (`row_span > 1` or `column_span > 1`);
- every relevant native text span maps to exactly one anchor cell;
- consumed TextPage blocks cannot contain non-blank text outside the table;
- consumed blocks remain contiguous and cannot overlap another accepted table.

Accepted merged cells are emitted **once** at their anchor location. Covered logical slots do not receive duplicate text. M2.4 records `row_span`, `column_span`, and `logical_slots[]`. The merged topology version is `rectangular-spans-v1`.

## M2.5 disconnected multi-table segmentation

M2.5 handles the specific recall failure where a page contains multiple disconnected ruled tables but whole-page `lines_strict` exposes no defensible candidate.

The fallback is deliberately narrower than a generic permissive `strategy="lines"` retry:

1. page drawings are clustered into disconnected vector regions;
2. at least two non-overlapping regions are required;
3. each region is inspected independently;
4. regional `lines_strict` remains preferred;
5. if a bounded regional `lines` candidate is necessary, its raw grid is **not** trusted;
6. logical boundaries are rebuilt from actual source vector strokes;
7. weak outer gutters and leading/trailing material without a stable vertical grid are trimmed;
8. missing local separators may form only rectangular merged components;
9. the normalized candidate is sent through the existing source-span ownership, topology, contiguous-block, and overlap verifier;
10. if fewer than the configured minimum number of tables survive, all segmented structure is discarded and native text is preserved.

This prevents permissive candidate geometry from becoming source truth. M2.5 production behavior contains no fixture-specific coordinates, row/column counts, or text rules.

The segmentation contract version is `drawing-clusters-v1`.

## M2.6 boundary-safe source ownership

M2.6 addresses a narrower source-preservation problem: PyMuPDF may place the final table row and the paragraph immediately after it in the **same native TextPage block**. Earlier M2 versions correctly failed closed because consuming the whole block would lose non-table text, while accepting only table spans without an explicit residual contract would break provenance.

M2.6 does **not** introduce arbitrary source-block splitting. It supports only a strict shape:

```text
one original native block
  ├─ complete native lines belonging to the table     # contiguous prefix
  └─ complete native lines belonging to residual text # suffix
```

The partitioner requires:

- every nonblank span to be wholly inside or wholly outside the candidate table;
- no span partially crossing the candidate boundary;
- no native line mixing inside and outside nonblank spans;
- the first nonblank portion of the crossing block to belong to the table;
- table-owned lines to form one contiguous prefix;
- once residual content begins, table content may not reappear;
- visual order may not overlap beyond the configured geometry tolerance;
- table and residual line references must exactly cover the original native-line sequence without overlap.

If any condition is ambiguous, M2.6 rejects the retry and keeps the original source blocks authoritative.

### Private detection view, immutable source

The original `PdfBlockObservation` is never mutated. M2.6 builds a private detection-only block containing the table-owned prefix lines and reuses the existing M2.4 merged-table verifier. Accepted table fragments still reference the original `PdfSpanObservation` objects.

The following residual suffix is emitted separately as a `PARAGRAPH` with:

- `source_anchor.kind = "pdf_native_block_fragment"`;
- an anchor id scoped to the exact original page/block and native-line range;
- `pdf_native_bbox_scope = "source_line_fragment_union"`;
- the original whole-block native/displayed bbox retained in separate audit attributes;
- exact table-owned and residual native-line orders;
- the original native block number/order retained.

The residual is therefore explicit about being a projection of part of a TextPage block; it never masquerades as the original whole block.

### Conservation invariant

Before emitting a partitioned page, M2.6 verifies:

```text
table_source_spans ∩ residual_source_spans == ∅
table_source_spans ∪ residual_source_spans == original_crossing_block_source_spans
```

A missing, duplicated, or unexpected source span raises an adapter error instead of silently producing partial structure. A verified residual that unexpectedly becomes empty during emission also fails rather than being dropped.

### Derived cell text vs source-span text

Some TextPage spans contain layout whitespace such as trailing spaces. M2.6 applies `outer-whitespace-strip-v1` **only to the derived `TABLE_CELL.text` field for partitioned tables**. The exact source span text stored under `pdf_source_spans` is unchanged.

This distinction is intentional:

```text
SOURCE FACT
  pdf_source_spans[*].text = exact extracted span text

DERIVED STRUCTURE
  TABLE_CELL.text = structurally reconstructed text with outer whitespace removed
```

It allows a structural oracle such as `"2012_2"` to match without falsifying the extracted source text `"2012_2 "`.

### M2.6 versioned policy

```text
enable_boundary_safe_source_partitioning = true
boundary_partition_geometry_tolerance_points = 0.75
maximum_boundary_partitioned_blocks_per_table = 2
```

Current versions are:

```text
adapter                          8
policy                           9
table structure                  multi-strategy-v5
source block partition           native-line-prefix-v1
partitioned cell normalization   outer-whitespace-strip-v1
merged topology                  rectangular-spans-v1
multi-table segmentation         drawing-clusters-v1
table continuation evidence      adjacent-page-table-continuation-v1

M2.7 continuation is owned by the format-agnostic structural relation stage.
The PDF adapter emits normalized page-edge, table-width, column-lane, row/column
count, and topology evidence on each accepted TABLE fragment. The relation
builder may infer a directional `TABLE_BLOCK CONTINUES TABLE_BLOCK` relation
only for adjacent pages when the configured precision-first gates pass. A
repeated leading-row fingerprint is supporting evidence only; it is never
promoted to a semantic header fact. The
fragments, rows, cells, source spans, page identities, and bounding boxes remain
independent source-near objects.
```

## Cell text and provenance

Cell text is rebuilt from the exact TextPage spans owned by that cell; it is not trusted from a second semantic transcription. `source-spans-v1` preserves source block, line, and span native orders plus span text, native/displayed bboxes, fonts, flags, colors, alpha, and origins in cell audit metadata. Every table projection remains traceable to original PDF observations.

M2.6 adds source ownership metadata but does not promote inferred table structure into a source fact.

## Real-PDF measurement

The pinned benchmark keeps source truth separate from current parser capability. Current required positives are:

- Camelot `foo.pdf`: one published 7x7 table with content anchors and a separately audited residual paragraph sharing its final TextPage block;
- PyMuPDF `strict-yes-no.pdf`: exact published 5x3 simple table;
- Camelot `row_span_1.pdf`: one published 40x4 table with row-span topology;
- Camelot `column_span_2.pdf`: one published 11x7 table with column-span topology;
- Camelot `twotables_2.pdf`: two independently published 13x8 tables with content anchors.

For the small known-count pilot after M2.6:

```text
expected tables        5
predicted tables       5
false positives        0
missed tables          0
precision            1.0
recall               1.0
structural matches    6/6
```

For `foo.pdf`, the source-ownership audit also proves that residual native lines `81–83` / span orders `92–94` survive once with fragment-scoped provenance. Those exact line numbers are benchmark evidence only and are **not** encoded in production behavior.

These pilot metrics are not a claim about arbitrary PDFs.

## Diagnostics

M2 uses:

- `PDF_TABLE_STRUCTURE_EXTRACTED_M2` — high-confidence table structure was emitted;
- `PDF_TABLE_CANDIDATE_UNSUPPORTED_M2` — table-like evidence exists but topology or source ownership is not defensible;
- `PDF_TABLE_DETECTION_FAILED_M2` — table inspection failed safely and native text was retained;
- `PDF_TABLE_MERGED_DETECTION_FAILED_M2_4` — merged-topology retry failed safely;
- `PDF_TABLE_SEGMENTATION_FAILED_M2_5` — segmented multi-table inspection failed safely;
- `PDF_TABLE_SOURCE_PARTITION_FAILED_M2_6` — boundary-safe native-line ownership retry failed safely;
- `PDF_ALIGNED_LAYOUT_REMAINS_UNSTRUCTURED_M2` — additional aligned content outside accepted tables remains intentionally unstructured.

Existing M1 diagnostics remain valid for visibility, suspicious native mappings, image content, no-native-text pages, and unresolved aligned layouts.

## M1 invariants retained

Every emitted source unit still retains exact input-byte SHA-256, 1-based page identity, normalized displayed-page bbox, original point geometry, native order/provenance, and pinned backend/policy versions. Occluded text is excluded only with high-confidence paint-order evidence. Ambiguous reading order falls back to the native sequence.

## Explicit limitations after M2.6

M2.6 intentionally does **not** claim support for:

- arbitrary character, word, span, or native-line splitting across table boundaries;
- a table embedded in the middle of one native source block;
- outside-prefix followed by table-suffix ownership inside one source block;
- mixed inside/outside spans on one native line;
- partially crossing spans;
- arbitrary irregular or L-shaped merged cells;
- overlapping/non-rectangular table topology;
- continuation inference beyond adjacent pages, blank-page jumps, or merged
  cross-page source tables;
- semantic header inference;
- OCR / scanned-page recovery;
- image or vector-only text understanding;
- figure/caption pairing;
- header/footer/page-number classification;
- heading hierarchy;
- cross-page paragraph continuation.

OCR remains a separate optional later extension, not a prerequisite for the native PDF pipeline.

## Dependency

PyMuPDF remains the source observation backend. CI pins the supported release so native extraction and table-detection behavior cannot drift silently.
