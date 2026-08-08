"""Universal source-understanding package."""

from .assembly import (
    ASSEMBLY_VERSION,
    STRUCTURE_PIPELINE_VERSION,
    AssemblyError,
    CanonicalDocumentAssembler,
)

__all__ = [
    "ASSEMBLY_VERSION",
    "STRUCTURE_PIPELINE_VERSION",
    "AssemblyError",
    "CanonicalDocumentAssembler",
]
