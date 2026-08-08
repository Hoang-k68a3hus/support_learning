---
name: rag-source-understanding
description: Use for designing, reviewing, implementing, debugging, or evaluating source-understanding and RAG code in support_learning, including ingestion, canonical representation, structure, retrieval units, retrieval/reranking, evidence, grounding, provenance, and citations.
---

# RAG & Source Understanding Engineering

Use this skill for any task that can change the quality or correctness of the path from source ingestion to grounded answers.

`AGENTS.md` is authoritative. This skill adds a RAG-specific workflow and checklists; it does not override repository scope, Git rules, or branch constraints.

## Core model

Reason about the system as separate stages:

```text
ANY SOURCE
  -> Element
  -> LogicalUnit
  -> RetrievalUnit
  -> Retrieval
  -> Reranking
  -> Evidence
  -> Grounded Answer
  -> Citation

LogicalUnit
  -> Inferred Structure
  -> optional Semantic Enrichment
```

Keep three information classes distinct at all times:

```text
SOURCE FACT
INFERRED STRUCTURE
SEMANTIC ENRICHMENT
```

Never promote inference or model output into source fact without source evidence.

## First action: classify the task

Before editing code, identify the primary layer being changed:

1. source adapter / extraction;
2. canonical representation / normalization;
3. structure / grouping / relations;
4. RetrievalUnit projection / chunking;
5. retrieval / filtering / fusion;
6. reranking;
7. Evidence construction;
8. grounded generation / citation;
9. evaluation / debugging.

Then inspect the real implementation, tests, and nearest relevant design document for that layer. Do not design from memory.

For the current schema branch, respect its foundation-only scope unless the user explicitly changes scope.

## RAG priority order

When deciding what to improve, use this order:

```text
parsing correctness
-> information preservation
-> RetrievalUnit quality
-> retrieval recall
-> reranking
-> Evidence construction
-> grounded generation
-> citation correctness
```

Do not use prompt engineering to conceal poor extraction, broken provenance, weak RetrievalUnits, or missing retrieval recall.

## Source-understanding rules

### Source facts

Preserve source-near information before interpretation:

- raw text and normalized text remain separable;
- reading order is explicit;
- source locations retain defined coordinate/offset semantics;
- source revision/content hash remains traceable;
- tables, code, QA pairs, lists, dialogue, formulas, figures, captions, and other integrity-sensitive content are not flattened merely for convenience.

If location is unavailable, keep it unknown. Never invent page numbers, bounding boxes, offsets, or source anchors.

### Structure

Do not assume global hierarchy.

Treat `UNKNOWN`, `FLAT`, `LOCAL`, `GROUPED`, `HIERARCHICAL`, and `MIXED` as legitimate states.

Use this evidence priority:

```text
explicit source structure
> content-type integrity
> strong local pattern
> semantic boundary
> token target
```

A token target is a retrieval optimization, not a source-structure fact.

Keep source hierarchy separate from retrieval hierarchy. Parent/child retrieval chunks do not prove a source hierarchy.

### Semantic enrichment

Semantic topics, entities, roles, definitions, examples, prerequisites, summaries, and similar annotations are optional enrichment.

Failure of semantic enrichment must not make base RAG unusable.

## RetrievalUnit rules

A RetrievalUnit is a downstream projection, never the master source representation.

It must be rebuildable from `CanonicalDocument` without reparsing the original source.

Before indexing or trusting a RetrievalUnit:

- validate it against the exact canonical document revision;
- ensure every included element is covered by provenance/source anchors;
- ensure references are not dangling;
- ensure source hash/revision is current;
- ensure display/retrieval views do not destroy the canonical representation.

Never split a QA pair, table row/header dependency, code block, formula context, or other logical integrity unit solely to satisfy chunk size.

Do not hard-code a universal chunk size, overlap, `top_k`, or similarity threshold as an architectural truth. Treat these as evaluated retrieval policies.

## Retrieval and reranking rules

When retrieval quality is poor, inspect the candidate path rather than guessing.

Check, in order:

1. query/scoping/filter inputs;
2. eligible source/subdocument set;
3. RetrievalUnit corpus and text views;
4. sparse candidates;
5. dense candidates;
6. fusion result;
7. reranker input/output;
8. final Evidence selection.

If the user selected sources, apply source scope before retrieval rather than retrieving globally and filtering afterward.

Prefer hybrid retrieval when evaluation supports it; do not require hybrid retrieval by dogma.

Reranking cannot recover relevant evidence that candidate retrieval never recalled.

## Evidence and citation rules

Generation receives curated `Evidence`, not an unexamined dump of raw retrieval results.

Evidence building should consider:

