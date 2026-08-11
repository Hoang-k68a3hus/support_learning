from __future__ import annotations

from collections import Counter

from pydantic import Field

from source_understanding.schemas.context import SchemaModel
from source_understanding.schemas.element import RawElement

from ..base import (
    AdapterDiagnostic,
    AdapterDiagnosticLevel,
    AdapterError,
    SourceAdapterResult,
)
from .backend import PdfBackendError, PyMuPdfNativeBackend
from .emit import PdfRawElementEmitter
from .metadata import PdfMetadataBuilder
from .order import PdfReadingOrderPolicy, PdfReadingOrderResolver


PDF_ADAPTER_VERSION = "1"
PDF_POLICY_VERSION = "2"
PDF_MEDIA_TYPE = "application/pdf"
PDF_READING_ORDER_VERSION = "geometric-columns-v2"
PDF_BLOCK_RECONSTRUCTION_VERSION = "textpage-block-v1"


class PdfAdapterPolicy(SchemaModel):
    """Deterministic M1 policy for born-digital/native-text PDFs only."""

    version: str = PDF_POLICY_VERSION
    max_source_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=1,
        le=2 * 1024 * 1024 * 1024,
    )
    pdf_header_search_bytes: int = Field(default=1024, ge=5, le=4096)
    full_width_ratio: float = Field(default=0.68, ge=0.50, le=1.0)
    minimum_column_gap_ratio: float = Field(default=0.025, ge=0.0, le=0.25)
    minimum_vertical_overlap_ratio: float = Field(default=0.20, ge=0.0, le=1.0)
    column_join_overlap_ratio: float = Field(default=0.35, gt=0.0, le=1.0)
    maximum_separator_vertical_overlap_ratio: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
    )
    aligned_row_overlap_ratio: float = Field(default=0.50, gt=0.0, le=1.0)
    aligned_row_gap_ratio: float = Field(default=0.01, ge=0.0, le=0.25)
    aligned_layout_many_rows: int = Field(default=6, ge=2, le=100)
    aligned_layout_multi_cell_rows: int = Field(default=3, ge=1, le=100)
    bbox_tolerance_points: float = Field(default=1.0, ge=0.0, le=10.0)
    preserve_span_metadata: bool = True


