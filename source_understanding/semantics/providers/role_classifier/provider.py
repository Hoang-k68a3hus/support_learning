from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from source_understanding.schemas.context import (
    Confidence,
    FiniteFloat,
    Identifier,
    JsonObject,
    SchemaModel,
)
from source_understanding.schemas.document import (
    SemanticAnnotationType,
    SemanticConfidenceMethod,
)
from source_understanding.semantics.provider import (
    SemanticCandidate,
    SemanticCapability,
    SemanticProviderCapabilities,
    SemanticRequest,
    SemanticTargetKind,
)


ROLE_CLASSIFIER_PROVIDER_VERSION = "1"
ROLE_CLASSIFIER_POLICY_VERSION = "1"
ROLE_CLASSIFIER_CAPABILITY_NAME = "educational-role-classification"
ROLE_CLASSIFIER_ANNOTATION_TYPES = (
    SemanticAnnotationType.DEFINITION,
    SemanticAnnotationType.EXAMPLE,
    SemanticAnnotationType.PROCEDURE,
    SemanticAnnotationType.NOTE,
    SemanticAnnotationType.WARNING,
    SemanticAnnotationType.EXERCISE,
)
_ROLE_CLASSIFIER_ANNOTATION_TYPE_SET = frozenset(
    ROLE_CLASSIFIER_ANNOTATION_TYPES
)


class RoleClassifierProviderError(ValueError):
    """A role backend or calibrator violated the provider boundary."""


class RoleClassifierThreshold(SchemaModel):
    annotation_type: SemanticAnnotationType
    minimum_probability: Confidence = 0.5

    @model_validator(mode="after")
    def validate_annotation_type(self) -> "RoleClassifierThreshold":
        if self.annotation_type not in _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET:
            raise ValueError(
                "role classifier thresholds only support Phase A semantic roles"
            )
        return self


def _default_thresholds() -> tuple[RoleClassifierThreshold, ...]:
    return tuple(
        RoleClassifierThreshold(annotation_type=annotation_type)
        for annotation_type in ROLE_CLASSIFIER_ANNOTATION_TYPES
    )


class RoleClassifierProviderPolicy(SchemaModel):
    version: str = ROLE_CLASSIFIER_POLICY_VERSION
    batch_size: int = Field(default=16, ge=1, le=256)
    thresholds: tuple[RoleClassifierThreshold, ...] = Field(
        default_factory=_default_thresholds,
        min_length=len(ROLE_CLASSIFIER_ANNOTATION_TYPES),
        max_length=len(ROLE_CLASSIFIER_ANNOTATION_TYPES),
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "RoleClassifierProviderPolicy":
        annotation_types = tuple(item.annotation_type for item in self.thresholds)
        if len(annotation_types) != len(set(annotation_types)):
            raise ValueError("role classifier thresholds must be unique by role")
        if annotation_types != ROLE_CLASSIFIER_ANNOTATION_TYPES:
            missing = _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET - set(annotation_types)
            extra = set(annotation_types) - _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET
            raise ValueError(
                "role classifier thresholds must use the canonical Phase A order; "
                f"missing={sorted(item.value for item in missing)}, "
                f"extra={sorted(item.value for item in extra)}"
            )
        return self

    def threshold_for(self, annotation_type: SemanticAnnotationType) -> float:
        for item in self.thresholds:
            if item.annotation_type == annotation_type:
                return item.minimum_probability
        raise ValueError(
            f"role classifier policy has no threshold for {annotation_type.value!r}"
        )


class RoleClassifierLogit(SchemaModel):
    annotation_type: SemanticAnnotationType
    value: FiniteFloat

    @model_validator(mode="after")
    def validate_annotation_type(self) -> "RoleClassifierLogit":
        if self.annotation_type not in _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET:
            raise ValueError("role classifier logits contain an unsupported role")
        return self


class RoleClassifierPrediction(SchemaModel):
    target_id: Identifier
    logits: tuple[RoleClassifierLogit, ...] = Field(
        min_length=len(ROLE_CLASSIFIER_ANNOTATION_TYPES),
        max_length=len(ROLE_CLASSIFIER_ANNOTATION_TYPES),
    )

    @model_validator(mode="after")
    def validate_logits(self) -> "RoleClassifierPrediction":
        annotation_types = tuple(item.annotation_type for item in self.logits)
        if len(annotation_types) != len(set(annotation_types)):
            raise ValueError("role classifier logits must be unique by role")
        if set(annotation_types) != _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET:
            raise ValueError(
                "role classifier prediction must contain the exact Phase A label set"
            )
        return self


class RoleClassifierProbability(SchemaModel):
    annotation_type: SemanticAnnotationType
    probability: Confidence

    @model_validator(mode="after")
    def validate_annotation_type(self) -> "RoleClassifierProbability":
        if self.annotation_type not in _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET:
            raise ValueError("role classifier probabilities contain an unsupported role")
        return self


class RoleClassifierBatch(SchemaModel):
    provider_name: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=128)
    batch_index: int = Field(ge=0)
    requests: tuple[SemanticRequest, ...] = Field(min_length=1)
    annotation_types: tuple[SemanticAnnotationType, ...] = (
        ROLE_CLASSIFIER_ANNOTATION_TYPES
    )

    @model_validator(mode="after")
    def validate_requests(self) -> "RoleClassifierBatch":
        target_ids = tuple(request.target_id for request in self.requests)
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("role classifier batch target_ids must be unique")
        if any(
            request.target_kind != SemanticTargetKind.LOGICAL_UNIT
            for request in self.requests
        ):
            raise ValueError("role classifier only accepts LOGICAL_UNIT requests")
        if self.annotation_types != ROLE_CLASSIFIER_ANNOTATION_TYPES:
            raise ValueError("role classifier batch label order is not canonical")
        return self