- duplicate/near-duplicate units;
- overlapping or adjacent units;
- token budget;
- source diversity when relevant;
- evidence coverage;
- source anchors and citation resolvability.

Citation is a provenance operation, not free-form LLM generation.

Primary citation path:

```text
answer claim
-> Evidence
-> RetrievalUnit
-> LogicalUnit / Element
-> SourceAnchor
-> original source revision
```

Post-hoc fuzzy citation matching may be a fallback or verification mechanism, not the primary provenance model.

## Debugging workflow

For bugs, failed tests, unexpected metrics, or quality regressions:

```text
REPRODUCE
-> LOCALIZE THE FAILING STAGE
-> COLLECT EVIDENCE
-> FORM ONE HYPOTHESIS
-> ADD/ADJUST A REGRESSION TEST
-> MAKE THE MINIMAL FIX
-> RERUN LOCAL + REGRESSION CHECKS
-> REVIEW THE DIFF
```

Do not stack speculative fixes.

For multi-stage RAG failures, produce a diagnostic trace that makes the stage boundary visible. The reference checklist in `references/evaluation-and-debugging.md` contains suggested fields.

If three materially different fixes fail, reconsider the architecture or the diagnosed stage before trying another patch.

If the Superpowers plugin is installed, use its `systematic-debugging`, `test-driven-development`, and `verification-before-completion` skills as complementary workflows. Project invariants in `AGENTS.md` and this skill take precedence over generic advice.

## Evaluation: measure the layer you changed

Do not report a single end-to-end score as proof that every layer is healthy.

Choose metrics that isolate the changed stage.

### Parsing / canonicalization

Measure or test:

- source text preservation;
- reading-order correctness;
- element/reference validity;
- location/provenance coverage;
- structure source vs inference separation;
- unsupported-content warnings rather than silent loss.

### RetrievalUnit construction

Measure or test:

- reference/provenance validity;
- integrity-unit preservation;
- rebuildability from canonical data;
- token/size distribution as diagnostics, not success criteria;
- duplicate/overlap behavior.

### Retrieval

Prefer dataset-appropriate metrics such as:

- recall@k;
- hit rate;
- MRR;
- nDCG;
- precision@k when relevant;
- candidate count/latency.

Do not invent universal thresholds. Compare against an explicit baseline and task objective.

### Reranking

Measure:

- delta from candidate retrieval to reranked order;
- recall preservation;
- ranking quality;
- latency/cost.

### Evidence / generation / citation

Measure or test:

- answer support / faithfulness;
- evidence coverage;
- unsupported-claim rate;
- citation correctness and resolvability;
- source/revision correctness;
- refusal/unknown behavior when evidence is insufficient.

See `references/evaluation-and-debugging.md` for a compact evaluation matrix.

## Design questions before implementation

For any meaningful RAG change, answer these internally before coding:

1. Which stage owns this responsibility?
2. What information could be lost?
3. Does this convert inference into source fact?
4. Can downstream objects still trace back to the exact source revision?
5. What is the fallback when confidence or optional enrichment is unavailable?
6. What test demonstrates the invariant?
7. What metric would prove improvement at this layer?
8. Is this abstraction required now, or speculative?

If the answer to stage ownership is unclear, do not add cross-layer coupling until it is resolved.

## Review checklist

Classify findings:

### P0

- source data loss;
- fabricated/invalid citation or location;
- stale source revision accepted;
- broken references/provenance;
- inference stored as source fact;
- retrieval projection mutates/replaces canonical source;
- architecture makes base RAG depend on optional enrichment;
- severe security/privacy boundary failure.

### P1

- missing validation or fallback;
- hidden coupling;
- import cycles;
- weak observability/diagnostics;
- integrity-sensitive content can be split incorrectly;
- untested edge cases;
- policy constants presented as universal truths.

### P2

- performance tuning;
- convenience abstractions;
- advanced retrieval features;
- non-critical cleanup.

## Completion gate

Before saying a RAG/source-understanding change is complete:

- inspect final `git diff`;
- run the relevant tests;
- run the broader regression suite when feasible;
- verify no unrelated files changed;
- verify provenance/citation invariants;
- verify the exact layer-specific metric or diagnostic when the change is quality-related;
- state checks that were not available or not run;
- do not claim remote/CI/push success until independently verified.

## Useful invocation examples

```text
$rag-source-understanding review the current source_understanding schemas for P0/P1/P2 issues
```

```text
$rag-source-understanding debug why retrieval recall dropped after changing RetrievalUnit construction
```

```text
$rag-source-understanding design the next ingestion stage without losing source provenance
```

```text
$rag-source-understanding evaluate whether this chunking policy preserves QA/table/code integrity
```
