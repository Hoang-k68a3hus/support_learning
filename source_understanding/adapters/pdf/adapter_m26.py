from __future__ import annotations

from pydantic import Field

from source_understanding.schemas.document import DocumentMetadata
from source_understanding.schemas.element import RawElement
from source_understanding.source_attributes import SOURCE_ANCHOR_ATTRIBUTE

from ..base import AdapterDiagnostic, AdapterError, SourceAdapterResult
from .adapter_m25 import (
    PDF_BLOCK_RECONSTRUCTION_VERSION as _M25_BLOCK_RECONSTRUCTION_VERSION,
    PDF_MEDIA_TYPE as _M25_MEDIA_TYPE,
    PDF_MERGED_TABLE_TOPOLOGY_VERSION as _M25_MERGED_TABLE_TOPOLOGY_VERSION,
    PDF_MULTI_TABLE_SEGMENTATION_VERSION as _M25_MULTI_TABLE_SEGMENTATION_VERSION,
    PDF_READING_ORDER_VERSION as _M25_READING_ORDER_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION as _M25_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfAdapter as _M25PdfAdapter,
    PdfAdapterPolicy as _M25PdfAdapterPolicy,
)
from .backend import PyMuPdfNativeBackend
from .models import PdfBlockLinePartition, PdfBlockObservation
from .source_partition import PDF_SOURCE_LINE_PARTITION_VERSION, PdfSourcePartitionError
from .table_boundary import (
    PdfBoundaryPartitionedTableDetector,
    PdfBoundaryPartitionedTableObservation,
)
from .tables import PdfTableDetectionResult


PDF_ADAPTER_VERSION = "7"
PDF_POLICY_VERSION = "8"
PDF_MEDIA_TYPE = _M25_MEDIA_TYPE
PDF_READING_ORDER_VERSION = _M25_READING_ORDER_VERSION
PDF_BLOCK_RECONSTRUCTION_VERSION = _M25_BLOCK_RECONSTRUCTION_VERSION
PDF_TABLE_STRUCTURE_VERSION = "multi-strategy-v5"
PDF_TABLE_TEXT_RECONSTRUCTION_VERSION = _M25_TABLE_TEXT_RECONSTRUCTION_VERSION
PDF_MERGED_TABLE_TOPOLOGY_VERSION = _M25_MERGED_TABLE_TOPOLOGY_VERSION
PDF_MULTI_TABLE_SEGMENTATION_VERSION = _M25_MULTI_TABLE_SEGMENTATION_VERSION
PDF_SOURCE_BLOCK_PARTITION_VERSION = PDF_SOURCE_LINE_PARTITION_VERSION
PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION = "outer-whitespace-strip-v1"

_BOUNDARY_RETRY_REASON = "merged_source_block_crosses_table_boundary"


class PdfAdapterPolicy(_M25PdfAdapterPolicy):
    """PDF M2.6 policy: exact native-line prefix partition for crossing blocks."""

    version: str = PDF_POLICY_VERSION
    enable_boundary_safe_source_partitioning: bool = True
    boundary_partition_geometry_tolerance_points: float = Field(
        default=0.75,
        ge=0.0,
        le=5.0,
    )
    maximum_boundary_partitioned_blocks_per_table: int = Field(
        default=2,
        ge=1,
        le=8,
    )


