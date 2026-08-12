from __future__ import annotations

from collections import defaultdict
from math import isclose

from source_understanding.schemas.document import DocumentMetadata
from source_understanding.schemas.element import RawElement
from source_understanding.source_attributes import INTEGRITY_GROUP_ID_ATTRIBUTE

from ..base import AdapterDiagnostic, SourceAdapterResult
from .adapter_m23 import (
    PDF_BLOCK_RECONSTRUCTION_VERSION as _M23_BLOCK_RECONSTRUCTION_VERSION,
    PDF_MEDIA_TYPE as _M23_MEDIA_TYPE,
    PDF_READING_ORDER_VERSION as _M23_READING_ORDER_VERSION,
    PDF_TABLE_TEXT_RECONSTRUCTION_VERSION as _M23_TABLE_TEXT_RECONSTRUCTION_VERSION,
    PdfAdapter as _M23PdfAdapter,
    PdfAdapterPolicy as _M23PdfAdapterPolicy,
)
from .backend import PyMuPdfNativeBackend
from .table_merged import PDF_MERGED_TABLE_STRATEGY, PdfMergedTableDetector
from .tables import PdfTableDetectionResult


PDF_ADAPTER_VERSION = "5"
PDF_POLICY_VERSION = "6"
PDF_MEDIA_TYPE = _M23_MEDIA_TYPE
PDF_READING_ORDER_VERSION = _M23_READING_ORDER_VERSION
PDF_BLOCK_RECONSTRUCTION_VERSION = _M23_BLOCK_RECONSTRUCTION_VERSION
PDF_TABLE_STRUCTURE_VERSION = "multi-strategy-v3"
PDF_TABLE_TEXT_RECONSTRUCTION_VERSION = _M23_TABLE_TEXT_RECONSTRUCTION_VERSION
PDF_MERGED_TABLE_TOPOLOGY_VERSION = "rectangular-spans-v1"

_MERGED_RETRY_REASONS = frozenset(
    {
        "complex_or_merged_cells",
        "complex_or_irregular_topology",
    }
)


class PdfAdapterPolicy(_M23PdfAdapterPolicy):
    """PDF M2.4 policy: add exact rectangular row/column spans without OCR."""

    version: str = PDF_POLICY_VERSION
    enable_merged_table_structure: bool = True