@runtime_checkable
class RoleClassifierBackend(Protocol):
    """Framework-neutral backend that returns one full logit vector per target."""

    name: str
    version: str
    deterministic: bool | None

    def predict(self, batch: RoleClassifierBatch) -> Iterable[object]: ...


@runtime_checkable
class RoleClassifierCalibrator(Protocol):
    """Convert one full logit vector into calibrated per-role probabilities."""

    name: str
    version: str

    def calibrate(self, prediction: RoleClassifierPrediction) -> Iterable[object]: ...


class _RoleClassifierConfiguration(SchemaModel):
    value: JsonObject


class RoleClassifierProvider:
    """Multi-label semantic-role provider independent of any ML framework."""

    name = "semantic-role-classifier"
    implementation_version = ROLE_CLASSIFIER_PROVIDER_VERSION

    def __init__(
        self,
        *,
        version: str,
        backend: RoleClassifierBackend,
        calibrator: RoleClassifierCalibrator,
        policy: RoleClassifierProviderPolicy | None = None,
        configuration: dict[str, object] | None = None,
    ) -> None:
        self.version = self._validate_identity(version, "provider version")
        self._backend_name, self._backend_version = self._validate_backend(backend)
        self._calibrator_name, self._calibration_version = (
            self._validate_calibrator(calibrator)
        )
        self._backend = backend
        self._calibrator = calibrator
        self._policy = (
            policy if policy is not None else RoleClassifierProviderPolicy()
        )
        self.capabilities = SemanticProviderCapabilities(
            capabilities=(
                SemanticCapability(
                    name=ROLE_CLASSIFIER_CAPABILITY_NAME,
                    target_kinds=(SemanticTargetKind.LOGICAL_UNIT,),
                    annotation_types=ROLE_CLASSIFIER_ANNOTATION_TYPES,
                ),
            ),
            deterministic=backend.deterministic,
        )
        self.configuration = _RoleClassifierConfiguration(
            value={
                "implementation_version": self.implementation_version,
                "backend": {
                    "name": self._backend_name,
                    "version": self._backend_version,
                },
                "calibrator": {
                    "name": self._calibrator_name,
                    "version": self._calibration_version,
                },
                "policy": self._policy.model_dump(mode="json"),
                "model": {} if configuration is None else configuration,
            }
        ).value

    @staticmethod
    def _validate_identity(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
            raise TypeError(f"role classifier {field_name} must be non-blank and <= 128 chars")
        return value.strip()

    @classmethod
    def _validate_backend(cls, backend: object) -> tuple[str, str]:
        name = cls._validate_identity(getattr(backend, "name", None), "backend name")
        version = cls._validate_identity(
            getattr(backend, "version", None), "backend version"
        )
        if getattr(backend, "deterministic", None) not in (True, False, None):
            raise TypeError("role classifier backend deterministic must be bool or None")
        if not callable(getattr(backend, "predict", None)):
            raise TypeError("role classifier backend must define callable predict(batch)")
        return name, version

    @classmethod
    def _validate_calibrator(cls, calibrator: object) -> tuple[str, str]:
        name = cls._validate_identity(
            getattr(calibrator, "name", None), "calibrator name"
        )
        version = cls._validate_identity(
            getattr(calibrator, "version", None), "calibrator version"
        )
        if not callable(getattr(calibrator, "calibrate", None)):
            raise TypeError(
                "role classifier calibrator must define callable calibrate(prediction)"
            )
        return name, version

    def annotate(
        self,
        requests: tuple[SemanticRequest, ...],
    ) -> Iterable[SemanticCandidate]:
        snapshot = tuple(requests)
        target_ids = tuple(request.target_id for request in snapshot)
        if len(target_ids) != len(set(target_ids)):
            raise RoleClassifierProviderError(
                "role classifier requires unique request target_ids"
            )
        if any(
            request.target_kind != SemanticTargetKind.LOGICAL_UNIT
            for request in snapshot
        ):
            raise RoleClassifierProviderError(
                "role classifier only accepts LOGICAL_UNIT requests"
            )
        if not snapshot:
            return ()

        output: list[SemanticCandidate] = []
        batch_size = self._policy.batch_size
        for batch_index, start in enumerate(range(0, len(snapshot), batch_size)):
            requests_batch = snapshot[start : start + batch_size]
            batch = RoleClassifierBatch(
                provider_name=self.name,
                provider_version=self.version,
                batch_index=batch_index,
                requests=requests_batch,
            )
            predictions = self._predict(batch)
            predictions_by_target = {
                prediction.target_id: prediction for prediction in predictions
            }
            expected_targets = tuple(request.target_id for request in requests_batch)
            if set(predictions_by_target) != set(expected_targets):
                missing = set(expected_targets) - set(predictions_by_target)
                extra = set(predictions_by_target) - set(expected_targets)
                raise RoleClassifierProviderError(
                    "role classifier backend target coverage mismatch for batch "
                    f"{batch_index}; missing={sorted(missing)}, extra={sorted(extra)}"
                )

            for target_id in expected_targets:
                probabilities = self._calibrate(predictions_by_target[target_id])
                by_type = {item.annotation_type: item for item in probabilities}
                for annotation_type in ROLE_CLASSIFIER_ANNOTATION_TYPES:
                    probability = by_type[annotation_type].probability
                    if probability < self._policy.threshold_for(annotation_type):
                        continue
                    output.append(
                        SemanticCandidate(
                            target_id=target_id,
                            type=annotation_type,
                            value=annotation_type.value,
                            confidence=probability,
                            confidence_method=(
                                SemanticConfidenceMethod.CALIBRATED_PROBABILITY
                            ),
                            calibration_version=self._calibration_version,
                            capability_name=ROLE_CLASSIFIER_CAPABILITY_NAME,
                        )
                    )
        return tuple(output)

    def _predict(
        self,
        batch: RoleClassifierBatch,
    ) -> tuple[RoleClassifierPrediction, ...]:
        try:
            raw_predictions = tuple(self._backend.predict(batch))
        except Exception as exc:
            raise RoleClassifierProviderError(
                f"role classifier backend {self._backend_name!r} failed for "
                f"batch {batch.batch_index}: {exc}"
            ) from exc

        predictions: list[RoleClassifierPrediction] = []
        for raw_prediction in raw_predictions:
            try:
                predictions.append(
                    RoleClassifierPrediction.model_validate(raw_prediction)
                )
            except Exception as exc:
                raise RoleClassifierProviderError(
                    "role classifier backend returned invalid prediction: "
                    f"{raw_prediction!r}: {exc}"
                ) from exc
        target_ids = tuple(item.target_id for item in predictions)
        if len(target_ids) != len(set(target_ids)):
            raise RoleClassifierProviderError(
                "role classifier backend returned duplicate target predictions"
            )
        return tuple(predictions)

    def _calibrate(
        self,
        prediction: RoleClassifierPrediction,
    ) -> tuple[RoleClassifierProbability, ...]:
        try:
            raw_probabilities = tuple(self._calibrator.calibrate(prediction))
        except Exception as exc:
            raise RoleClassifierProviderError(
                f"role classifier calibrator {self._calibrator_name!r} failed for "
                f"target {prediction.target_id!r}: {exc}"
            ) from exc

        probabilities: list[RoleClassifierProbability] = []
        for raw_probability in raw_probabilities:
            try:
                probabilities.append(
                    RoleClassifierProbability.model_validate(raw_probability)
                )
            except Exception as exc:
                raise RoleClassifierProviderError(
                    "role classifier calibrator returned invalid probability: "
                    f"{raw_probability!r}: {exc}"
                ) from exc
        annotation_types = tuple(item.annotation_type for item in probabilities)
        if len(annotation_types) != len(set(annotation_types)):
            raise RoleClassifierProviderError(
                "role classifier calibrator returned duplicate role probabilities"
            )
        if set(annotation_types) != _ROLE_CLASSIFIER_ANNOTATION_TYPE_SET:
            raise RoleClassifierProviderError(
                "role classifier calibrator must return the exact Phase A label set"
            )
        return tuple(probabilities)
