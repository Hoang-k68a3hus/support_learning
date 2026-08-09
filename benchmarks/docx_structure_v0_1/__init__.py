"""Deterministic DOCX structure-evaluation pilot."""

from .generate_pilot import (
    GENERATOR_ID,
    GENERATOR_SEED,
    GeneratedCase,
    build_manifest,
    build_pilot_cases,
    materialize,
)

__all__ = [
    "GENERATOR_ID",
    "GENERATOR_SEED",
    "GeneratedCase",
    "build_manifest",
    "build_pilot_cases",
    "materialize",
]
