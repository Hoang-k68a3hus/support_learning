from __future__ import annotations

from pydantic import Field, model_validator

from source_understanding.schemas.document import DocumentMetadata
from source_understanding.schemas.element import RawElement

from ..base import AdapterDiagnostic, SourceAdapterResult
from .adapter import (
    PDF_BLOCK_RECONSTRUCTION_VERSION as _M2_BLOCK_RECONSTRUCTION_VERSION,
    PDF_MEDIA_TYPE as _M2_MEDIA_TYPE,
    PDF_READING_ORDER_VERSION as _M2_READING_ORDER_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION as _M2_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfAdapter as _M2PdfAdapter,
    PdfAdapterPolicy as _M2PdfAdapterPolicy,
)
from .backend import PyMuPdfNativeBackend
from .table_text import PdfTextAlignedTableDetector, PdfTextAlignedTablePolicy
from .tables import PdfRejectedTableObservation, PdfTableDetectionResult


PDF_ADAPTER_VERSION = "4"
PDF_POLICY_VERSION = "5"
PDF_MEDIA_TYPE = _M2_MEDIA_TYPE
PDF_READING_ORDER_VERSION = _M2_READING_ORDER_VERSION
PDF_BLOCK_RECONSTRUCTION_VERSION = _M2_BLOCK_RECONSTRUCTION_VERSION
PDF_TABLE_STRUCTURE_VERSION = "multi-strategy-v2"
PDF_TABLE_TEXT_RECONSTRUCTION_VERSION = _M2_TABLE_TEXT_RECONSTRUCTION_VERSION


