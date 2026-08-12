from __future__ import annotations

from pydantic import Field, model_validator

from source_understanding.schemas.document import DocumentMetadata
from source_understanding.schemas.element import RawElement

from ..base import AdapterDiagnostic, SourceAdapterResult
from .adapter_m24 import (
    PDF_BLOCK_RECONSTRUCTION_VERSION as _M24_BLOCK_RECONSTRUCTION_VERSION,
    PDF_MEDIA_TYPE as _M24_MEDIA_TYPE,
    PDF_MERGED_TABLE_TOPOLOGY_VERSION as _M24_MERGED_TABLE_TOPOLOGY_VERSION,
    PDF_READING_ORDER_VERSION as _M24_READING_ORDER_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION as _M24_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfAdapter as _M24PdfAdapter,
    PdfAdapterPolicy as _M24PdfAdapterPolicy,
)
from .backend import PyMuPdfNativeBackend
from .table_regions import (
    PDF_SEGMENTED_LINES_MERGED_TABLE_STRATEGY,
    PDF_SEGMENTED_LINES_TABLE_STRATEGY,
    PDF_SEGMENTED_STRICT_MERGED_TABLE_STRATEGY,
    PDF_SEGMENTED_STRICT_TABLE_STRATEGY,
    PdfSegmentedTableDetector,
)
from .tables import PdfTableDetectionResult


PDF_ADAPTER_VERSION = "6"
PDF_POLICY_VERSION = "7"
PDF_MEDIA_TYPE = _M24_MEDIA_TYPE
PDF_READING_ORDER_VERSION = _M24_READING_ORDER_VERSION
PDF_BLOCK_RECONSTRUCTION_VERSION = _M24_BLOCK_RECONSTRUCTION_VERSION
PDF_TABLE_STRUCTURE_VERSION = "multi-strategy-v4"
PDF_TABLE_TEXT_RECONSTRUCTION_VERSION = _M24_TABLE_TEXT_RECONSTRUCTION_VERSION
PDF_MERGED_TABLE_TOPOLOGY_VERSION = _M24_MERGED_TABLE_TOPOLOGY_VERSION
PDF_MULTI_TABLE_SEGMENTATION_VERSION = "drawing-clusters-v1"

_SEGMENTED_RETRY_REASON = "rectilinear_evidence_no_strict_candidate"
_SEGMENTED_STRATEGIES = frozenset(
    {
        PDF_SEGMENTED_STRICT_TABLE_STRATEGY,
        PDF_SEGMENTED_LINES_TABLE_STRATEGY,
        PDF_SEGMENTED_STRICT_MERGED_TABLE_STRATEGY,
        PDF_SEGMENTED_LINES_MERGED_TABLE_STRATEGY,
    }
)


class PdfAdapterPolicy(_M24PdfAdapterPolicy):
    """PDF M2.5 policy: add precision-first multi-table vector segmentation."""

    version: str = PDF_POLICY_VERSION
    enable_segmented_multi_table_structure: bool = True
    minimum_segmented_table_regions: int = Field(default=2, ge=2, le=16)
    maximum_segmented_table_regions: int = Field(default=16, ge=2, le=64)
    segmented_table_cluster_tolerance_points: float = Field(
        default=3.0,
        ge=0.0,
        le=20.0,
    )
    segmented_table_boundary_support_ratio: float = Field(
        default=0.75,
        gt=0.0,
        le=1.0,
    )
    segmented_table_vector_alignment_tolerance_points: float = Field(
        default=0.75,
        ge=0.0,
        le=5.0,
    )
    segmented_table_active_vertical_boundary_fraction: float = Field(
        default=0.40,
        gt=0.0,
        le=1.0,
    )
    segmented_table_minimum_active_vertical_boundaries: int = Field(
        default=3,
        ge=2,
        le=64,
    )

    @model_validator(mode="after")
    def validate_segmented_table_limits(self) -> "PdfAdapterPolicy":
        if self.maximum_segmented_table_regions < self.minimum_segmented_table_regions:
            raise ValueError(
                "maximum_segmented_table_regions must be >= minimum_segmented_table_regions"
            )
        return self


