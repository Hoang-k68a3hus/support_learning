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
  -> paint-order visibility gate
  -> displayed page bbox normalization
  -> deterministic fail-closed reading order
  -> derived block reconstruction
  -> RawElement[]
  -> SourceAdapterRunner
  -> format-agnostic SourceUnderstandingPipeline
```

## Source / inference boundary

PDF does not usually expose paragraph or heading semantics as authoritative source
facts. M1 therefore emits reconstructed visible text blocks as `PARAGRAPH` hints with
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

## Paint-order visibility

A PDF text object can exist in the content stream while being invisible because a later
drawing operation paints over it. TextPage extraction alone is therefore not sufficient
evidence that extracted text is visible document content.

M1 uses `get_texttrace()` sequence numbers together with later opaque vector fills. It
excludes a block only when the evidence is high confidence: the text can be associated
with paint sequence entries, a later fill is effectively opaque and rectangle-like, and that
fill covers almost the entire text-block bbox. Ambiguous visibility always preserves the
native text.

High-confidence exclusions are reported as `PDF_OCCLUDED_TEXT_EXCLUDED_M1` and
retained in page audit metadata, but they are not emitted as retrieval text.

## Reading order

M1 never assumes that PDF content-stream order is natural reading order, but it also does
not replace native order without strong evidence. The native sequence remains the
fail-closed fallback.

`geometric-columns-v3` only changes order when a defensible prose-column cohort exists.
Candidate columns must contain repeated blocks, coexist vertically, be separated spatially,
and have reasonably balanced widths. Narrow equation-number lanes and asymmetric math
fragments therefore do not count as prose columns.

Wide blocks may separate vertical layout bands only when the remaining blocks independently
establish a defensible column cohort. A long single-column paragraph or formula cannot
become a false separator merely because it spans most of the page width.

Repeated row-aligned geometry remains conservative: M1 preserves native order and emits
`PDF_ALIGNED_LAYOUT_NOT_STRUCTURED_M1` rather than flattening probable tables, forms,
equation arrays, or diagrams column-major.

## Native text quality diagnostics

Native text is preserved exactly as returned by the PDF backend. M1 does not clean or
replace suspicious glyph mappings. If extraction contains C0/C1 control code points or
the Unicode replacement character, the adapter emits `PDF_NATIVE_TEXT_MAPPING_SUSPECT`.
OCR remains a later milestone rather than a hidden repair path.

## Explicit M1 limitations

The following are intentionally **not** silently handled:

- OCR / scanned pages;
- image understanding;
- vector-only text;
- arbitrary-path or image-based occlusion where visibility cannot be established safely;
- table structure recognition;
- figure/caption pairing;
- header/footer/page-number classification;
- heading hierarchy;
- cross-page paragraph continuation;
- formulas beyond whatever native Unicode text the PDF already exposes.

Pages without visible native text and pages containing image blocks produce explicit
structural-loss diagnostics. Suspicious native font mappings and strongly aligned/grid-like
native text layouts are surfaced instead of silently normalized or flattened.

## Dependency

M1 uses PyMuPDF as the source observation backend. CI pins the supported release so
extraction behavior does not drift silently.
