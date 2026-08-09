# Semantic role annotation guideline v0.1

Annotate the narrowest defensible target. A local marker on one Element must not
label its whole LogicalUnit.

Gold roles describe semantic meaning, never source structure. Do not change an
Element type or create a heading to express `DEFINITION`, `EXAMPLE`, `WARNING`,
`NOTE`, `EXERCISE`, `SUMMARY`, or related roles.

For this pilot:

1. Label an explicit role only when the full source text supports it.
2. Do not label ordinary prose merely because it contains words such as
   "definition" or "example".
3. Preserve the exact element order, text, and type in gold.
4. Record one `(target, annotation type)` pair at most once.
5. Keep annotation values as reviewer context; role scoring compares target and
   type, not generated wording.
6. `CUSTOM` labels are outside v0.1 because ontology-specific evaluation needs a
   separate adjudication contract.
