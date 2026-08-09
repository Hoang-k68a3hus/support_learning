"""Deterministic generated DOCX sources with adjudicated structure gold."""

from .adjudicated_pilot import (
    GOLD_ADJUDICATION_VERSION,
    build_adjudicated_manifest,
    build_pilot_cases,
    materialize,
)
from .generate_pilot import (
    GENERATOR_ID,
    GENERATOR_SEED,
    GeneratedCase,
)

__all__ = [
    "GENERATOR_ID",
    "GENERATOR_SEED",
    "GOLD_ADJUDICATION_VERSION",
    "GeneratedCase",
    "build_adjudicated_manifest",
    "build_pilot_cases",
    "materialize",
]
