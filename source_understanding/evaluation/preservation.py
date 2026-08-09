"""Evaluation-facing re-export of the atomic parser-preservation audit."""

from source_understanding.atomic.preservation import (
    PARSER_PRESERVATION_EVALUATOR_VERSION,
    ParserPreservationReport,
    evaluate_parser_preservation,
)

__all__ = [
    "PARSER_PRESERVATION_EVALUATOR_VERSION",
    "ParserPreservationReport",
    "evaluate_parser_preservation",
]
