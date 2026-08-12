from __future__ import annotations

from collections import Counter
from dataclasses import replace

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
from .order_v3 import PdfReadingOrderPolicyV3, PdfReadingOrderResolverV3
from .table_emit import PdfTableRawElementEmitter
from .tables import (
    PDF_TABLE_STRUCTURE_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfTableDetectionError,
    PdfTableDetectionResult,
    PdfTableDetector,
    PdfTablePolicy,
)
from .visibility import PdfVisibilityPolicy, PdfVisibilityResolver


PDF_ADAPTER_VERSION = "3"
PDF_POLICY_VERSION = "4"
PDF_MEDIA_TYPE = "application/pdf"
PDF_READING_ORDER_VERSION = "geometric-columns-v3"
PDF_BLOCK_RECONSTRUCTION_VERSION = "textpage-block-v1"


class PdfAdapterPolicy(SchemaModel):
    """Deterministic PDF policy through M2 line-bordered table structure."""

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
    minimum_column_width_balance_ratio: float = Field(default=0.35, ge=0.0, le=1.0)
    minimum_column_block_count: int = Field(default=2, ge=2, le=100)
    minimum_trace_overlap_ratio: float = Field(default=0.50, gt=0.0, le=1.0)
    minimum_occlusion_coverage_ratio: float = Field(default=0.95, gt=0.0, le=1.0)
    minimum_fill_opacity: float = Field(default=0.98, ge=0.0, le=1.0)
    bbox_tolerance_points: float = Field(default=1.0, ge=0.0, le=10.0)
    preserve_span_metadata: bool = True

    enable_table_structure: bool = True
    minimum_table_rows: int = Field(default=2, ge=2, le=1000)
    minimum_table_columns: int = Field(default=2, ge=2, le=1000)
    minimum_table_cells: int = Field(default=6, ge=4, le=100_000)
    minimum_populated_table_rows: int = Field(default=2, ge=1, le=1000)
    minimum_populated_table_columns: int = Field(default=2, ge=1, le=1000)
    minimum_populated_table_cells: int = Field(default=4, ge=1, le=100_000)
    minimum_span_cell_overlap_ratio: float = Field(default=0.50, gt=0.0, le=1.0)
    table_visual_line_overlap_ratio: float = Field(default=0.60, gt=0.0, le=1.0)
    table_topology_tolerance_points: float = Field(default=3.0, ge=0.0, le=20.0)


