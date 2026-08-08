# RAG Evaluation and Debugging Reference

Use this reference with `$rag-source-understanding`. Select only the fields and metrics relevant to the layer being investigated.

## Stage diagnostic trace

For one failing query/example, capture enough information to locate the failure:

```text
query_id
query_text
selected_source_ids
selected_subdocument_ids

candidate_corpus_version
canonical_source_revision/content_hash
retrieval_unit_builder_version

sparse_candidates:
  - retrieval_unit_id
  - score
  - source_id

dense_candidates:
  - retrieval_unit_id
  - score
  - source_id

fused_candidates:
  - retrieval_unit_id
  - score/rank

reranked_candidates:
  - retrieval_unit_id
  - score/rank

selected_evidence:
  - evidence_id
  - retrieval_unit_id
  - element_ids
  - source_anchors

answer_claims:
  - claim
  - supporting_evidence_ids
  - citation_result
```

The point is stage localization, not logging every possible field.

## Failure localization

### Relevant source content never entered canonical representation

Investigate adapter/extraction/canonicalization.

Do not tune retrieval.

### Relevant canonical content exists but no suitable RetrievalUnit exists

Investigate grouping, text views, RetrievalUnit construction, exclusion policy, or integrity handling.

Do not tune generation prompts.

### Relevant RetrievalUnit exists but is absent from candidates

Investigate source scope, filtering, sparse/dense retrieval, embeddings, query representation, or candidate budget.

Reranking cannot fix missing recall.

### Relevant unit is in candidates but ranked too low

Investigate fusion/reranking features, score calibration, or candidate competition.

### Correct evidence is selected but answer is unsupported/wrong

Investigate Evidence packaging, grounding/generation policy, or prompt/context construction.

### Correct answer but citation is wrong/unresolvable

Investigate provenance chain and CitationResolver. Do not let the LLM synthesize locations.

## Evaluation matrix

| Layer | Primary questions | Useful measures |
|---|---|---|
| Parsing | Did we preserve what the source actually contains? | fixture invariants, text/order preservation, provenance/location coverage, unsupported-content warnings |
| Structure | Did we infer only what evidence supports? | boundary/group accuracy, hierarchy validity, confidence calibration, explicit-vs-inferred correctness |
| RetrievalUnit | Is the retrieval projection faithful and useful? | reference validation, integrity preservation, rebuildability, size distribution, duplicate rate |
| Retrieval | Did relevant units enter the candidate set? | recall@k, hit rate, MRR, nDCG, precision@k when appropriate |
| Reranking | Did ordering improve without losing recall? | ranking delta, MRR/nDCG delta, recall preservation, latency |
| Evidence | Is selected context sufficient and non-redundant? | evidence coverage, redundancy/overlap, token use |
| Generation | Are claims supported by evidence? | faithfulness, unsupported-claim rate, answer correctness |
| Citation | Does each citation resolve to the correct source revision/location? | citation precision, resolvability, stale-revision rejection |

Do not hard-code universal metric thresholds. Establish a baseline and define an improvement target for the actual dataset/task.

## Regression fixture classes

Prefer fixtures that stress invariants, not only happy paths:

- completely flat text;
- mixed structure in one source;
- weak/ambiguous heading signals;
- duplicate/repeated headers or footers;
- QA pairs near chunk boundaries;
- large tables with headers and merged cells;
- code blocks with surrounding explanation;
- formulas with nearby explanatory text;
- dialogue/log sequences;
- multiple source revisions with same business document ID;
- missing page/bbox but valid textual provenance;
- derived render locations;
- low-confidence/unknown structure;
- semantic enrichment unavailable;
- no relevant retrieval result;
- relevant result just outside candidate budget;
- duplicate candidates from adjacent/overlapping units.

## Change attribution

When comparing two RAG versions:

1. freeze the evaluation set;
2. record source/canonical/retrieval builder versions;
3. change one meaningful policy at a time where possible;
4. compare candidate retrieval before reranking;
5. compare reranking before generation;
6. inspect wins and regressions, not only averages;
7. keep examples of changed outcomes for future regression tests.

A higher end-to-end answer score does not excuse provenance loss, citation breakage, or source data loss.
