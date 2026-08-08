"""Source-near adapters that preserve format facts before interpretation."""

from .base import (
    SOURCE_ADAPTER_PROTOCOL_VERSION,
    AdapterDiagnostic,
    AdapterDiagnosticLevel,
    AdapterError,
    SourceAdapter,
    SourceAdapterResult,
    validate_adapter,
)
from .docx import (
    DOCX_ADAPTER_VERSION,
    DOCX_MEDIA_TYPE,
    DOCX_POLICY_VERSION,
    DocxAdapter,
    DocxAdapterPolicy,
    RevisionView,
)
from .runner import (
    SOURCE_ADAPTER_RUNNER_VERSION,
    AdaptedSourceUnderstandingResult,
    SourceAdapterRunner,
)

__all__ = [
    "SOURCE_ADAPTER_PROTOCOL_VERSION",
    "SOURCE_ADAPTER_RUNNER_VERSION",
    "AdapterDiagnostic",
    "AdapterDiagnosticLevel",
    "AdapterError",
    "SourceAdapter",
    "SourceAdapterResult",
    "validate_adapter",
    "DOCX_ADAPTER_VERSION",
    "DOCX_MEDIA_TYPE",
    "DOCX_POLICY_VERSION",
    "DocxAdapter",
    "DocxAdapterPolicy",
    "RevisionView",
    "AdaptedSourceUnderstandingResult",
    "SourceAdapterRunner",
]