class PdfAdapter:
    """Preserve visible PDF facts and add only high-confidence structural projections."""

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
        self._order_resolver = PdfReadingOrderResolverV3(
            PdfReadingOrderPolicyV3(
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
                minimum_column_width_balance_ratio=(
                    self.policy.minimum_column_width_balance_ratio
                ),
                minimum_column_block_count=self.policy.minimum_column_block_count,
            )
        )
        self._visibility_resolver = PdfVisibilityResolver(
            PdfVisibilityPolicy(
                minimum_trace_overlap_ratio=self.policy.minimum_trace_overlap_ratio,
                minimum_occlusion_coverage_ratio=(
                    self.policy.minimum_occlusion_coverage_ratio
                ),
                minimum_fill_opacity=self.policy.minimum_fill_opacity,
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
        self._table_detector = PdfTableDetector(
            PdfTablePolicy(
                minimum_rows=self.policy.minimum_table_rows,
                minimum_columns=self.policy.minimum_table_columns,
                minimum_cells=self.policy.minimum_table_cells,
                minimum_populated_rows=self.policy.minimum_populated_table_rows,
                minimum_populated_columns=(
                    self.policy.minimum_populated_table_columns
                ),
                minimum_populated_cells=self.policy.minimum_populated_table_cells,
                minimum_span_cell_overlap_ratio=(
                    self.policy.minimum_span_cell_overlap_ratio
                ),
                visual_line_overlap_ratio=self.policy.table_visual_line_overlap_ratio,
                topology_tolerance_points=self.policy.table_topology_tolerance_points,
            )
        )
        self._table_emitter = PdfTableRawElementEmitter(
            adapter_name=self.name,
            adapter_version=self.version,
            base_emitter=self._emitter,
            reading_order_version=PDF_READING_ORDER_VERSION,
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
            pages_with_occluded_text = 0
            pages_with_extracted_tables = 0
            extracted_table_count = 0

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

                visible_blocks, occluded_blocks = self._visibility_resolver.partition(
                    page,
                    observation.native_text_blocks,
                )
                if occluded_blocks:
                    pages_with_occluded_text += 1
                    observation = replace(
                        observation,
                        native_text_blocks=visible_blocks,
                        occluded_text_blocks=occluded_blocks,
                    )
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_OCCLUDED_TEXT_EXCLUDED_M1",
                            message=(
                                f"PDF page {observation.page_number} contains native text "
                                "objects that are fully covered by later opaque paint. M1 "
                                "keeps the source audit metadata but excludes those objects "
                                "from visible RawElement text"
                            ),
                            level=AdapterDiagnosticLevel.INFO,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "occluded_block_count": len(occluded_blocks),
                                "native_block_numbers": [
                                    item.native_block_number for item in occluded_blocks
                                ],
                                "coverage_ratios": [
                                    item.coverage_ratio for item in occluded_blocks
                                ],
                            },
                        )
                    )

                table_detection = self._detect_tables(
                    page,
                    observation,
                    diagnostics=diagnostics,
                )
                if table_detection.rejected:
                    reason_counts = Counter(
                        item.reason for item in table_detection.rejected
                    )
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_TABLE_CANDIDATE_UNSUPPORTED_M2",
                            message=(
                                f"PDF page {observation.page_number} contains vector-grid "
                                "table candidates that M2 cannot bind to a simple rectangular "
                                "source-span topology with high confidence. Original native "
                                "text blocks are preserved instead"
                            ),
                            affects_structural_completeness=True,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "rejected_candidate_count": len(
                                    table_detection.rejected
                                ),
                                "reason_counts": dict(sorted(reason_counts.items())),
                                "candidates": [
                                    {
                                        "table_index": item.table_index,
                                        "reason": item.reason,
                                        "bbox_points": (
                                            list(item.bbox)
                                            if item.bbox is not None
                                            else None
                                        ),
                                        "row_count": item.row_count,
                                        "column_count": item.column_count,
                                        "detail": item.detail,
                                    }
                                    for item in table_detection.rejected
                                ],
                            },
                        )
                    )

                table_structure_element_count = 0
                if table_detection.tables:
                    pages_with_extracted_tables += 1
                    extracted_table_count += len(table_detection.tables)
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_TABLE_STRUCTURE_EXTRACTED_M2",
                            message=(
                                f"PDF page {observation.page_number} contains "
                                f"{len(table_detection.tables)} high-confidence line-bordered "
                                "table(s). M2 emits TABLE/TABLE_ROW/TABLE_CELL structure and "
                                "preserves the owning source spans in cell audit metadata"
                            ),
                            level=AdapterDiagnosticLevel.INFO,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "table_structure_version": PDF_TABLE_STRUCTURE_VERSION,
                                "table_count": len(table_detection.tables),
                                "tables": [
                                    {
                                        "table_index": item.table_index,
                                        "row_count": item.row_count,
                                        "column_count": item.column_count,
                                        "source_native_orders": list(
                                            item.source_native_orders
                                        ),
                                    }
                                    for item in table_detection.tables
                                ],
                            },
                        )
                    )

                suspect_codepoints, suspect_block_count = self._source_text_suspicions(
                    observation
                )

                if table_detection.tables:
                    emitted_on_page, table_structure_element_count = (
                        self._emit_page_with_tables(
                            observation,
                            table_detection,
                            raw_elements=raw_elements,
                            backend=backend,
                        )
                    )
                    consumed_orders = {
                        order
                        for table in table_detection.tables
                        for order in table.source_native_orders
                    }
                    residual_blocks = tuple(
                        block
                        for block in observation.native_text_blocks
                        if block.native_order not in consumed_orders
                    )
                    if self._order_resolver.looks_aligned_layout(
                        residual_blocks,
                        page_width=observation.width_points,
                    ):
                        diagnostics.append(
                            AdapterDiagnostic(
                                code="PDF_ALIGNED_LAYOUT_REMAINS_UNSTRUCTURED_M2",
                                message=(
                                    f"PDF page {observation.page_number} contains additional "
                                    "row-aligned geometry outside accepted M2 tables. The "
                                    "remaining native blocks preserve source order rather than "
                                    "being forced into table structure"
                                ),
                                affects_structural_completeness=True,
                                part=f"page:{observation.page_number}",
                                metadata={
                                    "page": observation.page_number,
                                    "residual_native_text_block_count": len(
                                        residual_blocks
                                    ),
                                    "reading_order_action": "preserve_native_order",
                                },
                            )
                        )
                else:
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
                                    "form, equation array, or table-like layout. M2 found no "
                                    "high-confidence supported table, so native block order is "
                                    "preserved and rows/cells are not invented"
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
                    emitted_on_page = self._emit_ordered_blocks(
                        ordered,
                        page=observation,
                        raw_elements=raw_elements,
                        backend=backend,
                    )

                if emitted_on_page:
                    pages_with_native_text += 1
                else:
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="PDF_PAGE_NO_NATIVE_TEXT",
                            message=(
                                f"PDF page {observation.page_number} produced no visible "
                                "native text blocks; OCR is intentionally outside M2"
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
                                "is preserved unchanged and OCR is intentionally outside M2"
                            ),
                            affects_structural_completeness=True,
                            part=f"page:{observation.page_number}",
                            metadata={
                                "page": observation.page_number,
                                "affected_block_count": suspect_block_count,
                                "codepoint_counts": dict(
                                    sorted(suspect_codepoints.items())
                                ),
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
                                "M2 preserves native text/table structure only and does not "
                                "claim image content"
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
                        extracted_table_count=len(table_detection.tables),
                        emitted_table_structure_element_count=(
                            table_structure_element_count
                        ),
                    )
                )

            metadata = self._metadata_builder.build(
                document=document,
                backend=backend,
                source_name=source_name,
                page_metadata=page_metadata,
                pages_with_native_text=pages_with_native_text,
                pages_with_images=pages_with_images,
                pages_with_occluded_text=pages_with_occluded_text,
                pages_with_extracted_tables=pages_with_extracted_tables,
                extracted_table_count=extracted_table_count,
                diagnostics=diagnostics,
                reading_order_version=PDF_READING_ORDER_VERSION,
                block_reconstruction_version=PDF_BLOCK_RECONSTRUCTION_VERSION,
                table_structure_version=PDF_TABLE_STRUCTURE_VERSION,
                table_text_reconstruction_version=(
                    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION
                ),
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

    def _detect_tables(
        self,
        page: object,
        observation: object,
        *,
        diagnostics: list[AdapterDiagnostic],
    ) -> PdfTableDetectionResult:
        if not self.policy.enable_table_structure:
            return PdfTableDetectionResult()
        native_text_blocks = getattr(observation, "native_text_blocks")
        page_number = int(getattr(observation, "page_number"))
        try:
            return self._table_detector.detect(page, native_text_blocks)
        except PdfTableDetectionError as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_TABLE_DETECTION_FAILED_M2",
                    message=(
                        f"PDF page {page_number} table detection failed safely; original "
                        f"native text blocks are preserved: {exc}"
                    ),
                    affects_structural_completeness=True,
                    part=f"page:{page_number}",
                    metadata={
                        "page": page_number,
                        "error_type": type(exc).__name__,
                    },
                )
            )
            return PdfTableDetectionResult()

    def _source_text_suspicions(
        self,
        observation,
    ) -> tuple[Counter[str], int]:
        suspect_codepoints: Counter[str] = Counter()
        suspect_block_count = 0
        for block in observation.native_text_blocks:
            text, _lines, _spans, _offsets = self._emitter.reconstruct_block(
                block,
                page=observation,
            )
            suspicions = self._suspect_native_text_codepoints(text)
            if suspicions:
                suspect_block_count += 1
                suspect_codepoints.update(suspicions)
        return suspect_codepoints, suspect_block_count

    def _emit_ordered_blocks(
        self,
        ordered,
        *,
        page,
        raw_elements: list[RawElement],
        backend: object,
    ) -> int:
        emitted = 0
        for reading_index, block in enumerate(ordered):
            raw = self._emitter.emit(
                block,
                page=page,
                reading_index=reading_index,
                global_order=len(raw_elements),
                backend=backend,
            )
            if raw is not None:
                raw_elements.append(raw)
                emitted += 1
        return emitted

    def _emit_page_with_tables(
        self,
        page,
        detection: PdfTableDetectionResult,
        *,
        raw_elements: list[RawElement],
        backend: object,
    ) -> tuple[int, int]:
        consumed_orders = {
            order
            for table in detection.tables
            for order in table.source_native_orders
        }
        table_by_first_order = {
            table.source_native_orders[0]: table for table in detection.tables
        }
        emitted = 0
        table_structure_elements = 0
        reading_index = 0
        for block in page.native_text_blocks:
            table = table_by_first_order.get(block.native_order)
            if table is not None:
                projected = self._table_emitter.emit(
                    table,
                    page=page,
                    global_order=len(raw_elements),
                    reading_index=reading_index,
                    backend=backend,
                )
                raw_elements.extend(projected)
                emitted += len(projected)
                table_structure_elements += len(projected)
                reading_index += 1
                continue
            if block.native_order in consumed_orders:
                continue
            raw = self._emitter.emit(
                block,
                page=page,
                reading_index=reading_index,
                global_order=len(raw_elements),
                backend=backend,
            )
            reading_index += 1
            if raw is not None:
                raw_elements.append(raw)
                emitted += 1
        return emitted, table_structure_elements

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
                    "M2 does not accept passwords at the adapter boundary"
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
