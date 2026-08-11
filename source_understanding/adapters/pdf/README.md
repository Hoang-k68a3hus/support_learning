# PDF Adapter — M1 Native Text Foundation

`source_understanding.adapters.pdf` is the born-digital/native-text PDF boundary.
It is deliberately separate from OCR, layout-model, table-recognition, and semantic
classification work.

## M1 pipeline

```text
exact PDF bytes
  -> validate/open
  -> standard/XMP metadata + page geometry
  -> PyMuPDF TextPage DICT (sort=False)
  -> native text blocks / lines / spans
  -> displayed page bbox normalization
  -> deterministic geometry-first reading order
  -> derived block reconstruction
  -> RawElement[]
  -> SourceAdapterRunner
  -> format-agnostic SourceUnderstandingPipeline
```

## Source / inference boundary

PDF does not usually expose paragraph or heading semantics as authoritative source
facts. M1 therefore emits reconstructed text blocks as `PARAGRAPH` hints with
`DERIVED` provenance. It does **not** emit `HEADING`, `TABLE`, `HEADER`, `FOOTER`,
or semantic roles from font size or position.

Every emitted block retains:

- exact input-byte SHA-256 through `SourceAdapterResult.content_hash`;
- 1-based page identity;
- canonical normalized `[0, 1]` bbox in displayed/rotated page coordinates;
- original PyMuPDF unrotated bbox in points;
- native block order and resolved reading order;
- line-break reconstruction offsets;
- span offsets, bboxes, font name/size, flags, color, alpha and origin when enabled;
- PyMuPDF / MuPDF versions and deterministic adapter policy in provenance/manifest.

## Reading order

M1 never assumes that PDF content-stream order is natural reading order, but it
also does not replace native order without evidence. The native sequence is retained
for audit and is the fail-closed fallback.

`geometric-columns-v2` only changes order when a defensible prose-column cohort is
found. Wide blocks may separate vertical layout bands only when they do not
materially overlap neighboring blocks. This prevents a long continuation line,
formula fragment, or BNF production from being promoted into a false page
separator merely because its bbox spans most of the page width.

Repeated row-aligned geometry is handled even more conservatively. Several
horizontally separated blocks repeatedly sharing the same vertical bands often
indicate a table, form, equation array, or diagram rather than independent prose
columns. M1 does not infer those structures. It preserves native block order and
emits `PDF_ALIGNED_LAYOUT_NOT_STRUCTURED_M1` so downstream code knows structural
completeness is unresolved instead of receiving a false column-major flattening.

If neither aligned-layout evidence nor defensible columns are present, native order
is preserved. This distinction matters because small baseline differences can
otherwise move an equation number, production label, table cell, or continuation
fragment behind the content it labels.

## Native text quality diagnostics

Native text is preserved exactly as returned by the PDF backend. M1 does not clean
or replace suspicious glyph mappings. If extraction contains C0/C1 control code
points or the Unicode replacement character, the adapter emits
`PDF_NATIVE_TEXT_MAPPING_SUSPECT` with structural-completeness impact and records the
affected code points. This commonly indicates an embedded font without a reliable
Unicode mapping. OCR remains a later milestone rather than a hidden repair path.

## Explicit M1 limitations

The following are intentionally **not** silently handled:

- OCR / scanned pages;
- image understanding;
- vector-only text;
- table structure recognition;
- figure/caption pairing;
- header/footer/page-number classification;
- heading hierarchy;
- cross-page paragraph continuation;
- formulas beyond whatever native Unicode text the PDF already exposes.

Pages without native text and pages containing image blocks produce structural-loss
diagnostics. Suspicious native font mappings and strongly aligned/grid-like native
text layouts are also surfaced instead of being silently normalized or flattened.
This keeps M1 honest while later PDF milestones add OCR, tables, and richer layout
understanding without changing the canonical source boundary.

## Dependency

M1 uses PyMuPDF as the source observation backend. CI pins the supported release so
extraction behavior does not drift silently.
