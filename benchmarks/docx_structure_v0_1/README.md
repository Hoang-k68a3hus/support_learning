# DOCX Structure Gold Benchmark V0.1 — Pilot

This benchmark is a **deterministic generated pilot**, not evidence of real-world production accuracy.
Its purpose is to make structural evaluation reproducible before collecting a larger human-reviewed DOCX corpus.

## Scope

The pilot measures only document/source structure already owned by `source_understanding`:

- source element preservation and `ElementType`;
- native heading levels and hierarchy parent assignment;
- structural/content-integrity `LogicalUnit` grouping;
- exact table/list/QA integrity blocks;
- `ContentRegion` boundaries and routing categories;
- selected grounded structural relations;
- exact visible source-text preservation;
- expected versus unexpected adapter structural diagnostics;
- final document structure mode and `structural_ready` status.

It deliberately does **not** evaluate topics, entities, semantic relations, retrieval quality, embeddings, or answer generation.

## Why generated first?

V0.1 is a schema/evaluator pilot. Generated OOXML gives us exact source truth, deterministic hashes, known edge cases, and no licensing ambiguity. It lets us test whether the evaluation framework itself is correct before paying the annotation cost for real documents.

Generated data must not be reported as a real-world benchmark. The next benchmark milestone should add human-reviewed real DOCX files while preserving the same gold schema and evaluator.

## Source generation versus gold adjudication

The benchmark intentionally separates two steps:

1. `generate_pilot.py` deterministically creates the DOCX **source bytes** and an initial source-derived annotation draft.
2. `adjudicated_pilot.py` applies reviewed **gold decisions** without modifying those source bytes or hashes.

This mirrors the later human-annotation workflow: source creation/collection and gold interpretation are different responsibilities. Gold corrections are not allowed to rewrite a source file simply to improve the parser score.

V0.1 adjudication currently records one explicit correction in case 03: referenced footer/header stories are preceded by deliberate `source_zone_boundary` elements, and boilerplate/separator material follows the core bridge policy by attaching to the adjacent material region rather than creating a standalone routing region.

## Pilot cases

| Case | Split | Structural focus |
| --- | --- | --- |
| `docx-pilot-01` | dev | inherited heading styles, heading hierarchy, numbered list integrity |
| `docx-pilot-02` | dev | outer/nested tables, content-control wrapper, native `PART_OF` |
| `docx-pilot-03` | dev | footnote/endnote, paragraph section break, source-story boundaries, header/footer |
| `docx-pilot-04` | dev | narrative + lexical Q/A, QA pairing, grouping-aware mixed-region gap |
| `docx-pilot-05` | test | tracked revisions, content control, valid comment id 0, opaque `altChunk` |

Case 04 intentionally contains a known architectural challenge: Q/A roles are inferred structurally without mutating source `ElementType`, while the current region segmenter routes primarily from element categories. Gold records the intended QA region so the benchmark can expose this gap instead of hiding it.

## Reproducibility

The generator uses:

- generator id `docx-structure-pilot-generator:0.1`;
- seed `20260809`;
- fixed ZIP timestamps;
- `ZIP_STORED` entries to avoid zlib-version-dependent byte hashes;
- deterministic entry ordering;
- synthetic text released as CC0-1.0 by the project.

Run commands from the repository root so imports resolve exactly as they do in CI.

Generate the materialized source + **adjudicated** gold bundle:

```bash
python -m benchmarks.docx_structure_v0_1.adjudicated_pilot \
  --output benchmarks/docx_structure_v0_1/materialized
```

Run the baseline against the current parser:

```bash
python -m benchmarks.docx_structure_v0_1.run_benchmark \
  --report /tmp/docx-structure-v0.1-report.json
```

The generator + adjudication layer are the V0.1 pilot source of truth. `materialize(...)` writes reviewable gold JSON plus reproducible `.docx` files into an output directory. The generated bundle is then reloaded through the strict hash/path validator before scoring.

## Gold stability

Gold IDs such as `e01` or `ctx1` belong only to the benchmark. They must never reuse production `Element.id` values.

Gold-to-prediction alignment uses, in descending preference:

1. explicit native source anchors (`footnote:1`, `comment:0`, etc.);
2. exact raw source text + OPC part + source zone;
3. normalized text + OPC part + source zone;
4. source-kind occurrence for textless structural elements.

There is intentionally no broad fuzzy text matching. An ambiguous match is an evaluation error, not something the evaluator silently guesses.

## Relation evaluation scope

Structural relation labels may be reused across endpoint namespaces. For example, `PART_OF` can represent both Element→LogicalUnit membership and LogicalUnit→LogicalUnit native nesting. V0.1 evaluates only endpoint namespaces demonstrated by positive gold relations for the selected relation types. This prevents correct out-of-scope structural edges from becoming false positives.

A future benchmark that needs **negative-only** relation scopes must make those scopes explicit in a later gold-schema version rather than treating unannotated namespaces as negative.

## Metric interpretation

The report exposes both pooled counts and per-document macro summaries. A complete miss on a document with gold positives has `F1=0`; it is not dropped from the macro average merely because precision has an empty denominator.

A green unit-test suite means the framework obeys its coded invariants. Benchmark metrics mean the parser matches this gold set. Neither one alone demonstrates general real-world document-understanding accuracy.
