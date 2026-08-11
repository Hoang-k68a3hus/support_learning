from __future__ import annotations

from math import isfinite
from typing import Any

from source_understanding.schemas.document import DocumentMetadata

from ..base import AdapterDiagnostic
from .models import PdfPageObservation


class PdfMetadataBuilder:
    """Build JSON-safe document/page metadata without inventing source facts."""

    def build(
        self,
        *,
        document: Any,
        backend: Any,
        source_name: str | None,
        page_metadata: list[dict[str, object]],
        pages_with_native_text: int,
        pages_with_images: int,
        diagnostics: list[AdapterDiagnostic],
        reading_order_version: str,
        block_reconstruction_version: str,
    ) -> DocumentMetadata:
        standard = self.safe_mapping(getattr(document, "metadata", None))
        xmp_xml = self.xmp_metadata(document, diagnostics=diagnostics)
        pdf_attributes: dict[str, object] = {
            "backend": {
                "name": backend.name,
                "pymupdf_version": backend.version,
                "mupdf_version": backend.mupdf_version,
            },
            "format": standard.get("format"),
            "encryption": standard.get("encryption"),
            "permissions": int(getattr(document, "permissions", 0)),
            "needs_pass": bool(getattr(document, "needs_pass", False)),
            "is_repaired": bool(getattr(document, "is_repaired", False)),
            "is_fast_webaccess": bool(
                getattr(document, "is_fast_webaccess", False)
            ),
            "is_form_pdf": bool(getattr(document, "is_form_pdf", False)),
            "page_layout": getattr(document, "pagelayout", None),
            "page_mode": getattr(document, "pagemode", None),
            "mark_info": getattr(document, "markinfo", None),
            "version_count": int(getattr(document, "version_count", 0)),
            "page_count": len(page_metadata),
            "pages_with_native_text": pages_with_native_text,
            "pages_with_image_blocks": pages_with_images,
            "standard_metadata": standard,
            "xmp_metadata": xmp_xml,
            "pages": page_metadata,
            "coordinate_view": (
                "visible displayed page; top-left origin; bboxes normalized "
                "after applying PDF page rotation"
            ),
            "native_coordinate_view": (
                "PyMuPDF unrotated page coordinates retained in pdf_*_bbox_points"
            ),
            "reading_order_version": reading_order_version,
            "block_reconstruction_version": block_reconstruction_version,
        }
        author = self.non_blank(standard.get("author"))
        return DocumentMetadata(
            title=self.non_blank(standard.get("title")),
            source_name=source_name,
            authors=(author,) if author is not None else (),
            attributes={"pdf": pdf_attributes},
        )

    @staticmethod
    def page_record(
        page: PdfPageObservation,
        *,
        emitted_block_count: int,
    ) -> dict[str, object]:
        return {
            "page": page.page_number,
            "width_points": page.width_points,
            "height_points": page.height_points,
            "rotation_degrees": page.rotation,
            "cropbox_points": list(page.cropbox),
            "mediabox_points": list(page.mediabox),
            "cropbox_position_points": list(page.cropbox_position),
            "native_text_block_count": len(page.native_text_blocks),
            "emitted_block_count": emitted_block_count,
            "image_block_count": page.image_block_count,
        }

    @staticmethod
    def safe_mapping(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        output: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            if item is None or isinstance(item, (str, bool, int)):
                output[key] = item
            elif isinstance(item, float):
                output[key] = item if isfinite(item) else str(item)
            else:
                output[key] = str(item)
        return output

    @staticmethod
    def xmp_metadata(
        document: Any,
        *,
        diagnostics: list[AdapterDiagnostic],
    ) -> str | None:
        try:
            value = document.get_xml_metadata()
        except Exception as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_XMP_METADATA_UNAVAILABLE",
                    message=f"PDF XMP metadata could not be read: {exc}",
                    metadata={"error_type": type(exc).__name__},
                )
            )
            return None
        if not isinstance(value, str) or not value:
            return None
        return value

    @staticmethod
    def non_blank(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped if stripped else None
