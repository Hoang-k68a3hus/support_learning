# DOCX Structure Gold Annotation Guideline V0.1

## 1. Objective

Annotate the **expected structural interpretation of the source**, not the current parser output. Gold must remain useful when implementation IDs or algorithms change.

The benchmark follows `Preserve -> Structure -> Enrich`. This guideline covers only `Preserve` and `Structure`.

## 2. Annotation unit

Annotate at document level. A gold document may contain:

- source elements;
- LogicalUnits;
- ContextNodes/hierarchy;
- ContentRegions;
- structural relations;
- expected adapter diagnostics;
- explicitly unsupported constructs.

Do not create isolated paragraph examples as the master gold record.

## 3. Gold element rules

### 3.1 Preserve source order

`GoldElement.order` follows the adapter-visible source-story order defined by the benchmark case. Orders are unique and ascending.

### 3.2 Stable anchors, never production IDs

A gold element must be alignable without knowing production `Element.id`.
Use `opc_part` and `source_zone` for every element. Then use one of:

- exact visible `text` when unique enough;
- `source_kind + occurrence` for textless structures such as tables/section separators;
- native `source_anchor_kind + source_anchor_id` for notes/comments and other explicit source identities.

### 3.3 Element type

Annotate what the source-near adapter should expose, not a semantic role inferred later.

Examples:

- Word native heading -> `HEADING`;
- ordinary Word paragraph beginning with `Q:` -> `PARAGRAPH`, not `QUESTION`;
- numbered/bulleted paragraph -> `LIST_ITEM`;
- native table container -> `TABLE`;
- native row/cell -> `TABLE_ROW` / `TABLE_CELL`;
- footnote/endnote/comment story emitted through the note contract -> `FOOTNOTE`;
- opaque imported block (`altChunk`) -> `UNKNOWN` plus expected diagnostic.

This distinction is important: lexical Q/A may create a `QA_PAIR` LogicalUnit without rewriting source element facts.

### 3.4 Heading level

Annotate `heading_level` only for `HEADING`. The value is one-based and reflects defensible native/effective Word heading structure. Do not infer a heading level from font size alone in gold.

## 4. LogicalUnit rules

LogicalUnits describe structural/content integrity, not semantic meaning.

Annotate only unit types explicitly included in `evaluated_logical_unit_types`. V0.1 focuses on:

- `LIST_GROUP`;
- `TABLE_BLOCK`;
- `QA_PAIR`;
- other integrity types only when a pilot case specifically tests them.

Do not annotate generic `TEXT_BLOCK` merely to increase label density.

`exact_match=true` means every member element must be present in the predicted unit and no extra member may be present.

### Nested integrity

Nested table blocks are separate LogicalUnits. Parent/child membership is represented by a structural `PART_OF` relation, not by duplicating child elements inside the parent gold unit.

## 5. Context hierarchy

A gold `ContextNode` must be anchored to a source-observed `GoldElement`. The anchor element type and the inferred structural role are separate layers.

Prefer native `TITLE` / `HEADING` anchors when the source provides them. A non-heading source element may anchor a ContextNode only when **strong independent structural evidence** makes the role defensible, for example:

- a rendered standalone document title/section label with stable layout evidence;
- an explicit numbered legal clause that behaves as an outline section rather than an ordinary bullet item;
- another source-observed structural marker whose context role is corroborated by source inspection and independent audit evidence.

When a non-heading element anchors inferred structure:

- keep its `GoldElement.type` source-near; do not rewrite a `PARAGRAPH` or `LIST_ITEM` into `HEADING` merely because it anchors context;
- record the inference/rationale in adjudication metadata or decision notes;
- require evidence stronger than bold text, font size, or a single lexical guess;
- never promote arbitrary list items, labels, or body paragraphs into hierarchy simply to make the tree look complete.

Annotate node `type`, defensible `level`, and canonical `parent_id`. Do not add synthetic hierarchy nodes merely to make levels contiguous. If the source defensibly jumps from level 1 to level 3, gold should preserve that fact and the expected hierarchy policy should be adjudicated explicitly.

## 6. ContentRegion rules

Regions are contiguous local **routing/modality** areas, not semantic topics and never token-sized chunks.

If regions are annotated, they must cover every gold element exactly once with no overlap.

V0.1 categories follow the core routing vocabulary:

`narrative`, `list`, `dialogue`, `code`, `table`, `qa`, `formula`, `log`, `key_value`, `visual`, `boilerplate`, `separator`, `unknown`.

Attach boilerplate/separator material according to the intended canonical region policy rather than creating arbitrary one-element regions solely because the type changes.

## 7. Structural relations

Only relation types declared in `evaluated_relation_types` are scored.
V0.1 uses relations such as:

- `QUESTION_ANSWER`;
- `FOOTNOTE_OF`;
- `PART_OF` for native integrity nesting.

Do not annotate semantic relations (`EXPLAINS`, `SAME_TOPIC`, etc.).
Do not require `NEXT` unless a benchmark case explicitly makes reading-order relation quality part of its target; otherwise its high frequency would dominate the relation score.

## 8. Unsupported constructs and diagnostics

Unsupported does not mean incorrect if the system behaves exactly as declared.

For an unsupported construct, record:

- `construct_type`;
- expected behavior;
- expected diagnostic code when applicable.

Examples:

- `altChunk`: preserve opaque reference and emit structural-completeness diagnostic;
- a complex note structure that V1 intentionally flattens: preserve all visible text and emit a structural-loss diagnostic.

A construct that is silently dropped is always an error.

## 9. Text preservation

Gold `text` is the expected adapter `raw_text` view. Exact text preservation is measured separately from structural interpretation.

Do not normalize whitespace in gold merely to make matching easier. If a source transformation is intentional, update the source-view contract rather than silently changing gold.

## 10. Ambiguity and adjudication

When two source observations cannot be aligned uniquely using source identity/order/text, do not introduce fuzzy matching to force agreement. Mark the benchmark case for adjudication or improve its stable anchor.

For every real-document disagreement added after this synthetic pilot, record:

- source excerpt/anchor;
- annotation A/B if double annotated;
- adjudicated decision;
- reason;
- guideline revision if the rule was unclear.

A production disagreement is evidence to investigate, not a reason to move gold toward the implementation.

## 11. What V0.1 does not annotate

- topics/concepts/entities;
- semantic roles such as definition/example;
- coreference;
- semantic relations;
- retrieval units or token chunks;
- generated answers/citations;
- page/bbox coordinates for reflowable DOCX.

## 12. Pilot-to-real-data rule

The five generated pilot files validate the **evaluation machinery** and exercise known OOXML structures. They must not be used to claim real-world accuracy.

Before publishing accuracy claims, build a separately versioned reviewed real DOCX set drawn from multiple document families and report results separately from the synthetic pilot.
