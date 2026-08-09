# Role classifier training dataset format v2

`RoleClassifierTrainingDataset` is the canonical JSON envelope for the Phase A
multi-label classifier. It belongs to AI Data Studio and is separate from the
production semantic runtime and from `benchmarks/semantic_roles_v0_1/gold.json`,
which remains an evaluation benchmark.

The Phase A label order is fixed for schema version `2`:

```text
DEFINITION, EXAMPLE, PROCEDURE, NOTE, WARNING, EXERCISE
```

Each example stores:

- exact `document_id`, `content_hash`, and optional `source_revision`;
- required `source_family_id` and strongest-leakage `split_group_id` identities;
- a source-stable `LOGICAL_UNIT` target expressed by canonical element orders;
- the complete, source-grounded `SemanticRequest` used as model input, including
  reversible target/context segments;
- zero or more labels (an empty tuple is a required, valid negative example);
- generic `DatasetSplit` (`train`, `dev`, or `test`) identity resolved from a
  separate split manifest by the downstream exporter;
- either `HUMAN_GOLD` or `LLM_SILVER` label provenance.

`LLM_SILVER` rows require the teacher provider name, version, and configuration
hash. `test` rows reject silver labels and the dataset serializes the
`HUMAN_ONLY_FROZEN` test policy. An exact `(content_hash, target element orders)`
cannot occur twice. A `split_group_id`, `source_family_id`, or `content_hash`
cannot occur in more than one split, including when the targets differ. Each
`source_family_id`, `content_hash`, and `document_id` must also belong to one
split group, preventing ambiguous grouping even when both groups currently map
to the same split.
`RoleClassifierDatasetSplit` remains a compatibility alias for `DatasetSplit`;
the generic vocabulary in `ai_data_studio.datasets` is the long-term contract.

Load and validate before training:

```python
from ai_data_studio.training.role_classifier import (
    load_role_classifier_training_dataset,
)

dataset = load_role_classifier_training_dataset("training.json")
```

Backbone-specific tokenization, tensor serialization, class weighting, and data
augmentation are intentionally downstream transformations of this canonical
format. They must retain `example_id` so predictions remain auditable.

Dependency direction is one-way:

```text
ai_data_studio -> source_understanding
```

Production `source_understanding` code must remain runnable without AI Data
Studio, annotation datasets, training dependencies, or external workbenches.
