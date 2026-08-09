"""Production multi-label semantic-role provider contracts."""

from .provider import (
    ROLE_CLASSIFIER_ANNOTATION_TYPES,
    ROLE_CLASSIFIER_CAPABILITY_NAME,
    ROLE_CLASSIFIER_POLICY_VERSION,
    ROLE_CLASSIFIER_PROVIDER_VERSION,
    RoleClassifierBackend,
    RoleClassifierBatch,
    RoleClassifierCalibrator,
    RoleClassifierLogit,
    RoleClassifierPrediction,
    RoleClassifierProbability,
    RoleClassifierProvider,
    RoleClassifierProviderError,
    RoleClassifierProviderPolicy,
    RoleClassifierThreshold,
)

__all__ = [
    "ROLE_CLASSIFIER_ANNOTATION_TYPES",
    "ROLE_CLASSIFIER_CAPABILITY_NAME",
    "ROLE_CLASSIFIER_POLICY_VERSION",
    "ROLE_CLASSIFIER_PROVIDER_VERSION",
    "RoleClassifierBackend",
    "RoleClassifierBatch",
    "RoleClassifierCalibrator",
    "RoleClassifierLogit",
    "RoleClassifierPrediction",
    "RoleClassifierProbability",
    "RoleClassifierProvider",
    "RoleClassifierProviderError",
    "RoleClassifierProviderPolicy",
    "RoleClassifierThreshold",
]
