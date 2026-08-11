"""Native PDF source adapter M1.

This package is intentionally format-specific. It emits source-near / derived
RawElements and then hands control back to the format-agnostic understanding
pipeline.
"""

from .adapter import (
    PDF_ADAPTER_VERSION,
    PDF_BLOCK_RECONSTRUCTION_VERSION,
    PDF_MEDIA_TYPE,
    PDF_POLICY_VERSION,
    PDF_READING_ORDER_VERSION,
    PdfAdapter,
    PdfAdapterPolicy,
)

__all__ = [
    "PDF_ADAPTER_VERSION",
    "PDF_BLOCK_RECONSTRUCTION_VERSION",
    "PDF_MEDIA_TYPE",
    "PDF_POLICY_VERSION",
    "PDF_READING_ORDER_VERSION",
    "PdfAdapter",
    "PdfAdapterPolicy",
]