class PdfAdapter(_M23PdfAdapter):
    """PDF adapter through M2.4 merged ruled-table topology.

    OCR remains intentionally absent. M2.4 only retries line-table candidates
    rejected by the simple rectangular path and accepts them when every logical
    grid slot is explained by one rectangular row/column span.
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
        self._merged_table_detector = PdfMergedTableDetector(self._table_detector.policy)

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        result = super().adapt(data, source_name=source_name)
        raw_elements = self._annotate_merged_topology(result.raw_elements)
        return SourceAdapterResult(
            protocol_version=result.protocol_version,
            adapter_name=result.adapter_name,
            adapter_version=self.version,
            media_type=result.media_type,
            source_name=result.source_name,
            content_hash=result.content_hash,
            raw_elements=raw_elements,
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
        if not self.policy.enable_table_structure:
            return base_result
        if not self.policy.enable_merged_table_structure:
            return base_result

        retry_indexes = frozenset(
            item.table_index
            for item in base_result.rejected
            if item.reason in _MERGED_RETRY_REASONS
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
            merged_result = self._merged_table_detector.detect(
                page,
                native_text_blocks,
                candidate_indexes=retry_indexes,
                reserved_source_orders=reserved,
            )
        except Exception as exc:
            diagnostics.append(
                AdapterDiagnostic(
                    code="PDF_TABLE_MERGED_DETECTION_FAILED_M2_4",
                    message=(
                        f"PDF page {page_number} merged-table topology inspection failed "
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

        if not merged_result.tables:
            if not merged_result.rejected:
                return base_result
            retained = tuple(
                item
                for item in base_result.rejected
                if item.table_index not in retry_indexes
            )
            return PdfTableDetectionResult(
                tables=base_result.tables,
                rejected=retained + merged_result.rejected,
            )

        accepted_indexes = {item.table_index for item in merged_result.tables}
        tables = tuple(
            sorted(
                (*base_result.tables, *merged_result.tables),
                key=lambda item: item.source_native_orders[0],
            )
        )
        rejected = tuple(
            item
            for item in base_result.rejected
            if item.table_index not in accepted_indexes
        ) + tuple(
            item
            for item in merged_result.rejected
            if item.table_index not in accepted_indexes
        )
        return PdfTableDetectionResult(tables=tables, rejected=rejected)

    @staticmethod
    def _upgrade_table_element(element: RawElement) -> RawElement:
        upgraded = _M23PdfAdapter._upgrade_table_element(element)
        if upgraded.type_hint not in {"TABLE", "TABLE_ROW", "TABLE_CELL"}:
            return upgraded
        payload = upgraded.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        attributes["pdf_table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        strategy = attributes.get("pdf_table_detection_strategy")
        if strategy == PDF_MERGED_TABLE_STRATEGY:
            attributes["integrity_evidence"] = "pdf_rectangular_merged_geometry"
            attributes["pdf_merged_table_topology_version"] = (
                PDF_MERGED_TABLE_TOPOLOGY_VERSION
            )
        payload["attributes"] = attributes
        provenance = dict(payload["provenance"])
        provenance_metadata = dict(provenance.get("metadata", {}))
        provenance_metadata["table_detection"] = PDF_TABLE_STRUCTURE_VERSION
        if strategy == PDF_MERGED_TABLE_STRATEGY:
            provenance_metadata["merged_table_topology"] = (
                PDF_MERGED_TABLE_TOPOLOGY_VERSION
            )
        provenance["metadata"] = provenance_metadata
        payload["provenance"] = provenance
        return RawElement.model_validate(payload)

    @staticmethod
    def _upgrade_metadata(metadata: DocumentMetadata) -> DocumentMetadata:
        upgraded = _M23PdfAdapter._upgrade_metadata(metadata)
        payload = upgraded.model_dump(mode="python")
        attributes = dict(payload["attributes"])
        pdf = dict(attributes.get("pdf", {}))
        pdf["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
        pdf["merged_table_topology_version"] = PDF_MERGED_TABLE_TOPOLOGY_VERSION
        pdf["table_detection_strategies"] = [
            "lines_strict",
            PDF_MERGED_TABLE_STRATEGY,
            "text_aligned",
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
        upgraded = _M23PdfAdapter._upgrade_diagnostics(diagnostics, raw_elements)
        output: list[AdapterDiagnostic] = []
        for diagnostic in upgraded:
            payload = diagnostic.model_dump(mode="python")
            metadata = dict(payload["metadata"])
            if diagnostic.code == "PDF_TABLE_STRUCTURE_EXTRACTED_M2":
                page = metadata.get("page")
                payload["message"] = (
                    f"PDF page {page} contains high-confidence native table structure. "
                    "M2.4 supports simple, rectangular merged, and conservative native "
                    "text-aligned tables while preserving exact source-span provenance; "
                    "OCR is not involved"
                )
                metadata["table_structure_version"] = PDF_TABLE_STRUCTURE_VERSION
            elif diagnostic.code == "PDF_TABLE_CANDIDATE_UNSUPPORTED_M2":
                page = metadata.get("page")
                payload["message"] = (
                    f"PDF page {page} contains table-like evidence that M2.4 cannot "
                    "project without inventing topology. Original native text blocks "
                    "are preserved instead"
                )
            payload["metadata"] = metadata
            output.append(AdapterDiagnostic.model_validate(payload))
        return tuple(output)

    def _annotate_merged_topology(
        self,
        raw_elements: tuple[RawElement, ...],
    ) -> tuple[RawElement, ...]:
        by_group: dict[str, list[int]] = defaultdict(list)
        for index, element in enumerate(raw_elements):
            if element.type_hint not in {"TABLE", "TABLE_ROW", "TABLE_CELL"}:
                continue
            if element.attributes.get("pdf_table_detection_strategy") != PDF_MERGED_TABLE_STRATEGY:
                continue
            group_id = element.attributes.get(INTEGRITY_GROUP_ID_ATTRIBUTE)
            if isinstance(group_id, str):
                by_group[group_id].append(index)
        if not by_group:
            return raw_elements

        output = list(raw_elements)
        for indexes in by_group.values():
            group = [raw_elements[index] for index in indexes]
            table = next((item for item in group if item.type_hint == "TABLE"), None)
            if table is None:
                raise ValueError("merged PDF table group is missing TABLE container")
            row_count = self._positive_attribute_int(table, "row_count")
            column_count = self._positive_attribute_int(table, "column_count")
            table_bbox = self._attribute_rect(table, "pdf_native_bbox_points")
            rows = sorted(
                (item for item in group if item.type_hint == "TABLE_ROW"),
                key=lambda item: self._nonnegative_attribute_int(item, "row_index"),
            )
            if len(rows) != row_count:
                raise ValueError("merged PDF table row count drift after emission")
            tolerance = self.policy.table_topology_tolerance_points
            row_boundaries = [table_bbox[1]]
            for expected, row in enumerate(rows):
                row_index = self._nonnegative_attribute_int(row, "row_index")
                if row_index != expected:
                    raise ValueError("merged PDF table row indexes are not contiguous")
                row_bbox = self._attribute_rect(row, "pdf_native_bbox_points")
                if not isclose(row_bbox[0], table_bbox[0], abs_tol=tolerance) or not isclose(
                    row_bbox[2], table_bbox[2], abs_tol=tolerance
                ):
                    raise ValueError("merged PDF row bbox does not cover table width")
                if not isclose(row_boundaries[-1], row_bbox[1], abs_tol=tolerance):
                    raise ValueError("merged PDF row boundary drift")
                row_boundaries.append(row_bbox[3])
            if not isclose(row_boundaries[-1], table_bbox[3], abs_tol=tolerance):
                raise ValueError("merged PDF rows do not cover table height")

            cells = [item for item in group if item.type_hint == "TABLE_CELL"]
            x_values = [table_bbox[0], table_bbox[2]]
            for cell in cells:
                bbox = self._attribute_rect(cell, "pdf_native_bbox_points")
                x_values.extend((bbox[0], bbox[2]))
            column_boundaries = self._cluster_boundaries(x_values)
            if len(column_boundaries) != column_count + 1:
                raise ValueError("merged PDF logical column boundaries cannot be rebuilt")

            merged_cell_count = 0
            for index in indexes:
                element = raw_elements[index]
                payload = element.model_dump(mode="python")
                attributes = dict(payload["attributes"])
                if element.type_hint == "TABLE":
                    attributes["pdf_table_topology"] = "rectangular_with_spans"
                    attributes["pdf_merged_cell_count"] = 0
                    payload["attributes"] = attributes
                    output[index] = RawElement.model_validate(payload)
                    continue
                if element.type_hint == "TABLE_ROW":
                    attributes["logical_column_count"] = column_count
                    payload["attributes"] = attributes
                    output[index] = RawElement.model_validate(payload)
                    continue

                row_index = self._nonnegative_attribute_int(element, "row_index")
                cell_index = self._nonnegative_attribute_int(element, "cell_index")
                bbox = self._attribute_rect(element, "pdf_native_bbox_points")
                x0 = self._boundary_index(tuple(column_boundaries), bbox[0])
                x1 = self._boundary_index(tuple(column_boundaries), bbox[2])
                y0 = self._boundary_index(tuple(row_boundaries), bbox[1])
                y1 = self._boundary_index(tuple(row_boundaries), bbox[3])
                if None in {x0, x1, y0, y1}:
                    raise ValueError("merged PDF cell boundary cannot be rebuilt")
                assert x0 is not None and x1 is not None and y0 is not None and y1 is not None
                if x0 != cell_index or y0 != row_index or x1 <= x0 or y1 <= y0:
                    raise ValueError("merged PDF cell anchor drift after emission")
                row_span = y1 - y0
                column_span = x1 - x0
                if row_span > 1 or column_span > 1:
                    merged_cell_count += 1
                attributes["row_span"] = row_span
                attributes["column_span"] = column_span
                attributes["logical_slots"] = [
                    {"row_index": row, "cell_index": column}
                    for row in range(y0, y1)
                    for column in range(x0, x1)
                ]
                payload["attributes"] = attributes
                output[index] = RawElement.model_validate(payload)

            table_index = next(
                index for index in indexes if raw_elements[index].type_hint == "TABLE"
            )
            table_payload = output[table_index].model_dump(mode="python")
            table_attributes = dict(table_payload["attributes"])
            table_attributes["pdf_merged_cell_count"] = merged_cell_count
            table_attributes["has_merged_cells"] = merged_cell_count > 0
            table_payload["attributes"] = table_attributes
            output[table_index] = RawElement.model_validate(table_payload)

        return tuple(output)

    @staticmethod
    def _positive_attribute_int(element: RawElement, name: str) -> int:
        value = element.attributes.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"invalid {name} on emitted PDF table")
        return value

    @staticmethod
    def _nonnegative_attribute_int(element: RawElement, name: str) -> int:
        value = element.attributes.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"invalid {name} on emitted PDF table")
        return value

    @staticmethod
    def _attribute_rect(element: RawElement, name: str) -> tuple[float, float, float, float]:
        value = element.attributes.get(name)
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError(f"invalid {name} on emitted PDF table")
        rect = tuple(float(item) for item in value)
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            raise ValueError(f"non-positive {name} on emitted PDF table")
        return rect[0], rect[1], rect[2], rect[3]

    def _cluster_boundaries(self, values: list[float]) -> tuple[float, ...]:
        tolerance = self.policy.table_topology_tolerance_points
        clusters: list[list[float]] = []
        for value in sorted(values):
            if not clusters or value - clusters[-1][-1] > tolerance:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        return tuple(sum(cluster) / len(cluster) for cluster in clusters)

    def _boundary_index(self, boundaries: tuple[float, ...], value: float) -> int | None:
        tolerance = self.policy.table_topology_tolerance_points
        if not boundaries:
            return None
        index = min(range(len(boundaries)), key=lambda item: abs(boundaries[item] - value))
        if abs(boundaries[index] - value) > tolerance:
            return None
        return index