class PdfAdapter(_M24PdfAdapter):
    """PDF adapter through M2.5 multiple ruled-table region segmentation.

    M2.5 does not relax source ownership or topology checks. It only retries the
    specific case where page-level rectilinear evidence exists but `lines_strict`
    exposes no candidate, and it requires multiple disconnected vector regions to
    independently survive source-vector grid normalization plus the existing table
    verifier.
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
        self._segmented_table_detector = PdfSegmentedTableDetector(
            self._table_detector.policy,
            cluster_tolerance_points=(
                self.policy.segmented_table_cluster_tolerance_points
            ),
            minimum_regions=self.policy.minimum_segmented_table_regions,
            maximum_regions=self.policy.maximum_segmented_table_regions,
            boundary_support_ratio=(
                self.policy.segmented_table_boundary_support_ratio
            ),
            vector_alignment_tolerance_points=(
                self.policy.segmented_table_vector_alignment_tolerance_points
            ),
            active_vertical_boundary_fraction=(
                self.policy.segmented_table_active_vertical_boundary_fraction
            ),
            minimum_active_vertical_boundaries=(
                self.policy.segmented_table_minimum_active_vertical_boundaries
            ),
        )

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        result = super().adapt(data, source_name=source_name)
        return SourceAdapterResult(
            protocol_version=result.protocol_version,
            adapter_name=result.adapter_name,
            adapter_version=self.version,
            media_type=result.media_type,
            source_name=result.source_name,
            content_hash=result.content_hash,
            raw_elements=result.raw_elements,
            assets=result.assets,
            metadata=result.metadata,
            diagnostics=result.diagnostics,
            configuration=self.policy.model_dump(mode="json"),
        )

    def _detect_tables(
        self,
        page: object,
        observation: object,
        *,
        diagnostics: list[AdapterDiagnostic],
    ) -> PdfTableDetectionResult:
        base_result = super()._detect_tables(
            page,
            observation,
            diagnostics=diagnostics,
        )
        if base_result.tables:
            return base_result
        if not self.policy.enable_table_structure:
            return base_result
        if not self.policy.enable_segmented_multi_table_structure:
            return base_result
        if not any(
            item.reason == _SEGMENTED_RETRY_REASON for item in base_result.rejected
        ):
            return base_result

        native_text_blocks = tuple(getattr(observation, "native_text_blocks"))
        if not native_text_blocks:
            return base_result
        page_number = int(getattr(observation, "page_number"))
        try:
            segmented = self._segmented_table_detector.detect(
                page,
                native_text_blocks,
            )
        except Exception as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_TABLE_SEGMENTATION_FAILED_M2_5",
                    message=(
                        f"PDF page {page_number} multi-table vector segmentation failed "
                        "safely; original native text blocks are preserved"
                    ),
                    affects_structural_completeness=True,
                    part=f"page:{page_number}",
                    metadata={
                        "page": page_number,
                        "error_type": type(exc).__name__,
                    },
                )
            )
            return base_result

        if not segmented.tables:
            retained = tuple(
                item
                for item in base_result.rejected
                if item.reason != _SEGMENTED_RETRY_REASON
            )
            return PdfTableDetectionResult(
                tables=base_result.tables,
                rejected=retained + segmented.rejected,
            )

        retained = tuple(
            item
            for item in base_result.rejected
            if item.reason != _SEGMENTED_RETRY_REASON
        )
        return PdfTableDetectionResult(
            tables=segmented.tables,
            rejected=retained + segmented.rejected,
        )

    @staticmethod
    def _upgrade_table_element(element: RawElement) -> RawElement:
        upgraded = _M24PdfAdapter._upgrade_table_element(element)
        if upgraded.type_hint not in {"TABLE", "TABLE_ROW", "TABLE_CELL"}:
            return upgraded
        payload = upgraded.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        attributes["pdf_table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        strategy = attributes.get("pdf_table_detection_strategy")
        if strategy in _SEGMENTED_STRATEGIES:
            attributes["integrity_evidence"] = "pdf_segmented_rectilinear_geometry"
            attributes["pdf_multi_table_segmentation_version"] = (
                PDF_MULTI_TABLE_SEGMENTATION_VERSION
            )
        payload["attributes"] = attributes
        provenance = dict(payload["provenance"])
        provenance_metadata = dict(provenance.get("metadata", {}))
        provenance_metadata["table_detection"] = PDF_TABLE_STRUCTURE_VERSION
        if strategy in _SEGMENTED_STRATEGIES:
            provenance_metadata["multi_table_segmentation"] = (
                PDF_MULTI_TABLE_SEGMENTATION_VERSION
            )
        provenance["metadata"] = provenance_metadata
        payload["provenance"] = provenance
        return RawElement.model_validate(payload)

    @staticmethod
    def _upgrade_metadata(metadata: DocumentMetadata) -> DocumentMetadata:
        upgraded = _M24PdfAdapter._upgrade_metadata(metadata)
        payload = upgraded.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        pdf = dict(attributes.get("pdf", {}))
        pdf["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        pdf["multi_table_segmentation_version"] = PDF_MULTI_TABLE_SEGMENTATION_VERSION
        pdf["table_detection_strategies"] = [
            "lines_strict",
            "lines_strict_merged",
            "text_aligned",
            PDF_SEGMENTED_STRICT_TABLE_STRATEGY,
            PDF_SEGMENTED_LINES_TABLE_STRATEGY,
            PDF_SEGMENTED_STRICT_MERGED_TABLE_STRATEGY,
            PDF_SEGMENTED_LINES_MERGED_TABLE_STRATEGY,
        ]
        pdf["ocr_table_extraction"] = "deferred_optional_extension"
        attributes["pdf"] = pdf
        payload["attributes"] = attributes
        return DocumentMetadata.model_validate(payload)

    @staticmethod
    def _upgrade_diagnostics(
        diagnostics: tuple[AdapterDiagnostic, ...],
        raw_elements: tuple[RawElement, ...],
    ) -> tuple[AdapterDiagnostic, ...]:
        upgraded = _M24PdfAdapter._upgrade_diagnostics(diagnostics, raw_elements)
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
        for diagnostic in upgraded:
            payload = diagnostic.model_dump(mode="python")
            metadata = dict(payload["metadata"])
            page = metadata.get("page")
            if diagnostic.code == "PDF_TABLE_STRUCTURE_EXTRACTED_M2":
                payload["message"] = (
                    f"PDF page {page} contains high-confidence native table structure. "
                    "M2.5 supports simple, rectangular merged, conservative text-aligned, "
                    "and disconnected multi-table vector regions while preserving exact "
                    "source-span provenance; OCR is not involved"
                )
                metadata["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
                if isinstance(page, int):
                    metadata["detection_strategies"] = sorted(
                        set(strategies_by_page.get(page, ()))
                    )
            elif diagnostic.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2":
                payload["message"] = (
                    f"PDF page {page} contains table-like evidence that M2.5 cannot "
                    "project without inventing topology or source ownership. Original "
                    "native text blocks are preserved instead"
                )
            payload["metadata"] = metadata
            output.append(AdapterDiagnostic.model_validate(payload))
        return tuple(output)
