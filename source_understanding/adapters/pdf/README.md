# PDF Adapter — M2 Structural Content

`source_understanding.adapters.pdf` is the born-digital/native-text PDF boundary.
M1 preserves visible native text, geometry, reading order, and provenance. M2 adds
structural content only when the PDF provides enough auditable evidence to do so.
OCR, image understanding, and semantic classification remain separate concerns.

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
       -> rejected/ambiguous: preserve M1 native blocks + diagnostic
  -> deterministic fail-closed reading order for non-table content
  -> RawElement[]
  -> SourceAdapterRunner
  -> format-agnostic SourceUnderstandingPipeline
```

OCR is **not** part of this pipeline. It is deferred as an optional later extension.

## Source / inference boundary

PDF normally does not expose paragraph, heading, or table semantics as authoritative
tags. Visible text blocks therefore remain `PARAGRAPH` hints with `DERIVED`
provenance. M2 table elements are also explicitly `DERIVED`: they represent a
high-confidence structural projection from PDF geometry/text alignment plus exact
native text-span ownership, not an explicit source tag.

The adapter never converts weak layout evidence into a source fact. Unsupported or
ambiguous candidates remain their original M1 text blocks.

## Simple ruled tables

The `lines_strict` path is precision-first. It accepts a candidate only when there is
a stable simple rectangular grid, enough populated content, unique native-span cell
ownership, no source block crossing the candidate boundary, contiguous consumed
source blocks, and no overlapping table ownership.

A verified table replaces the consumed paragraph blocks rather than duplicating them:

```text
TABLE
TABLE_ROW
TABLE_CELL ...
TABLE_ROW
TABLE_CELL ...
```

All table elements share the format-agnostic `integrity_group_id`, allowing the
existing integrity consolidator to build one `TABLE_BLOCK` downstream without
PDF-specific grouping logic.

## M2.3 borderless native-text fallback

When the page does not contain strong rectilinear vector evidence, M2.3 may infer a
borderless table from repeated native text alignment. This fallback requires repeated
3+ row / 3+ column geometry, stable column lanes, adequate whitespace, exact source
ownership, and contiguous source blocks. Equation/form operator lanes such as `=` or
`:`, dense parallel prose, and ambiguous layouts fail closed.

The adapter deliberately does **not** call a whole-page `find_tables(strategy="text")`
and trust the result, because prose pages can otherwise become false mega-grids.

## M2.4 rectangular merged topology

M2.4 adds `lines_strict_merged` for ruled tables containing rectangular row spans or
column spans. It only retries line-table candidates that the simple path rejected as
complex/merged.

A PyMuPDF `None` cell slot is never treated as an ordinary empty cell. It is accepted
only when one rectangular anchor cell can be proven to cover that logical slot.
The detector reconstructs global row/column boundaries and requires all of these
invariants:

- exact logical row/column boundary counts;
- each non-`None` cell is the top-left anchor of its logical rectangle;
- every logical slot is covered by exactly one anchor cell;
- no overlap and no unexplained hole;
- a real span exists (`row_span > 1` or `column_span > 1`);
- every relevant native text span maps to exactly one anchor cell;
- consumed TextPage blocks cannot contain non-blank text outside the table;
- consumed blocks remain contiguous and cannot overlap another accepted table.

Accepted merged cells are emitted **once** at their anchor location. Covered logical
slots do not receive duplicate text. M2.4 records:

```text
TABLE:
  pdf_table_topology = rectangular_with_spans
  has_merged_cells
  pdf_merged_cell_count

TABLE_CELL:
  row_span
  column_span
  logical_slots[]
```

The merged topology version is `rectangular-spans-v1`. The structure is still
`DERIVED`; the exact native text/span provenance remains attached to the anchor cell.

## Cell text and provenance

Cell text is rebuilt from the exact TextPage spans owned by that cell; it is not
trusted from a second semantic transcription. `source-spans-v1` preserves source
block, line, and span native orders plus span text, native/displayed bboxes, fonts,
flags, colors, alpha, and origins in cell audit metadata. This keeps every table
projection traceable back to the original PDF observations.

## Real-PDF measurement

The pinned real-PDF benchmark keeps source truth separate from current parser
capability. M2.4 adds topology-aware release contracts without inventing exact merge
coordinates that the upstream fixtures do not establish.

Current real required positives include:

- PyMuPDF `strict-yes-no.pdf`: exact published 5x3 simple table;
- Camelot `row_span_1.pdf`: one published 40x4 table with row-span topology;
- Camelot `column_span_2.pdf`: one published 11x7 table with column-span topology.

Remaining real misses continue to be classified from production diagnostics only
after independent gold establishes that a source table exists.

## Diagnostics

M2 uses:

- `PDF_TABLE_STRUCTURE_EXTRACTED_M2` — high-confidence table structure was emitted;
- `PDF_TABLE_CANDIDATE_UNSUPPORTED_M2` — table-like evidence exists but topology or
  source ownership is not defensible;
- `PDF_TABLE_DETECTION_FAILED_M2` — table inspection failed safely and M1 text was
  retained;
- `PDF_TABLE_MERGED_DETECTION_FAILED_M2_4` — merged-topology retry failed safely;
- `PDF_ALIGNED_LAYOUT_REMAINS_UNSTRUCTURED_M2` — additional aligned content outside
  accepted tables remains intentionally unstructured.

Existing M1 diagnostics remain valid for visibility, suspicious native mappings,
image content, no-native-text pages, and unresolved aligned layouts.

## M1 invariants retained

Every emitted source unit still retains exact input-byte SHA-256, 1-based page
identity, normalized displayed-page bbox, original unrotated point geometry, native
order/provenance, and pinned backend/policy versions. Occluded text is excluded only
with high-confidence paint-order evidence. Ambiguous reading order falls back to the
native sequence.

## Explicit limitations after M2.4

M2.4 intentionally does **not** claim support for:

- arbitrary irregular or L-shaped merged cells;
- overlapping/non-rectangular table topology;
- cross-page table continuation;
- semantic header inference;
- OCR / scanned-page recovery;
- image or vector-only text understanding;
- figure/caption pairing;
- header/footer/page-number classification;
- heading hierarchy;
- cross-page paragraph continuation.

OCR remains a separate optional later extension, not a prerequisite for the native PDF
pipeline.

## Dependency

PyMuPDF remains the source observation backend. CI pins the supported release so
native extraction and table-detection behavior cannot drift silently.