class PdfAdapter(_M25PdfAdapter):
    """PDF adapter through M2.6 boundary-safe native source ownership.

    M2.6 never splits characters, words, spans, or native lines. It retries only
    merged ruled-table candidates whose crossing source block has a contiguous
    table-line prefix followed by a residual suffix. The original source block
    remains immutable; a private table-only detection view is used and the exact
    untouched residual suffix is emitted after the verified table.
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
        self._boundary_table_detector = PdfBoundaryPartitionedTableDetector(
            self._table_detector.policy,
            geometry_tolerance_points=(
                self.policy.boundary_partition_geometry_tolerance_points
            ),
            maximum_partitioned_blocks_per_table=(
                self.policy.maximum_boundary_partitioned_blocks_per_table
            ),
        )

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        result = super().adapt(data, source_name=source_name)
        raw_elements = tuple(
            self._upgrade_m26_element(item) for item in result.raw_elements
        )
        metadata = self._upgrade_m26_metadata(result.metadata)
        diagnostics = self._upgrade_m26_diagnostics(
            result.diagnostics,
            raw_elements,
        )
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
        base_result = super()._detect_tables(
            page,
            observation,
            diagnostics=diagnostics,
        )
        if not self.policy.enable_table_structure:
            return base_result
        if not self.policy.enable_merged_table_structure:
            return base_result
        if not self.policy.enable_boundary_safe_source_partitioning:
            return base_result

        retry_indexes = frozenset(
            item.table_index
            for item in base_result.rejected
            if item.reason == _BOUNDARY_RETRY_REASON
        )
        if not retry_indexes:
            return base_result

        native_text_blocks = tuple(getattr(observation, "native_text_blocks"))
        if not native_text_blocks:
            return base_result
        page_number = int(getattr(observation, "page_number"))
        reserved = frozenset(
            order
            for table in base_result.tables
            for order in table.source_native_orders
        )
        try:
            retry = self._boundary_table_detector.detect(
                page,
                native_text_blocks,
                candidate_indexes=retry_indexes,
                reserved_source_orders=reserved,
            )
        except Exception as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_TABLE_SOURCE_PARTITION_FAILED_M2_6",
                    message=(
                        f"PDF page {page_number} native-line table ownership retry failed "
                        "safely; original native text blocks remain authoritative"
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

        accepted_indexes = {item.table_index for item in retry.tables}
        if not accepted_indexes:
            if not retry.rejected:
                return base_result
            retained = tuple(
                item
                for item in base_result.rejected
                if item.table_index not in retry_indexes
            )
            return PdfTableDetectionResult(
                tables=base_result.tables,
                rejected=retained + retry.rejected,
            )

        tables = tuple(
            sorted(
                (*base_result.tables, *retry.tables),
                key=lambda item: item.source_native_orders[0],
            )
        )
        rejected = tuple(
            item
            for item in base_result.rejected
            if item.table_index not in accepted_indexes
        ) + tuple(
            item
            for item in retry.rejected
            if item.table_index not in accepted_indexes
        )
        return PdfTableDetectionResult(tables=tables, rejected=rejected)

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
        partition_by_order: dict[
            int,
            tuple[PdfBlockLinePartition, PdfBoundaryPartitionedTableObservation],
        ] = {}
        for table in detection.tables:
            if not isinstance(table, PdfBoundaryPartitionedTableObservation):
                continue
            for partition in table.source_block_line_partitions:
                if partition.native_order in partition_by_order:
                    raise AdapterError(
                        "M2.6 source partition assigns one native block to multiple tables"
                    )
                partition_by_order[partition.native_order] = (partition, table)

        original_by_order = {
            block.native_order: block for block in page.native_text_blocks
        }
        residual_by_order: dict[int, PdfBlockObservation] = {}
        for native_order, (partition, owner_table) in partition_by_order.items():
            original = original_by_order.get(native_order)
            if original is None:
                raise AdapterError(
                    "M2.6 source partition references a missing native block"
                )
            try:
                residual = self._boundary_table_detector.partitioner.residual_fragment(
                    original,
                    partition,
                )
            except PdfSourcePartitionError as exc:
                raise AdapterError(
                    f"M2.6 residual source partition invariant failed: {exc.reason}"
                ) from exc
            self._validate_partition_span_conservation(
                table=owner_table,
                original=original,
                residual=residual,
                partition=partition,
            )
            residual_by_order[native_order] = residual

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
                if isinstance(table, PdfBoundaryPartitionedTableObservation):
                    projected = self._annotate_partitioned_table_projection(
                        projected,
                        table,
                    )
                raw_elements.extend(projected)
                emitted += len(projected)
                table_structure_elements += len(projected)
                reading_index += 1

            if block.native_order in consumed_orders:
                residual = residual_by_order.get(block.native_order)
                if residual is not None:
                    raw = self._emitter.emit(
                        residual,
                        page=page,
                        reading_index=reading_index,
                        global_order=len(raw_elements),
                        backend=backend,
                    )
                    reading_index += 1
                    if raw is None:
                        raise AdapterError(
                            "M2.6 verified residual source fragment became empty at emission"
                        )
                    partition, owner_table = partition_by_order[block.native_order]
                    raw_elements.append(
                        self._annotate_residual_fragment(
                            raw,
                            partition=partition,
                            owner_table=owner_table,
                        )
                    )
                    emitted += 1
                continue

            if table is not None:
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

    @staticmethod
    def _validate_partition_span_conservation(
        *,
        table: PdfBoundaryPartitionedTableObservation,
        original: PdfBlockObservation,
        residual: PdfBlockObservation,
        partition: PdfBlockLinePartition,
    ) -> None:
        original_span_orders = {
            span.native_order
            for line in original.lines
            for span in line.spans
            if span.text
        }
        table_span_orders = {
            fragment.span.native_order
            for row in table.rows
            for cell in row.cells
            for fragment in cell.fragments
            if fragment.block_native_order == partition.native_order
            and fragment.span.text
        }
        residual_span_orders = {
            span.native_order
            for line in residual.lines
            for span in line.spans
            if span.text
        }
        overlap = table_span_orders.intersection(residual_span_orders)
        if overlap:
            raise AdapterError(
                "M2.6 table and residual source spans overlap: "
                f"{sorted(overlap)}"
            )
        combined = table_span_orders.union(residual_span_orders)
        if combined != original_span_orders:
            missing = sorted(original_span_orders - combined)
            extra = sorted(combined - original_span_orders)
            raise AdapterError(
                "M2.6 table/residual source span conservation failed: "
                f"missing={missing};extra={extra}"
            )

    @staticmethod
    def _annotate_partitioned_table_projection(
        projected: tuple[RawElement, ...],
        table: PdfBoundaryPartitionedTableObservation,
    ) -> tuple[RawElement, ...]:
        partition_payload = [
            {
                "page": item.page_number,
                "native_block_number": item.native_block_number,
                "native_order": item.native_order,
                "table_line_native_orders": list(item.table_line_native_orders),
                "residual_line_native_orders": list(item.residual_line_native_orders),
                "original_native_bbox_points": list(item.original_bbox),
                "original_displayed_bbox_points": list(
                    item.original_displayed_bbox
                ),
            }
            for item in table.source_block_line_partitions
        ]
        output: list[RawElement] = []
        for element in projected:
            payload = element.model_dump(mode="python")
            attributes = dict(payload["attributes"])
            attributes["pdf_source_block_partition_version"] = (
                PDF_SOURCE_BLOCK_PARTITION_VERSION
            )
            attributes["pdf_source_block_line_partitions"] = partition_payload
            attributes["integrity_evidence"] = (
                "pdf_rectangular_merged_geometry_with_native_line_partition"
            )
            if element.type_hint == "TABLE_CELL":
                text = payload.get("text")
                if isinstance(text, str):
                    payload["text"] = text.strip()
                attributes["pdf_partitioned_table_text_normalization_version"] = (
                    PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION
                )
            payload["attributes"] = attributes

            provenance = dict(payload["provenance"])
            metadata = dict(provenance.get("metadata", {}))
            metadata["source_block_partition"] = PDF_SOURCE_BLOCK_PARTITION_VERSION
            if element.type_hint == "TABLE_CELL":
                metadata["derived_cell_text_normalization"] = (
                    PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION
                )
            provenance["metadata"] = metadata
            payload["provenance"] = provenance
            output.append(RawElement.model_validate(payload))
        return tuple(output)

    @staticmethod
    def _annotate_residual_fragment(
        element: RawElement,
        *,
        partition: PdfBlockLinePartition,
        owner_table: PdfBoundaryPartitionedTableObservation,
    ) -> RawElement:
        if element.type_hint != "PARAGRAPH":
            raise AdapterError("M2.6 residual source fragment must remain a paragraph")
        payload = element.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        first_line = partition.residual_line_native_orders[0]
        last_line = partition.residual_line_native_orders[-1]
        attributes[SOURCE_ANCHOR_ATTRIBUTE] = {
            "kind": "pdf_native_block_fragment",
            "id": (
                f"page:{partition.page_number}:block:{partition.native_block_number}:"
                f"lines:{first_line}-{last_line}"
            ),
        }
        attributes["pdf_source_block_partition_version"] = (
            PDF_SOURCE_BLOCK_PARTITION_VERSION
        )
        attributes["pdf_source_partition_role"] = "residual_suffix"
        attributes["pdf_original_native_block_bbox_points"] = list(
            partition.original_bbox
        )
        attributes["pdf_original_displayed_block_bbox_points"] = list(
            partition.original_displayed_bbox
        )
        attributes["pdf_table_owned_line_native_orders"] = list(
            partition.table_line_native_orders
        )
        attributes["pdf_residual_line_native_orders"] = list(
            partition.residual_line_native_orders
        )
        attributes["pdf_native_bbox_scope"] = "source_line_fragment_union"
        attributes["pdf_partition_owner_table_index"] = owner_table.table_index
        payload["attributes"] = attributes

        provenance = dict(payload["provenance"])
        metadata = dict(provenance.get("metadata", {}))
        metadata["source_block_partition"] = PDF_SOURCE_BLOCK_PARTITION_VERSION
        metadata["source_binding"] = (
            "exact untouched native-line residual from a partitioned TextPage block"
        )
        provenance["metadata"] = metadata
        payload["provenance"] = provenance
        return RawElement.model_validate(payload)

    @staticmethod
    def _upgrade_m26_element(element: RawElement) -> RawElement:
        if element.type_hint not in {"TABLE", "TABLE_ROW", "TABLE_CELL"}:
            return element
        payload = element.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        attributes["pdf_table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        payload["attributes"] = attributes
        provenance = dict(payload["provenance"])
        metadata = dict(provenance.get("metadata", {}))
        metadata["table_detection"] = PDF_TABLE_STRUCTURE_VERSION
        provenance["metadata"] = metadata
        payload["provenance"] = provenance
        return RawElement.model_validate(payload)

    @staticmethod
    def _upgrade_m26_metadata(metadata: DocumentMetadata) -> DocumentMetadata:
        payload = metadata.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        pdf = dict(attributes.get("pdf", {}))
        pdf["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        pdf["source_block_partition_version"] = PDF_SOURCE_BLOCK_PARTITION_VERSION
        pdf["source_block_partition_capability"] = (
            "table_prefix_residual_suffix_only"
        )
        pdf["partitioned_table_text_normalization_version"] = (
            PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION
        )
        pdf["ocr_table_extraction"] = "deferred_optional_extension"
        attributes["pdf"] = pdf
        payload["attributes"] = attributes
        return DocumentMetadata.model_validate(payload)

    @staticmethod
    def _upgrade_m26_diagnostics(
        diagnostics: tuple[AdapterDiagnostic, ...],
        raw_elements: tuple[RawElement, ...],
    ) -> tuple[AdapterDiagnostic, ...]:
        partitioned_pages = {
            element.location.page
            for element in raw_elements
            if element.type_hint == "TABLE"
            and element.location is not None
            and element.location.page is not None
            and element.attributes.get("pdf_source_block_partition_version")
            == PDF_SOURCE_BLOCK_PARTITION_VERSION
        }
        output: list[AdapterDiagnostic] = []
        for diagnostic in diagnostics:
            payload = diagnostic.model_dump(mode="python")
            metadata = dict(payload["metadata"])
            page = metadata.get("page")
            if diagnostic.code == "PDF_TABLE_STRUCTURE_EXTRACTED_M2":
                payload["message"] = (
                    f"PDF page {page} contains high-confidence native table structure. "
                    "M2.6 can additionally partition an exact native-line table prefix "
                    "from a following residual suffix without rewriting source spans"
                )
                metadata["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
                if page in partitioned_pages:
                    metadata["source_block_partition_version"] = (
                        PDF_SOURCE_BLOCK_PARTITION_VERSION
                    )
                    metadata["partitioned_table_text_normalization_version"] = (
                        PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION
                    )
            elif diagnostic.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2":
                payload["message"] = (
                    f"PDF page {page} contains table-like evidence that M2.6 cannot "
                    "project without ambiguous topology or source-line ownership. "
                    "Original native text remains authoritative"
                )
            payload["metadata"] = metadata
            output.append(AdapterDiagnostic.model_validate(payload))
        return tuple(output)
