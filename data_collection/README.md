# SupportLearning data collection snapshot

This directory mirrors the Google Drive data-collection layout for a controlled crawl run.

Run: `run_2026_08_10_001`

The crawl is a candidate-data pilot for `support_learning`. It is not a frozen training
dataset. Every candidate is `LLM_SILVER` and `REVIEW_REQUIRED`; no record is `HUMAN_GOLD`,
and no TRAIN/DEV/TEST split is assigned here.

## Layout

```text
00_project_context/  project documents and crawl context
01_source_policies/  collection, licensing, robots, and provenance policy
02_crawl_manifests/  one JSON object per discovered source
03_raw_allowed/      storage policy for source snapshots; no full page dumps in this pilot
04_candidates/       short, attributed candidate excerpts
05_review_queue/     human-review work items
06_reports/          run-level metrics and limitations
99_quarantine/       metadata-only sources and unresolved access/license checks
```

## Scope

- Discovery target: 10 Vietnamese, 8 English, and 2 mixed-language sources.
- Candidate target: educational and technical text with definitions, procedures,
  examples, objectives, notes, code/markup, and flat/local structure.
- Natural-language text is preserved separately from inferred structure and semantic labels.
- Short excerpts are stored only when a source license is explicit or the record is clearly
  marked for review. Full copyrighted pages are not mirrored.

## Status boundary

```text
web scout → source manifest → candidate excerpt → human review → WorkingRecord
          → GoldCompiler → frozen dataset
```

The files in this branch stop before human review and GoldCompiler.
