# Crawl run report: run_2026_08_10_001

## Result

- Run date: 2026-08-10
- Scope: public educational and technical pages for source-understanding/semantic-role candidate data
- Candidate policy: short excerpts only; no full-page mirror
- Gold policy: no HUMAN_GOLD, no frozen split, no TRAIN/DEV/TEST assignment

## Counts

| Metric | Count |
|---|---:|
| Sources discovered | 20 |
| Sources collected as short excerpts | 14 |
| Sources metadata-only | 6 |
| Sources rejected | 0 |
| Sources with candidate records | 14 |
| Candidate records | 14 |
| Review queue records | 14 |
| Crawl/check errors | 4 |
| PII findings | 0 observed |
| Exact duplicates inside this run | 0 |
| Near-duplicate clusters | 0 |

## Discovery language target

| Language | Discovered | Candidate records | Target |
|---|---:|---:|---:|
| Vietnamese | 10 | 4 | 50% |
| English | 8 | 8 | 40% |
| Mixed | 2 | 2 | 10% |

The discovery target is met, but the candidate corpus is not balanced because six Vietnamese
Wikipedia pages remain metadata-only while their robots status is unresolved. This is a
coverage gap, not a reason to translate English text into synthetic Vietnamese.

## Candidate label distribution

- DEFINITION: 9
- PROCEDURE: 4
- LEARNING_OBJECTIVE: 6
- NOTE: 4
- EXERCISE: 1
- WARNING: 1

Counts are multi-label counts, so they do not sum to 14.

## Source and quality observations

- VOER has an explicit CC BY 3.0 notice on the pages sampled, but robots verification was not
  available; each excerpt is small and remains REVIEW_REQUIRED.
- MDN, Python, Rust, Kubernetes, Wikipedia, and Wikibooks expose explicit open licenses, but
  attribution and downstream training-policy review are still required.
- Mixed-language records are natural Vietnamese translations/localizations containing technical
  English terms; `synthetic_translation=false`.
- No page-level PII was observed in the sampled excerpts.
- No candidate is a gold label. The proposed semantic labels are LLM_SILVER only.
- The candidate records preserve source fact separately from inferred structure and semantic
  enrichment.

## Required next actions

1. Verify robots and Terms of Service for VOER, Rust, and Wikibooks.
2. Verify Wikimedia Vietnamese robots policy, then re-run a small excerpt pilot for the six
   metadata-only pages if allowed.
3. Human-review all 14 candidates, especially the four P0 records with unresolved robots status.
4. Resolve the repository's current controlled vocabulary before compiling WorkingRecord.
5. Run deduplication across previous runs before any split or GoldCompiler step.

