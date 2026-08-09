from __future__ import annotations

import unittest

from pydantic import ValidationError

from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
    SemanticTextView,
)
from source_understanding.semantics import (
    ROLE_CLASSIFIER_ANNOTATION_TYPES,
    RoleClassifierBatch,
    RoleClassifierLogit,
    RoleClassifierPrediction,
    RoleClassifierProvider,
    RoleClassifierProviderError,
    RoleClassifierProviderPolicy,
    RoleClassifierThreshold,
    SemanticRequest,
    SemanticRequestSegment,
    SemanticTargetKind,
)


def logical_request(index: int = 0) -> SemanticRequest:
    text = f"Gradient descent definition {index}."
    element_id = f"e{index}"
    return SemanticRequest(
        target_id=f"lu{index}",
        target_kind=SemanticTargetKind.LOGICAL_UNIT,
        text=text,
        language="en",
        element_ids=(element_id,),
        target_segments=(
            SemanticRequestSegment(
                element_id=element_id,
                text=text,
                text_view=SemanticTextView.RAW_TEXT,
                element_start=0,
                element_end=len(text),
                request_start=0,
                request_end=len(text),
            ),
        ),
        logical_unit_type="TEXT_BLOCK",
        context_labels=("Optimization",),
    )


class RecordingRoleBackend:
    name = "recording-role-backend"
    version = "1"
    deterministic = True

    def __init__(self, *, omit_last_target: bool = False) -> None:
        self.batches: list[RoleClassifierBatch] = []
        self.omit_last_target = omit_last_target

    def predict(self, batch: RoleClassifierBatch):
        self.batches.append(batch)
        requests = batch.requests[:-1] if self.omit_last_target else batch.requests
        return tuple(
            RoleClassifierPrediction(
                target_id=request.target_id,
                logits=tuple(
                    RoleClassifierLogit(
                        annotation_type=annotation_type,
                        value=(
                            1.0
                            if annotation_type == SemanticAnnotationType.DEFINITION
                            else -1.0
                        ),
                    )
                    for annotation_type in ROLE_CLASSIFIER_ANNOTATION_TYPES
                ),
            )
            for request in requests
        )


class FixedCalibrator:
    name = "fixed-temperature"
    version = "role-calibration-v1"

    def calibrate(self, prediction: RoleClassifierPrediction):
        return tuple(
            {
                "annotation_type": item.annotation_type,
                "probability": 0.91 if item.value > 0 else 0.1,
            }
            for item in prediction.logits
        )


def policy() -> RoleClassifierProviderPolicy:
    return RoleClassifierProviderPolicy(
        thresholds=tuple(
            RoleClassifierThreshold(
                annotation_type=annotation_type,
                minimum_probability=0.8,
            )
            for annotation_type in ROLE_CLASSIFIER_ANNOTATION_TYPES
        )
    )


class RoleClassifierProviderTests(unittest.TestCase):
    def test_emits_only_thresholded_calibrated_multilabel_candidates(self) -> None:
        backend = RecordingRoleBackend()
        provider = RoleClassifierProvider(
            version="model-v1",
            backend=backend,
            calibrator=FixedCalibrator(),
            policy=policy(),
            configuration={"encoder": "fixture"},
        )

        candidates = tuple(provider.annotate((logical_request(),)))

        self.assertEqual(len(backend.batches), 1)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.type, SemanticAnnotationType.DEFINITION)
        self.assertEqual(candidate.value, "DEFINITION")
        self.assertEqual(
            candidate.confidence_method,
            SemanticConfidenceMethod.CALIBRATED_PROBABILITY,
        )
        self.assertEqual(candidate.calibration_version, "role-calibration-v1")
        self.assertEqual(
            provider.configuration["policy"]["thresholds"][0][
                "minimum_probability"
            ],
            0.8,
        )

    def test_rejects_incomplete_backend_target_coverage(self) -> None:
        provider = RoleClassifierProvider(
            version="model-v1",
            backend=RecordingRoleBackend(omit_last_target=True),
            calibrator=FixedCalibrator(),
        )

        with self.assertRaisesRegex(
            RoleClassifierProviderError, "target coverage mismatch"
        ):
            tuple(provider.annotate((logical_request(),)))

    def test_policy_rejects_noncanonical_threshold_order(self) -> None:
        reversed_thresholds = tuple(
            RoleClassifierThreshold(annotation_type=annotation_type)
            for annotation_type in reversed(ROLE_CLASSIFIER_ANNOTATION_TYPES)
        )

        with self.assertRaisesRegex(ValidationError, "canonical Phase A order"):
            RoleClassifierProviderPolicy(thresholds=reversed_thresholds)

if __name__ == "__main__":
    unittest.main()
