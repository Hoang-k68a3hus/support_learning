from __future__ import annotations

import unittest
from datetime import datetime, timezone

from source_understanding.adapters.base import AdapterError, SourceAdapterResult
from source_understanding.adapters.runner import SourceAdapterRunner
from source_understanding.atomic import ElementNormalizer
from source_understanding.pipeline import SourceUnderstandingPipeline
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.element import Provenance, RawElement


class FakeAdapter:
    name = "fake"
    version = "1"
    media_types = ("text/plain",)
    extensions = (".txt",)

    def __init__(self, *, bad_hash: bool = False, bad_media_type: bool = False):
        self.bad_hash = bad_hash
        self.bad_media_type = bad_media_type

    def adapt(self, data: bytes, *, source_name: str | None = None) -> SourceAdapterResult:
        return SourceAdapterResult(
            adapter_name=self.name,
            adapter_version=self.version,
            media_type="application/x-undeclared" if self.bad_media_type else "text/plain",
            source_name=source_name,
            content_hash=("sha256:" + "0" * 64) if self.bad_hash else SourceAdapterResult.hash_bytes(data),
            raw_elements=(
                RawElement(
                    text=data.decode("utf-8"),
                    type_hint="paragraph",
                    order=0,
                    provenance=Provenance(
                        source=StructureSource.EXPLICIT,
                        extractor=self.name,
                        extractor_version=self.version,
                    ),
                ),
            ),
        )


class LossyNormalizer(ElementNormalizer):
    def normalize(self, raw_elements, *, document_id):
        result = super().normalize(raw_elements, document_id=document_id)
        changed = result.elements[0].model_copy(update={"raw_text": "changed"})
        return result.model_copy(update={"elements": (changed,)})


class SourceAdapterRunnerTests(unittest.TestCase):
    def test_runner_recomputes_exact_source_hash(self):
        with self.assertRaisesRegex(AdapterError, "content_hash does not match exact input bytes"):
            SourceAdapterRunner().understand_bytes(
                b"hello",
                adapter=FakeAdapter(bad_hash=True),
                document_id="doc",
                processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            )

    def test_runner_rejects_undeclared_media_type(self):
        with self.assertRaisesRegex(AdapterError, "undeclared media_type"):
            SourceAdapterRunner().understand_bytes(
                b"hello",
                adapter=FakeAdapter(bad_media_type=True),
                document_id="doc",
                processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            )

    def test_valid_adapter_preserves_adapter_result_and_pipeline_result(self):
        result = SourceAdapterRunner().understand_bytes(
            b"hello",
            adapter=FakeAdapter(),
            document_id="doc",
            processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(result.adapter_result.content_hash, SourceAdapterResult.hash_bytes(b"hello"))
        self.assertEqual(result.understanding.document.elements[0].raw_text, "hello")
        self.assertEqual(result.understanding.document.processing.adapter_name, "fake")
        self.assertTrue(result.preservation_report.fully_preserved)
        self.assertEqual(result.preservation_report.exact_element_ratio, 1.0)

    def test_runner_fails_closed_when_normalization_loses_source_facts(self):
        runner = SourceAdapterRunner(
            SourceUnderstandingPipeline(normalizer=LossyNormalizer())
        )

        with self.assertRaisesRegex(AdapterError, "preservation audit failed"):
            runner.understand_bytes(
                b"hello",
                adapter=FakeAdapter(),
                document_id="doc",
                processed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
