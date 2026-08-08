# AGENTS.md — support_learning

This file contains persistent repository instructions for Codex and other coding agents.

## Repository and branch

- Repository: `Hoang-k68a3hus/support_learning`.
- Active source-understanding branch: `agent/build-boundary-scorer`.
- GitHub/current branch code is the source of truth. Read the actual files before proposing or making changes.
- Do not assume project state from old chat history, generated snippets, or stale documentation when code disagrees.
- Never push directly to `main` unless the user explicitly requests it.
- Do not commit or push unless the user asks. When asked to publish, keep changes on the current feature branch unless the task clearly requires a new branch.

## Current project objective

The current objective is to complete the **Universal Source Understanding system**. Do not expand the active implementation roadmap into a general RAG/chatbot stack unless the user explicitly changes this scope.

In scope:

- source adapters and atomic/source-near extraction;
- canonical `Element` representation and normalization;
- content profiling and region/subdocument understanding;
- structural signals and boundary decisions;
- LogicalUnit grouping and content-integrity preservation;
- hierarchy/context understanding without fabricated structure;
- structural and semantic relations;
- `CanonicalDocument` assembly and validation;
- optional semantic annotation generation and semantic quality diagnostics;
- end-to-end source-understanding orchestration, reproducibility, quality, and debugging;
- provenance/source identity needed to preserve exact source meaning.

Currently out of scope:

- vector databases or indexing infrastructure;
- embedding model integration;
- retrieval/fusion/reranking implementation;
- Evidence selection;
- grounded answer/chat generation;
- citation-generation workflows beyond preserving source provenance;
- personalization or recommendation systems.

Existing `RetrievalUnit` code may remain as a downstream projection/compatibility boundary, but do not make retrieval optimization the next milestone while the source-understanding system is incomplete.

## Architecture to preserve

Current information flow:

```text
ANY SOURCE
  -> Raw/source-near observations
  -> Element
  -> Content Profile
  -> Structure Signals
  -> Boundary Decisions
  -> LogicalUnit + ContextNode + SubDocument
  -> Structural Relations + Structure Quality
  -> CanonicalDocument
  -> optional Semantic Enrichment
  -> validated Understood CanonicalDocument
```

Downstream projections such as `RetrievalUnit` must remain rebuildable from the canonical representation and must not become the master source model.

Keep these information classes distinct:

1. SOURCE FACT — information actually present in the source.
2. INFERRED STRUCTURE — structure inferred from evidence.
3. SEMANTIC ENRICHMENT — optional semantic labels/relations added downstream of structural understanding.

Inference must never silently become a source fact.

The system must not assume documents are always `Chapter -> Section -> Paragraph`.
Valid structure modes include `UNKNOWN`, `FLAT`, `LOCAL`, `GROUPED`, `HIERARCHICAL`, and `MIXED`.

## Non-negotiable invariants

- Preserve information before interpreting it: `Preserve -> Structure -> Enrich`.
- Keep raw and normalized text separable. Normalization must not overwrite source text or silently change anchor meaning.
- `CanonicalDocument` represents exactly one source revision.
- Unknown/flat structure is a valid result; low confidence must not be repaired by inventing hierarchy.
- Tables, code, QA pairs, lists, formulas, dialogue, logs, figures, and other integrity-sensitive content must not be flattened or split merely for convenience.
- Provenance and exact source identity must remain traceable through every inferred object.
- Never invent page numbers, bounding boxes, character ranges, source references, or source facts.
- Derived layout locations must be marked `DERIVED` and must not overwrite original source location facts.
- Optional semantic enrichment must not be required for a valid structural `CanonicalDocument`.
- Semantic provider/model output must never claim `EXPLICIT` provenance unless that explicit fact was independently observed in the source layer.
- Inferred topics must remain semantic annotations; they must not be promoted into headings or explicit ContextNodes.
- Configuration that materially changes deterministic parsing/understanding output must be serialized in the stage result or `ProcessingManifest` so the result is reproducible.
- Every final `CanonicalDocument` must pass canonical graph validation after the last transformation stage.

## Current schema contracts

Before changing schemas, inspect the implementation and tests in the active branch. Preserve these contracts unless the user explicitly asks to redesign them:

- Schema models are immutable/frozen and reject unknown fields.
- JSON metadata must remain recursively immutable, JSON-safe, and finite.
- `CanonicalDocument.content_hash` identifies exact source content; `source_revision` is optional revision identity.
- `ProcessingManifest` records adapter/normalizer/structure/semantic versions and processing configuration needed for reproducibility.
- `DocumentStructure(mode=UNKNOWN)` carries no fake `source` or `confidence`; known modes require both.
- `ContentRegion` is a non-overlapping local profiling/routing boundary; references follow canonical element order and `MIXED` structure requires regions.
- `LogicalUnit` is structural/content-integrity oriented. Definition/example/exercise/topic and similar roles belong in semantic annotations rather than structural types.
- `ContextNode.parent_id` is authoritative for context hierarchy. Do not duplicate that hierarchy with redundant context `PARENT_OF` edges.
- `RelationLayer` separates structural from semantic relations; relation provenance (`EXPLICIT`, `INFERRED`, `DERIVED`) is a separate axis.
- Avoid redundant canonical inverse relations when one direction can be derived.
- Canonical page-relative bounding boxes use normalized `[0, 1]` coordinates with top-left origin.
- Character ranges use zero-based, start-inclusive/end-exclusive `[start, end)` offsets against the adapter source-text view before canonical normalization.
- Unmeasured confidence/quality must remain unknown (`None`), not silently default to perfect confidence.
- Semantic annotation generation must be provider-independent at the orchestration boundary and validate provider output before attaching it to the canonical graph.

