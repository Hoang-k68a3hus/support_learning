"""Native PDF source adapter through M2.3 structural table recall.

This package remains format-specific. It preserves source-near PDF observations,
adds only high-confidence geometry-derived structure, and then hands control back
to the format-agnostic understanding pipeline. OCR is intentionally deferred as
an optional later extension and is not part of M2.3.
"""

from .adapter_m23 import (
    PDF_ADAPTER_VERSION,
    PDF_BLOCK_RECONSTRUCTION_VERSION,
    PDF_MEDIA_TYPE,
    PDF_POLICY_VERSION,
    PDF_READING_ORDER_VERSION,
    PDF_TABLE_STRUCTURE_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfAdapter,
    PdfAdapterPolicy,
)

__all__ = [
    "PDF_ADAPTER_VERSION",
    "PDF_BLOCK_RECONSTRUCTION_VERSION",
    "PDF_MEDIA_TYPE",
    "PDF_POLICY_VERSION",
    "PDF_READING_ORDER_VERSION",
    "PDF_TABLE_STRUCTURE_VERSION",
    "PDF_TABLE_TEXT_RECONSTRUCTION_VERSION",
    "PdfAdapter",
    "PdfAdapterPolicy",
]
