# Real PDF table-continuation benchmark M2.7.1

This benchmark evaluates adjacent-page table continuation against a small,
independently adjudicated corpus rooted outside the repository. PDF bytes are
not copied into Git. The runner verifies the pinned SHA-256 values when a
source hash is available and records the actual hash in its report.

The gold cases were reviewed from rendered pages and source layout without
using production `CONTINUES` relations. The corpus contains positive and hard
negative adjacent-page pairs, including a six-page vocabulary-table chain that
contains multiple three-page subchains.

The benchmark keeps three prediction namespaces separate:

- **Core gold** is the frozen independent 19-case sample used for precision,
  recall, F1, and chain regression.
- **Coverage adjudications** are independently reviewed production-emitted
  pairs outside core gold. They measure emitted-edge safety only; they must not
  be used to calculate recall or F1.
- **Unknown predictions** are emitted pairs that are neither core gold nor in
  the coverage ledger. They fail closed and block promotion.

The coverage ledger starts empty in this task. It is intentionally populated
only after independent review of rendered source pages in a later task; the
absence of a production edge is not itself a negative adjudication.

Run against the user corpus:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m benchmarks.pdf_table_continuation_real_v0_1.run_benchmark `
  --root D:\book `
  --report $env:TEMP\pdf-table-continuation-real-v0.1.json `
  --enforce-promotion-gate
```

Promotion requires zero false continuation links, zero false negatives on the
adjudicated positives, and every required three-page chain edge. A report may
be run without the promotion flag to document current misses while the gold
remains frozen. No detector threshold may be tuned from the report before a
new gold review.
