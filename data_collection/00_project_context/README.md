# Project context

The authoritative project code remains in the `support_learning` repository. This folder
stores the context used for this crawl snapshot so that the run can be reproduced without
depending on a Google Drive session.

The pilot uses the following design decisions:

- `ANY SOURCE → Element → LogicalUnit → RetrievalUnit → Evidence → Grounded Answer`;
- source fact, inferred structure, and semantic enrichment are separate layers;
- `FLAT`, `LOCAL`, `GROUPED`, `HIERARCHICAL`, and `UNKNOWN` are valid structure states;
- provenance must resolve from candidate → source anchor → original URL;
- a proposed semantic label is not ground truth;
- a source with unclear license or robots status is metadata-only/quarantined.

The full project documents and the crawl setup guide are copied under `documents/` in the
branch as archival context. `context_manifest.json` records the snapshot names without
including private Drive/Library identifiers.