## Source-understanding stage ownership

Keep responsibilities explicit:

```text
adapter / atomic extraction
    source observations only

profiling
    observed composition diagnostics, not document-type truth

structure signals
    evidence only

boundary
    adjacent boundary decisions only

grouping
    LogicalUnit/SubDocument construction, not semantic role assignment

hierarchy
    ContextNode interpretation, only from defensible structural evidence

relations
    auditable structural/semantic edges owned by their respective layer

assembly
    reconcile stage outputs and make CanonicalDocument validation the final gate

semantics
    optional inferred/derived meaning attached after structural parsing

pipeline
    orchestration, stage isolation, reproducibility manifest, and failure policy
```

Do not hide one stage's missing responsibility inside another stage just to make an end-to-end example pass.

## Semantic understanding rules

Semantic enrichment may include:

- topics and concepts;
- definitions, examples, warnings, notes, summaries;
- theorem/proof roles;
- exercises/questions/answers;
- procedures and key points;
- learning objectives;
- entities/keywords when a provider can support them reliably.

Use the narrowest defensible target. A local definition/example marker on one Element should not automatically label an entire multi-element LogicalUnit.

Provider output must be filtered/validated for:

- requested target identity;
- allowed annotation type;
- confidence policy;
- duplicate values;
- target-level limits;
- provenance class;
- deterministic provider/version identity.

Semantic failure defaults to preserving the valid structural document unless strict semantic execution is explicitly requested.

## Repository-local Codex skills

Codex discovers project skills from `.agents/skills/`.

Use `$rag-source-understanding` for source-understanding work, but apply only the portions relevant to the current project objective. Its downstream RAG guidance does not expand the current scope by itself.

`AGENTS.md` remains authoritative for repository scope, architecture, Git safety, and publishing rules.

If a generic or third-party skill conflicts with these source-understanding invariants, follow this file.

## Design priority

When several implementation choices are possible, prioritize:

1. correctness;
2. information preservation;
3. provenance and reproducibility;
4. maintainability;
5. testability and observability;
6. semantic/structural understanding quality;
7. performance;
8. cleverness.

Do not add an abstraction unless it improves correctness, preservation, provenance, reproducibility, quality, evaluation, or debugging.

## Python conventions

- Use explicit type annotations.
- Avoid mutable default arguments.
- Validate data at boundaries.
- Prefer enums for controlled vocabulary.
- Avoid import cycles; use `TYPE_CHECKING` when only typing requires a reverse reference.
- Do not swallow exceptions.
- Error messages must identify the invalid object/reference and enough context to debug it.
- Do not hard-code magic values when they belong in schema/configuration.
- Avoid over-engineering speculative future needs.

## Required workflow for code changes

For implementation work, follow:

```text
READ CURRENT CODE
-> ANALYZE INVARIANTS
-> DESIGN MINIMAL CHANGE
-> IMPLEMENT
-> TEST
-> REVIEW DIFF
-> REPORT
```

If fixing a bug:

```text
reproduce -> add/adjust regression test -> fix -> rerun regression suite
```

Always inspect the current branch and final diff before publishing. Never silently include unrelated changes.

## Validation expectations

Minimum checks when the relevant environment is available:

```bash
python -m unittest discover -s tests -v
python -m compileall -q source_understanding tests
```

When available, also run configured lint/type checks. Do not claim a tool passed if it was not installed or not executed.

Add accepted/rejected-state tests where relevant, especially for:

- data loss;
- dangling/invalid references;
- source revision/hash mismatch;
- invalid canonical order;
- overlapping regions/subdocuments;
- invalid context hierarchy/cycles;
- source-fact vs inference leakage;
- semantic target leakage;
- optional semantic failure fallback;
- stage version/count/configuration drift;
- fallback/unknown states;
- serialization and immutability.

## Review severity

Use these priorities in reviews:

- P0: correctness, architecture, provenance integrity, data loss, fabricated source facts/locations, stale source revision, inference promoted to source fact.
- P1: validation gaps, reproducibility gaps, hidden coupling, weak observability, integrity-sensitive content mishandling, missing edge cases.
- P2: optimization, convenience abstractions, advanced features outside the current completion path.

Pay special attention to wrong assumptions about document structure, silent fallback, hidden stage coupling, unreproducible configuration, and source information loss.

## Communication

- Be concise but explicit about important architectural decisions.
- For long tasks, surface important findings as they are discovered.
- Never claim tests, lint, type-checks, commits, pushes, remote verification, or CI succeeded unless actually verified.