class PdfAdapterPolicy(_M2PdfAdapterPolicy):
    """PDF M2.3 policy: strict vector tables plus conservative text alignment."""

    version: str = PDF_POLICY_VERSION
    enable_text_aligned_table_structure: bool = True
    minimum_text_aligned_rows: int = Field(default=3, ge=3, le=1000)
    minimum_text_aligned_columns: int = Field(default=3, ge=3, le=1000)
    text_segment_join_gap_points: float = Field(default=8.0, ge=0.0, le=50.0)
    text_column_alignment_tolerance_points: float = Field(
        default=8.0,
        ge=0.0,
        le=50.0,
    )
    minimum_text_column_gap_points: float = Field(default=12.0, gt=0.0, le=200.0)
    minimum_text_row_gap_ratio: float = Field(default=0.30, ge=0.0, le=10.0)
    maximum_text_row_gap_ratio: float = Field(default=3.0, gt=0.0, le=20.0)
    text_visual_row_overlap_ratio: float = Field(default=0.60, gt=0.0, le=1.0)
    text_operator_lane_ratio: float = Field(default=0.60, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_text_table_spacing(self) -> "PdfAdapterPolicy":
        if self.maximum_text_row_gap_ratio < self.minimum_text_row_gap_ratio:
            raise ValueError(
                "maximum_text_row_gap_ratio must be >= minimum_text_row_gap_ratio"
            )
        return self


class PdfAdapter(_M2PdfAdapter):
    """PDF adapter through M2.3 precision-first native table recall.

    OCR is intentionally absent. The fallback operates only on native TextPage
    spans and is skipped whenever vector geometry already indicates that the page
    belongs to the line-table topology path.
    """

    version = PDF_ADAPTER_VERSION

    def __init__(
        self,
        policy: PdfAdapterPolicy | None = None,
        *,
        backend: PyMuPdfNativeBackend | None = None,
    ) -> None:
        resolved_policy = policy if policy is not None else PdfAdapterPolicy()
        super().__init__(policy=resolved_policy, backend=backend)
        self.policy = resolved_policy
        self._text_table_detector = PdfTextAlignedTableDetector(
            PdfTextAlignedTablePolicy(
                minimum_rows=self.policy.minimum_text_aligned_rows,
                minimum_columns=self.policy.minimum_text_aligned_columns,
                segment_join_gap_points=self.policy.text_segment_join_gap_points,
                column_alignment_tolerance_points=(
                    self.policy.text_column_alignment_tolerance_points
                ),
                minimum_column_gap_points=self.policy.minimum_text_column_gap_points,
                minimum_row_gap_ratio=self.policy.minimum_text_row_gap_ratio,
                maximum_row_gap_ratio=self.policy.maximum_text_row_gap_ratio,
                visual_row_overlap_ratio=self.policy.text_visual_row_overlap_ratio,
                operator_lane_ratio=self.policy.text_operator_lane_ratio,
            )
        )

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        result = super().adapt(data, source_name=source_name)
        raw_elements = tuple(self._upgrade_table_element(item) for item in result.raw_elements)
        metadata = self._upgrade_metadata(result.metadata)
        diagnostics = self._upgrade_diagnostics(result.diagnostics, raw_elements)
        return SourceAdapterResult(
            protocol_version=result.protocol_version,
            adapter_name=result.adapter_name,
            adapter_version=self.version,
            media_type=result.media_type,
            source_name=result.source_name,
            content_hash=result.content_hash,
            raw_elements=raw_elements,
            assets=result.assets,
            metadata=metadata,
            diagnostics=diagnostics,
            configuration=self.policy.model_dump(mode="json"),
        )

    def _detect_tables(
        self,
        page: object,
        observation: object,
        *,
        diagnostics: list[AdapterDiagnostic],
    ) -> PdfTableDetectionResult:
        line_result = super()._detect_tables(
            page,
            observation,
            diagnostics=diagnostics,
        )
        if line_result.tables or line_result.rejected:
            return line_result
        if not self.policy.enable_table_structure:
            return line_result
        if not self.policy.enable_text_aligned_table_structure:
            return line_result

        native_text_blocks = tuple(getattr(observation, "native_text_blocks"))
        if not native_text_blocks:
            return line_result
        page_number = int(getattr(observation, "page_number"))
        try:
            paths = page.get_drawings()  # type: ignore[attr-defined]
        except Exception as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_TABLE_TEXT_FALLBACK_SKIPPED_M2_3",
                    message=(
                        f"PDF page {page_number} native-text table fallback was skipped "
                        "because vector-geometry ownership could not be inspected safely"
                    ),
                    affects_structural_completeness=True,
                    part=f"page:{page_number}",
                    metadata={
                        "page": page_number,
                        "error_type": type(exc).__name__,
                    },
                )
            )
            return line_result

        if PdfTextAlignedTableDetector.has_rectilinear_vector_evidence(paths):
            return PdfTableDetectionResult(
                rejected=(
                    PdfRejectedTableObservation(
                        table_index=0,
                        reason="rectilinear_evidence_no_strict_candidate",
                        detail=(
                            "text-aligned fallback suppressed because vector geometry "
                            "belongs to the line-table topology path"
                        ),
                    ),
                )
            )

        try:
            return self._text_table_detector.detect(
                page,
                native_text_blocks,
            )
        except Exception as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_TABLE_TEXT_ALIGNMENT_FAILED_M2_3",
                    message=(
                        f"PDF page {page_number} native-text table detection failed "
                        "safely; original M1 text blocks are preserved"
                    ),
                    affects_structural_completeness=True,
                    part=f"page:{page_number}",
                    metadata={
                        "page": page_number,
                        "error_type": type(exc).__name__,
                    },
                )
            )
            return line_result

    @staticmethod
    def _upgrade_table_element(element: RawElement) -> RawElement:
        if element.type_hint not in {"TABLE", "TABLE_ROW", "TABLE_CELL"}:
            return element
        payload = element.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        attributes["pdf_table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        strategy = attributes.get("pdf_table_detection_strategy")
        if strategy == "text_aligned":
            attributes["integrity_evidence"] = "pdf_text_alignment"
        payload["attributes"] = attributes
        provenance = dict(payload["provenance"])
        provenance_metadata = dict(provenance.get("metadata", {}))
        provenance_metadata["table_detection"] = PDF_TABLE_STRUCTURE_VERSION
        provenance["metadata"] = provenance_metadata
        payload["provenance"] = provenance
        return RawElement.model_validate(payload)

    @staticmethod
    def _upgrade_metadata(metadata: DocumentMetadata) -> DocumentMetadata:
        payload = metadata.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        pdf = dict(attributes.get("pdf", {}))
        pdf["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        pdf["table_detection_strategies"] = ["lines_strict", "text_aligned"]
        pdf["ocr_table_extraction"] = "deferred_optional_extension"
        attributes["pdf"] = pdf
        payload["attributes"] = attributes
        return DocumentMetadata.model_validate(payload)

    @staticmethod
    def _upgrade_diagnostics(
        diagnostics: tuple[AdapterDiagnostic, ...],
        raw_elements: tuple[RawElement, ...],
    ) -> tuple[AdapterDiagnostic, ...]:
        strategies_by_page: dict[int, list[str]] = {}
        for element in raw_elements:
            if element.type_hint != "TABLE" or element.location is None:
                continue
            page = element.location.page
            strategy = element.attributes.get("pdf_table_detection_strategy")
            if page is None or not isinstance(strategy, str):
                continue
            strategies_by_page.setdefault(page, []).append(strategy)

        output: list[AdapterDiagnostic] = []
        for diagnostic in diagnostics:
            payload = diagnostic.model_dump(mode="python")
            metadata = dict(payload["metadata"])
            page = metadata.get("page")
            if diagnostic.code == "PDF_TABLE_STRUCTURE_EXTRACTED_M2":
                payload["message"] = (
                    f"PDF page {page} contains high-confidence native table structure. "
                    "M2.3 emits TABLE/TABLE_ROW/TABLE_CELL while preserving exact source "
                    "span provenance; OCR is not involved"
                )
                metadata["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
                if isinstance(page, int):
                    metadata["detection_strategies"] = sorted(
                        set(strategies_by_page.get(page, ()))
                    )
            elif diagnostic.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2":
                payload["message"] = (
                    f"PDF page {page} contains table-like evidence that M2.3 cannot "
                    "project with high confidence. Original native text blocks are "
                    "preserved instead"
                )
                reason_counts = metadata.get("reason_counts")
                if isinstance(reason_counts, dict):
                    metadata["failure_classes"] = dict(sorted(reason_counts.items()))
            payload["metadata"] = metadata
            output.append(AdapterDiagnostic.model_validate(payload))
        return tuple(output)