class PdfAdapter:
    """Preserve native PDF spatial text facts before structural interpretation."""

    name = "pdf-native-pymupdf"
    version = PDF_ADAPTER_VERSION
    media_types = (PDF_MEDIA_TYPE,)
    extensions = (".pdf",)

    def __init__(
        self,
        policy: PdfAdapterPolicy | None = None,
        *,
        backend: PyMuPdfNativeBackend | None = None,
    ) -> None:
        self.policy = policy if policy is not None else PdfAdapterPolicy()
        self._backend = backend
        self._order_resolver = PdfReadingOrderResolver(
            PdfReadingOrderPolicy(
                full_width_ratio=self.policy.full_width_ratio,
                minimum_column_gap_ratio=self.policy.minimum_column_gap_ratio,
                minimum_vertical_overlap_ratio=self.policy.minimum_vertical_overlap_ratio,
                column_join_overlap_ratio=self.policy.column_join_overlap_ratio,
                maximum_separator_vertical_overlap_ratio=(
                    self.policy.maximum_separator_vertical_overlap_ratio
                ),
                aligned_row_overlap_ratio=self.policy.aligned_row_overlap_ratio,
                aligned_row_gap_ratio=self.policy.aligned_row_gap_ratio,
                aligned_layout_many_rows=self.policy.aligned_layout_many_rows,
                aligned_layout_multi_cell_rows=self.policy.aligned_layout_multi_cell_rows,
            )
        )
        self._emitter = PdfRawElementEmitter(
            adapter_name=self.name,
            adapter_version=self.version,
            reading_order_version=PDF_READING_ORDER_VERSION,
            block_reconstruction_version=PDF_BLOCK_RECONSTRUCTION_VERSION,
            bbox_tolerance_points=self.policy.bbox_tolerance_points,
            preserve_span_metadata=self.policy.preserve_span_metadata,
        )
        self._metadata_builder = PdfMetadataBuilder()

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        payload = self._validate_payload(data)
        backend = self._backend if self._backend is not None else self._create_backend()
        document = backend.open(payload)
        diagnostics: list[AdapterDiagnostic] = []
        try:
            self._validate_document(document, diagnostics=diagnostics)
            page_count = int(getattr(document, "page_count", 0))
            raw_elements: list[RawElement] = []
            page_metadata: list[dict[str, object]] = []
            pages_with_native_text = 0
            pages_with_images = 0

            for page_index in range(page_count):
                try:
                    page = document.load_page(page_index)
                    observation = backend.page_observation(page)
                except PdfBackendError as exc:
                    raise AdapterError(str(exc)) from exc
                except Exception as exc:
                    raise AdapterError(
                        f"failed to inspect PDF page {page_index + 1}: {exc}"
                    ) from exc

                aligned_layout = self._order_resolver.looks_aligned_layout(
                    observation.native_text_blocks,
                    page_width=observation.width_points,
                )
                ordered = self._order_resolver.resolve(
                    observation.native_text_blocks,
                    page_width=observation.width_points,
                )
                if aligned_layout:
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_ALIGNED_LAYOUT_NOT_STRUCTURED_M1",
                            message=(
                                f"PDF page {observation.page_number} contains repeated "
                                "row-aligned native text geometry consistent with a grid, "
                                "form, equation array, or table-like layout. M1 preserves "
                                "native block order and does not infer rows, cells, or "
                                "higher-order structure"
                            ),
                            affects_structural_completeness=True,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "native_text_block_count": len(
                                    observation.native_text_blocks
                                ),
                                "reading_order_action": "preserve_native_order",
                            },
                        )
                    )

                emitted_on_page = 0
                suspect_codepoints: Counter[str] = Counter()
                suspect_block_count = 0
                for reading_index, block in enumerate(ordered):
                    raw = self._emitter.emit(
                        block,
                        page=observation,
                        reading_index=reading_index,
                        global_order=len(raw_elements),
                        backend=backend,
                    )
                    if raw is not None:
                        suspicions = self._suspect_native_text_codepoints(raw.text)
                        if suspicions:
                            suspect_block_count += 1
                            suspect_codepoints.update(suspicions)
                        raw_elements.append(raw)
                        emitted_on_page += 1

                if emitted_on_page:
                    pages_with_native_text += 1
                else:
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_PAGE_NO_NATIVE_TEXT",
                            message=(
                                f"PDF page {observation.page_number} produced no native text "
                                "blocks; OCR is intentionally outside M1"
                            ),
                            affects_structural_completeness=True,
                            part=f"page:{observation.page_number}",
                            metadata={"page": observation.page_number},
                        )
                    )
                if suspect_codepoints:
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_NATIVE_TEXT_MAPPING_SUSPECT",
                            message=(
                                f"PDF page {observation.page_number} native text contains "
                                "non-printing or replacement code points; the embedded "
                                "font-to-Unicode mapping may be incomplete. Extracted text "
                                "is preserved unchanged and OCR is intentionally outside M1"
                            ),
                            affects_structural_completeness=True,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "affected_block_count": suspect_block_count,
                                "codepoint_counts": dict(sorted(suspect_codepoints.items())),
                            },
                        )
                    )
                if observation.image_block_count:
                    pages_with_images += 1
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_IMAGE_CONTENT_NOT_EXTRACTED_M1",
                            message=(
                                f"PDF page {observation.page_number} contains image blocks; "
                                "M1 preserves native text only and does not claim image content"
                            ),
                            affects_structural_completeness=True,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "image_block_count": observation.image_block_count,
                            },
                        )
                    )
                page_metadata.append(
                    self._metadata_builder.page_record(
                        observation,
                        emitted_block_count=emitted_on_page,
                    )
                )

            metadata = self._metadata_builder.build(
                document=document,
                backend=backend,
                source_name=source_name,
                page_metadata=page_metadata,
                pages_with_native_text=pages_with_native_text,
                pages_with_images=pages_with_images,
                diagnostics=diagnostics,
                reading_order_version=PDF_READING_ORDER_VERSION,
                block_reconstruction_version=PDF_BLOCK_RECONSTRUCTION_VERSION,
            )
            return SourceAdapterResult(
                adapter_name=self.name,
                adapter_version=self.version,
                media_type=PDF_MEDIA_TYPE,
                source_name=source_name,
                content_hash=SourceAdapterResult.hash_bytes(payload),
                raw_elements=tuple(raw_elements),
                metadata=metadata,
                diagnostics=tuple(diagnostics),
                configuration=self.policy.model_dump(mode="json"),
            )
        finally:
            document.close()

    def _validate_payload(self, data: bytes) -> bytes:
        if not isinstance(data, (bytes, bytearray)):
            raise AdapterError("PDF adapter input must be bytes")
        payload = bytes(data)
        if len(payload) > self.policy.max_source_bytes:
            raise AdapterError("PDF source exceeds max_source_bytes")
        if b"%PDF-" not in payload[: self.policy.pdf_header_search_bytes]:
            raise AdapterError("PDF source does not contain a PDF header near the start")
        return payload

    @staticmethod
    def _suspect_native_text_codepoints(text: str | None) -> Counter[str]:
        suspicious: Counter[str] = Counter()
        if not text:
            return suspicious
        for character in text:
            codepoint = ord(character)
            if (
                (codepoint < 0x20 and character not in "\t\n\r")
                or 0x7F <= codepoint <= 0x9F
                or codepoint == 0xFFFD
            ):
                suspicious[f"U+{codepoint:04X}"] += 1
        return suspicious

    @staticmethod
    def _validate_document(
        document: object,
        *,
        diagnostics: list[AdapterDiagnostic],
    ) -> None:
        if not bool(getattr(document, "is_pdf", False)):
            raise AdapterError("native backend did not identify the source as PDF")
        if bool(getattr(document, "needs_pass", False)):
            try:
                authentication = int(document.authenticate(""))  # type: ignore[attr-defined]
            except Exception as exc:
                raise AdapterError(
                    f"password-protected PDF could not be authenticated: {exc}"
                ) from exc
            if authentication <= 0:
                raise AdapterError(
                    "password-protected PDF requires a non-empty password; "
                    "M1 does not accept passwords at the adapter boundary"
                )
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_EMPTY_PASSWORD_AUTHENTICATED",
                    message=(
                        "PDF required authentication but allowed empty-password access; "
                        "permissions are preserved in metadata"
                    ),
                    level=AdapterDiagnosticLevel.INFO,
                )
            )
        page_count = int(getattr(document, "page_count", 0))
        if page_count <= 0:
            raise AdapterError("PDF contains no pages")
        if bool(getattr(document, "is_repaired", False)):
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_REPAIRED_ON_OPEN",
                    message=(
                        "PyMuPDF repaired the PDF while opening it; extracted source "
                        "observations may not represent an intact original object graph"
                    ),
                    affects_structural_completeness=True,
                )
            )

    @staticmethod
    def _create_backend() -> PyMuPdfNativeBackend:
        try:
            return PyMuPdfNativeBackend()
        except PdfBackendError as exc:
            raise AdapterError(str(exc)) from exc
