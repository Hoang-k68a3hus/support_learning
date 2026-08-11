from __future__ import annotations

import unittest
from types import SimpleNamespace

from pydantic import SecretStr

from ai_data_studio.review.argilla_remote import (
    ArgillaReviewConfig,
    ArgillaReviewRemote,
    build_argilla_record,
    build_argilla_settings,
)
from ai_data_studio.review.contracts import HumanReviewTask
from ai_data_studio.review.errors import (
    ArgillaDatasetContractError,
    ArgillaRemoteReviewConflictError,
)
from ai_data_studio.schemas import WorkingRecordStatus

from tests.ai_data_studio._validation_fixtures import (
    canonical_document,
    positive_definition,
    working_batch,
    working_record,
)


class _NamedCollection(list[object]):
    def __getitem__(self, key):
        if isinstance(key, str):
            for item in self:
                if getattr(item, "name", None) == key:
                    return item
            raise KeyError(key)
        return super().__getitem__(key)


class _FakeSettings:
    def __init__(
        self,
        *,
        guidelines,
        fields,
        questions,
        allow_extra_metadata,
    ) -> None:
        self.guidelines = guidelines
        self.fields = _NamedCollection(fields)
        self.questions = _NamedCollection(questions)
        self.allow_extra_metadata = allow_extra_metadata

    def get(self):
        return self


class _FakeTextField:
    def __init__(self, *, name, title, required, use_markdown, client) -> None:
        self.name = name
        self.title = title
        self.required = required
        self.use_markdown = use_markdown
        self.client = client


class _FakeLabelQuestion:
    def __init__(self, *, name, title, labels, required, client) -> None:
        self.name = name
        self.title = title
        self.labels = tuple(labels)
        self.required = required
        self.client = client


class _FakeTextQuestion:
    def __init__(self, *, name, title, required, use_markdown, client) -> None:
        self.name = name
        self.title = title
        self.required = required
        self.use_markdown = use_markdown
        self.labels = ()
        self.client = client


class _FakeRecord:
    def __init__(self, *, id, fields, metadata) -> None:
        self.id = id
        self.fields = fields
        self.metadata = metadata
        self.responses = {
            "review_outcome": [],
            "review_decisions_json": [],
            "review_notes": [],
        }


class _FakeRecords:
    def __init__(self) -> None:
        self.by_id: dict[str, _FakeRecord] = {}
        self.log_calls = 0

    def __call__(self, **kwargs):
        return tuple(self.by_id[key] for key in sorted(self.by_id))

    def log(self, records) -> None:
        self.log_calls += 1
        for record in records:
            existing = self.by_id.get(record.id)
            if existing is not None:
                record.responses = existing.responses
            self.by_id[record.id] = record


class _FakeDatasets:
    def __init__(self) -> None:
        self.dataset = None

    def __call__(self, *, name, workspace):
        dataset = self.dataset
        if dataset is None:
            return None
        if dataset.name == name and dataset.workspace == workspace:
            return dataset
        return None


class _FakeClient:
    def __init__(self) -> None:
        self.datasets = _FakeDatasets()


class _FakeDataset:
    def __init__(self, *, name, workspace, settings, client) -> None:
        self.name = name
        self.workspace = workspace
        self.settings = settings
        self.client = client
        self.records = _FakeRecords()

    def create(self):
        self.client.datasets.dataset = self
        return self


class _FakeSdk:
    TextField = _FakeTextField
    LabelQuestion = _FakeLabelQuestion
    TextQuestion = _FakeTextQuestion
    Settings = _FakeSettings
    Dataset = _FakeDataset
    Record = _FakeRecord


class ArgillaRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = canonical_document()
        self.batch = working_batch()
        self.record = working_record(
            self.document,
            decisions=(positive_definition(),),
            status=WorkingRecordStatus.REVIEW_REQUIRED,
        )
        self.task = HumanReviewTask(
            record=self.record,
            guideline_version=self.batch.guideline_version,
            expected_decision_hash=self.record.decision_hash,
        )
        self.client = _FakeClient()
        self.config = ArgillaReviewConfig(
            api_url="https://argilla.example.test",
            api_key=SecretStr("test-api-key"),
            workspace="support-learning",
            dataset_name="semantic-review",
        )
        self.remote = ArgillaReviewRemote(
            self.config,
            sdk=_FakeSdk,
            client=self.client,
        )

    def test_config_from_env_requires_explicit_credentials(self) -> None:
        config = ArgillaReviewConfig.from_env(
            {
                "ARGILLA_API_URL": "https://argilla.example.test",
                "ARGILLA_API_KEY": "secret-key",
                "ARGILLA_WORKSPACE": "workspace-a",
                "ARGILLA_REVIEW_DATASET": "review-a",
                "ARGILLA_TIMEOUT_SECONDS": "30",
                "ARGILLA_RETRIES": "2",
            }
        )
        self.assertEqual(config.workspace, "workspace-a")
        self.assertEqual(config.dataset_name, "review-a")
        self.assertEqual(config.timeout_seconds, 30)
        self.assertEqual(config.retries, 2)
        self.assertEqual(config.api_key.get_secret_value(), "secret-key")
        with self.assertRaises(ValueError):
            ArgillaReviewConfig.from_env({"ARGILLA_API_URL": "https://example.test"})

    def test_real_argilla_2_8_settings_and_record_construction(self) -> None:
        import argilla as rg

        client = rg.Argilla(
            api_url="http://127.0.0.1:6900",
            api_key="test-api-key",
        )
        settings = build_argilla_settings(
            rg,
            guidelines="Review semantic roles.",
            client=client,
        )
        self.assertEqual(
            tuple(field.name for field in settings.fields),
            ("raw_text", "normalized_text", "review_context_json"),
        )
        payload = {
            "id": "record-1",
            "fields": {
                "raw_text": "raw",
                "normalized_text": "normalized",
                "review_context_json": "{}",
            },
            "metadata": {"review_contract_version": "1"},
        }
        record = build_argilla_record(rg, payload)
        self.assertEqual(record.id, "record-1")
        self.assertEqual(record.fields["raw_text"], "raw")

    def test_sync_is_idempotent_for_the_same_task_hash(self) -> None:
        first = self.remote.sync_tasks(
            [self.task],
            guidelines="Review semantic roles.",
        )
        second = self.remote.sync_tasks(
            [self.task],
            guidelines="Review semantic roles.",
        )

        self.assertEqual((first.created, first.updated, first.skipped), (1, 0, 0))
        self.assertEqual((second.created, second.updated, second.skipped), (0, 0, 1))
        dataset = self.client.datasets.dataset
        self.assertIsNotNone(dataset)
        assert dataset is not None
        self.assertEqual(dataset.records.log_calls, 1)
        self.assertEqual(len(dataset.records.by_id), 1)

    def test_changed_task_updates_remote_record_without_active_response(self) -> None:
        self.remote.sync_tasks([self.task], guidelines="Review semantic roles.")
        changed = HumanReviewTask(
            record=self.record,
            guideline_version="roles-v2",
            expected_decision_hash=self.record.decision_hash,
        )

        report = self.remote.sync_tasks(
            [changed],
            guidelines="Review semantic roles.",
        )

        self.assertEqual((report.created, report.updated, report.skipped), (0, 1, 0))
        dataset = self.client.datasets.dataset
        assert dataset is not None
        self.assertEqual(
            dataset.records.by_id[self.record.record_id].metadata["guideline_version"],
            "roles-v2",
        )

    def test_changed_task_never_overwrites_active_human_response(self) -> None:
        self.remote.sync_tasks([self.task], guidelines="Review semantic roles.")
        dataset = self.client.datasets.dataset
        assert dataset is not None
        remote_record = dataset.records.by_id[self.record.record_id]
        remote_record.responses["review_outcome"].append(
            SimpleNamespace(status="submitted")
        )
        changed = HumanReviewTask(
            record=self.record,
            guideline_version="roles-v2",
            expected_decision_hash=self.record.decision_hash,
        )

        with self.assertRaises(ArgillaRemoteReviewConflictError):
            self.remote.sync_tasks(
                [changed],
                guidelines="Review semantic roles.",
            )

    def test_existing_dataset_must_match_review_contract(self) -> None:
        dataset = _FakeDataset(
            name=self.config.dataset_name,
            workspace=self.config.workspace,
            settings=_FakeSettings(
                guidelines="Wrong schema",
                fields=[
                    _FakeTextField(
                        name="wrong",
                        title="Wrong",
                        required=True,
                        use_markdown=False,
                        client=self.client,
                    )
                ],
                questions=[],
                allow_extra_metadata=True,
            ),
            client=self.client,
        )
        self.client.datasets.dataset = dataset

        with self.assertRaises(ArgillaDatasetContractError):
            self.remote.ensure_dataset(guidelines="Review semantic roles.")


if __name__ == "__main__":
    unittest.main()
