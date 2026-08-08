# AGENTS.md — support_learning

This file contains persistent repository instructions for Codex and other coding agents.

## Repository and branch

- Repository: `Hoang-k68a3hus/support_learning`.
- The current schema feature branch is `agent/build-source-understanding-schemas`.
- GitHub/current branch code is the source of truth. Read the actual files before proposing or making changes.
- Do not assume project state from old chat history, generated snippets, or stale documentation when code disagrees.
- Never push directly to `main` unless the user explicitly requests it.
- Do not commit or push unless the user asks. When asked to publish, keep changes on the current feature branch unless the task clearly requires a new branch.

## Current branch scope

This branch is intentionally foundation-only:

- `source_understanding/schemas/`
- package exports
- schema regression tests
- repository instructions/documentation that directly support this foundation

Do not add DOCX/PDF adapters, atomic extractors, profilers, grouping builders, retrieval builders, embeddings, rerankers, or semantic-enrichment pipelines on this branch unless the user explicitly changes the scope.

## Architecture to preserve

Core information flow:

```text
ANY SOURCE
  -> Element
  -> LogicalUnit
  -> RetrievalUnit
  -> Evidence
  -> Grounded Answer
  -> Citation

LogicalUnit
  -> Inferred Structure
  -> optional Semantic Enrichment
```

Keep these information classes distinct:

1. SOURCE FACT — information actually present in the source.
2. INFERRED STRUCTURE — structure inferred from evidence.
3. SEMANTIC ENRICHMENT — optional semantic labels/relations added downstream.

Inference must never silently become a source fact.

The system must not assume documents are always `Chapter -> Section -> Paragraph`.
Valid structure modes include `UNKNOWN`, `FLAT`, `LOCAL`, `GROUPED`, `HIERARCHICAL`, and `MIXED`.

## Non-negotiable invariants

- Preserve information before interpreting it: `Preserve -> Structure -> Enrich -> Retrieve`.
- Keep raw and normalized text separable. Normalization must not overwrite source text or silently change anchor meaning.
- `CanonicalDocument` represents exactly one source revision.
- `RetrievalUnit` is a downstream projection and must remain outside `CanonicalDocument`; it must be rebuildable without reparsing the original source.
- Provenance must remain traceable:
  `RetrievalUnit -> LogicalUnit -> Element -> SourceAnchor -> Original Source`.
- LLM output must never invent page numbers, bounding boxes, source references, or citations.
- Optional semantic enrichment must not be required for base RAG to function.
- Do not break QA pairs, tables, code blocks, or other content-integrity units merely to hit a token target.

## Current schema contracts

Before changing schemas, inspect the implementation and tests in this branch. In particular, preserve these contracts unless the user explicitly asks to redesign them:

- Schema models are immutable/frozen and reject unknown fields.
- JSON metadata must remain recursively immutable, JSON-safe, and finite.
- `CanonicalDocument.content_hash` identifies exact source content; `source_revision` is optional revision identity.
- `ProcessingManifest` records adapter/normalizer/structure/semantic versions and processing configuration needed for reproducibility.
- `DocumentStructure(mode=UNKNOWN)` carries no fake `source` or `confidence`; known modes require both.
- `ContentRegion` is the local profiling/routing boundary. Regions are non-overlapping, references follow canonical element order, and `MIXED` structure requires regions.
- `LogicalUnit` is structural/content-integrity oriented. Semantic roles such as definition/example/exercise belong in semantic annotations rather than being smuggled into structural types.
- `ContextNode.parent_id` is authoritative for context hierarchy. Do not duplicate that hierarchy with redundant context `PARENT_OF` edges.
- `RelationLayer` separates structural from semantic relations; relation provenance (`EXPLICIT`, `INFERRED`, `DERIVED`) is a separate axis.
- Avoid storing redundant canonical inverse relations when one direction can be derived.
- Canonical page-relative bounding boxes use normalized `[0, 1]` coordinates with top-left origin.
- Character ranges use zero-based, start-inclusive/end-exclusive `[start, end)` offsets against the adapter source-text view before canonical normalization.
- Derived layout locations (for example DOCX rendered to PDF) must be marked `DERIVED` and must not overwrite original source anchors.
- `RetrievalUnit` and `SourceAnchor` carry content hash/revision identity so stale citations cannot silently point at changed content.
- A retrieval unit must pass `validate_against_document()` before it is considered safe for indexing/use.
- Unmeasured confidence/quality must remain unknown (`None`), not silently default to perfect confidence.

## Design priority

When several implementation choices are possible, prioritize:

1. correctness
2. information preservation
3. maintainability
4. testability
5. retrieval/evaluation/debuggability
6. performance
7. cleverness

Do not add an abstraction unless it improves at least correctness, information preservation, retrieval quality, evaluation, or debugging.

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

Always inspect `git status` and the diff before editing and before any commit. Never stage unrelated user changes.

## Validation commands

From the repository root, the minimum checks for schema changes are:

```bash
python -m unittest discover -s tests -v
python -m compileall -q source_understanding tests
```

When available, also run configured lint/type checks. Do not claim a tool passed if it was not installed or not executed.

For a schema change, add tests for both accepted and rejected states, especially:

- data loss
- dangling/invalid references
- source revision/hash mismatch
- invalid canonical order
- overlapping regions/subdocuments
- invalid context hierarchy/cycles
- provenance/citation loss
- source-fact vs inference leakage
- fallback/unknown states
- serialization and immutability

## Review severity

Use these priorities in reviews:

- P0: correctness, architecture, provenance/citation integrity, data loss, security.
- P1: validation gaps, maintainability, observability, missing edge cases.
- P2: optimization, convenience, advanced features.

Pay special attention to hidden coupling, import cycles, wrong assumptions about document structure, missing fallback paths, and source/citation information loss.

## Communication

- Be concise but explicit about important architectural decisions.
- For long tasks, surface important findings as they are discovered.
- Never claim tests, lint, type-checks, commits, pushes, or remote verification succeeded unless actually verified.
