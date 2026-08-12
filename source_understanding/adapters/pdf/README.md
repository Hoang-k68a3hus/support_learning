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
  -> M2 conservative table detection
       -> accepted: source-span-bound TABLE / TABLE_ROW / TABLE_CELL
       -> rejected/ambiguous: preserve M1 native blocks + diagnostic
  -> deterministic fail-closed reading order for non-table content
  -> RawElement[]
  -> SourceAdapterRunner
  -> format-agnostic SourceUnderstandingPipeline
```

## Source / inference boundary

PDF normally does not expose paragraph, heading, or table semantics as authoritative
tags. Visible text blocks therefore remain `PARAGRAPH` hints with `DERIVED`
provenance. M2 table elements are also explicitly `DERIVED`: they represent a
high-confidence structural projection from PDF vector geometry plus exact native
text-span ownership, not an explicit source tag.

The adapter never converts weak layout evidence into a source fact. Unsupported or
ambiguous candidates remain their original M1 text blocks.

## M2 table structure v1

`pymupdf-lines-strict-v1` is deliberately precision-first. PyMuPDF proposes
line-bordered table candidates from vector geometry using `lines_strict`. The adapter
then accepts a candidate only when all of these invariants hold:

- at least 2 rows and 2 columns;
- at least 6 total cells (small 2x2 figure/grid layouts are intentionally rejected);
- simple rectangular topology with no missing/merged/spanning cells;
- stable column boundaries across rows;
- enough populated rows, columns, and cells;
- every native text span inside the candidate maps to exactly one cell;
- a consumed TextPage block cannot also contain non-blank text outside the table;
- consumed visible source blocks must form one contiguous source interval;
- two accepted tables cannot claim the same source block.

A verified table replaces the consumed paragraph blocks rather than duplicating them:

```text
TABLE
TABLE_ROW
TABLE_CELL ...
TABLE_ROW
TABLE_CELL ...
```

All table elements share the format-agnostic `integrity_group_id`, allowing the
existing integrity consolidator to build one `TABLE_BLOCK` downstream without PDF-
specific logic.

### Cell text and provenance

Cell text is rebuilt from the exact TextPage spans owned by that cell; it is not
trusted from a second semantic transcription. `source-spans-v1` preserves source
block, line, and span native orders plus span text, native/displayed bboxes, fonts,
flags, colors, alpha, and origins in cell audit metadata. This keeps the table
projection traceable back to the original PDF observations.

## Diagnostics

M2 adds:

- `PDF_TABLE_STRUCTURE_EXTRACTED_M2` — a high-confidence table was structured;
- `PDF_TABLE_CANDIDATE_UNSUPPORTED_M2` — vector geometry proposed a candidate but
  topology/source ownership was too weak or unsupported;
- `PDF_TABLE_DETECTION_FAILED_M2` — table inspection failed safely and M1 text was
  retained;
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

## Explicit limitations after this increment

M2 v1 intentionally does **not** claim support for:

- borderless/text-only tables;
- merged cells, row spans, or column spans;
- irregular/non-rectangular tables;
- cross-page table continuation;
- semantic header inference;
- OCR / scanned pages;
- image or vector-only text understanding;
- figure/caption pairing;
- header/footer/page-number classification;
- heading hierarchy;
- cross-page paragraph continuation.

Those cases must stay visible as ordinary source content or structural-loss
diagnostics until a later milestone can prove them safely.

## Dependency

PyMuPDF remains the source observation backend. CI pins the supported release so
native extraction and table-detection behavior cannot drift silently.
