from __future__ import annotations

import unittest

from source_understanding.schemas.document import SemanticAnnotationType, SemanticTextView
from source_understanding.semantics.model import (
    ModelSemanticProvider,
    ModelSemanticProviderError,
    ModelSemanticProviderPolicy,
    SemanticModelBatch,
)
from source_understanding.semantics.provider import (
    SemanticCapability,
    SemanticProviderCapabilities,
    SemanticRequest,
    SemanticRequestSegment,
    SemanticTargetKind,
)


CAPABILITIES = SemanticProviderCapabilities(
    capabilities=(
        SemanticCapability(
            name="roles",
            target_kinds=(SemanticTargetKind.ELEMENT,),
            annotation_types=(SemanticAnnotationType.DEFINITION,),
        ),
    ),
    deterministic=False,
)


def request(index: int) -> SemanticRequest:
    text = f"Definition: value {index}"
    return SemanticRequest(
        target_id=f"e{index}",
        target_kind=SemanticTargetKind.ELEMENT,
        text=text,
        element_ids=(f"e{index}",),
        target_segments=(
            SemanticRequestSegment(
                element_id=f"e{index}",
                text=text,
                text_view=SemanticTextView.RAW_TEXT,
                element_start=0,
                element_end=len(text),
                request_start=0,
                request_end=len(text),
            ),
        ),
    )


class RecordingBackend:
    name = "recording-backend"
    version = "1"

    def __init__(self, *, wrong_target: bool = False) -> None:
        self.batches: list[SemanticModelBatch] = []
        self.wrong_target = wrong_target

    def infer(self, batch: SemanticModelBatch):
        self.batches.append(batch)
        return tuple(
            {
                "target_id": "outside" if self.wrong_target else item.target_id,
                "type": "DEFINITION",
                "value": item.text.removeprefix("Definition:").strip(),
                "confidence": 0.9,
            }
            for item in batch.requests
        )


class ModelSemanticProviderTests(unittest.TestCase):
    def test_batches_requests_and_returns_protocol_candidates(self) -> None:
        backend = RecordingBackend()
        provider = ModelSemanticProvider(
            name="test-model",
            version="model-1",
            backend=backend,
            capabilities=CAPABILITIES,
            policy=ModelSemanticProviderPolicy(batch_size=2),
            configuration={"temperature": 0},
        )

        candidates = tuple(provider.annotate(tuple(request(index) for index in range(3))))

        self.assertEqual(len(backend.batches), 2)
        self.assertEqual(tuple(item.target_id for item in candidates), ("e0", "e1", "e2"))
        self.assertEqual(candidates[0].type, SemanticAnnotationType.DEFINITION)
        self.assertEqual(provider.configuration["model"]["temperature"], 0)

    def test_rejects_candidate_for_target_outside_the_active_batch(self) -> None:
        provider = ModelSemanticProvider(
            name="test-model",
            version="model-1",
            backend=RecordingBackend(wrong_target=True),
            capabilities=CAPABILITIES,
        )

        with self.assertRaisesRegex(ModelSemanticProviderError, "outside batch"):
            tuple(provider.annotate((request(0),)))


if __name__ == "__main__":
    unittest.main()
