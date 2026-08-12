from __future__ import annotations

import unittest

from source_understanding.adapters.base import AdapterError
from source_understanding.adapters.pdf.adapter_m26 import (
    PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION,
    PdfAdapter,
)
from source_understanding.adapters.pdf.models import (
    PdfBlockLinePartition,
    PdfBlockObservation,
    PdfLineObservation,
    PdfSpanObservation,
)
from source_understanding.adapters.pdf.source_partition import (
    PdfSourceBlockLinePartitioner,
    PdfSourcePartitionError,
)
from source_understanding.adapters.pdf.table_boundary import (
    PdfBoundaryPartitionedTableDetector,
    PdfBoundaryPartitionedTableObservation,
)
from source_understanding.adapters.pdf.tables import (
    PdfTableCellObservation,
    PdfTableRowObservation,
    PdfTableSpanFragment,
)
from source_understanding.schemas.element import Provenance, RawElement
from source_understanding.source_attributes import SOURCE_ANCHOR_ATTRIBUTE


def _span(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    native_order: int,
    line_index: int,
    span_index: int = 0,
) -> PdfSpanObservation:
    return PdfSpanObservation(
        text=text,
        bbox=bbox,
        displayed_bbox=bbox,
        font_name="Test",
        font_size=10.0,
        flags=0,
        color=0,
        alpha=255,
        origin=None,
        native_order=native_order,
        line_index=line_index,
        span_index=span_index,
    )


def _line(
    spans: tuple[PdfSpanObservation, ...],
    *,
    bbox: tuple[float, float, float, float],
    native_order: int,
) -> PdfLineObservation:
    return PdfLineObservation(
        bbox=bbox,
        displayed_bbox=bbox,
        writing_mode=0,
        direction=(1.0, 0.0),
        spans=spans,
        native_order=native_order,
    )


def _block(lines: tuple[PdfLineObservation, ...]) -> PdfBlockObservation:
    return PdfBlockObservation(
        page_number=1,
        native_block_number=9,
        native_order=9,
        bbox=(
            min(line.bbox[0] for line in lines),
            min(line.bbox[1] for line in lines),
            max(line.bbox[2] for line in lines),
            max(line.bbox[3] for line in lines),
        ),
        displayed_bbox=(
            min(line.displayed_bbox[0] for line in lines),
            min(line.displayed_bbox[1] for line in lines),
            max(line.displayed_bbox[2] for line in lines),
            max(line.displayed_bbox[3] for line in lines),
        ),
        lines=lines,
    )


def _partitioned_table(
    *,
    partition: PdfBlockLinePartition,
    table_span: PdfSpanObservation | None = None,
) -> PdfBoundaryPartitionedTableObservation:
    if table_span is None:
        rows: tuple[PdfTableRowObservation, ...] = ()
        logical_column_count = 0
    else:
        cell = PdfTableCellObservation(
            row_index=0,
            cell_index=0,
            bbox=table_span.bbox,
            displayed_bbox=table_span.displayed_bbox,
            text=table_span.text,
            fragments=(
                PdfTableSpanFragment(
                    block_number=9,
                    block_native_order=9,
                    line_native_order=20,
                    span=table_span,
                ),
            ),
        )
        rows = (
            PdfTableRowObservation(
                row_index=0,
                bbox=table_span.bbox,
                displayed_bbox=table_span.displayed_bbox,
                cells=(cell,),
            ),
        )
        logical_column_count = 1
    return PdfBoundaryPartitionedTableObservation(
        table_index=0,
        bbox=(0.0, 0.0, 100.0, 100.0),
        displayed_bbox=(0.0, 0.0, 100.0, 100.0),
        rows=rows,
        source_block_numbers=(9,),
        source_native_orders=(9,),
        detection_strategy="lines_strict_merged",
        logical_column_count=logical_column_count,
        source_block_line_partitions=(partition,),
    )


class PdfM26SourcePartitionTests(unittest.TestCase):
    def test_table_prefix_and_residual_suffix_form_exact_native_line_cover(self) -> None:
        table_0 = _line(
            (_span("A", (20.0, 20.0, 40.0, 30.0), native_order=10, line_index=0),),
            bbox=(20.0, 20.0, 40.0, 30.0),
            native_order=20,
        )
        table_1 = _line(
            (_span("B", (20.0, 45.0, 40.0, 55.0), native_order=11, line_index=1),),
            bbox=(20.0, 45.0, 40.0, 55.0),
            native_order=21,
        )
        blank = _line(
            (_span(" ", (10.0, 105.0, 12.0, 115.0), native_order=12, line_index=2),),
            bbox=(10.0, 105.0, 12.0, 115.0),
            native_order=22,
        )
        residual = _line(
            (_span("after", (10.0, 125.0, 50.0, 135.0), native_order=13, line_index=3),),
            bbox=(10.0, 125.0, 50.0, 135.0),
            native_order=23,
        )
        source = _block((table_0, table_1, blank, residual))
        partitioner = PdfSourceBlockLinePartitioner()

        result = partitioner.partition_for_table(
            (source,),
            table_bbox=(0.0, 0.0, 100.0, 100.0),
        )

        self.assertEqual(len(result.partitions), 1)
        partition = result.partitions[0]
        self.assertEqual(partition.table_line_native_orders, (20, 21))
        self.assertEqual(partition.residual_line_native_orders, (22, 23))
        self.assertEqual(
            partition.table_line_native_orders + partition.residual_line_native_orders,
            tuple(line.native_order for line in source.lines),
        )
        self.assertEqual(len(result.detection_blocks), 1)
        self.assertEqual(
            tuple(line.native_order for line in result.detection_blocks[0].lines),
            (20, 21),
        )

        fragment = partitioner.residual_fragment(source, partition)
        self.assertEqual(tuple(line.native_order for line in fragment.lines), (22, 23))
        self.assertIs(fragment.lines[0], blank)
        self.assertIs(fragment.lines[1], residual)
        self.assertIs(fragment.lines[1].spans[0], residual.spans[0])
        self.assertEqual(fragment.bbox, (10.0, 105.0, 50.0, 135.0))
        self.assertEqual(partition.original_bbox, source.bbox)

    def test_wholly_outside_span_within_tolerance_is_not_absorbed(self) -> None:
        table_line = _line(
            (_span("cell", (20.0, 20.0, 40.0, 30.0), native_order=10, line_index=0),),
            bbox=(20.0, 20.0, 40.0, 30.0),
            native_order=20,
        )
        near_outside = _line(
            (
                _span(
                    "after",
                    (20.0, 100.1, 50.0, 100.5),
                    native_order=11,
                    line_index=1,
                ),
            ),
            bbox=(20.0, 100.1, 50.0, 100.5),
            native_order=21,
        )
        source = _block((table_line, near_outside))

        result = PdfSourceBlockLinePartitioner().partition_for_table(
            (source,),
            table_bbox=(0.0, 0.0, 100.0, 100.0),
        )

        self.assertEqual(result.partitions[0].table_line_native_orders, (20,))
        self.assertEqual(result.partitions[0].residual_line_native_orders, (21,))

    def test_table_and_residual_spans_exactly_conserve_crossing_block(self) -> None:
        table_span = _span(
            "cell ",
            (20.0, 20.0, 40.0, 30.0),
            native_order=10,
            line_index=0,
        )
        table_line = _line(
            (table_span,),
            bbox=(20.0, 20.0, 40.0, 30.0),
            native_order=20,
        )
        blank = _line(
            (_span(" ", (10.0, 105.0, 12.0, 115.0), native_order=11, line_index=1),),
            bbox=(10.0, 105.0, 12.0, 115.0),
            native_order=21,
        )
        residual_line = _line(
            (_span("after ", (10.0, 125.0, 50.0, 135.0), native_order=12, line_index=2),),
            bbox=(10.0, 125.0, 50.0, 135.0),
            native_order=22,
        )
        source = _block((table_line, blank, residual_line))
        partitioner = PdfSourceBlockLinePartitioner()
        result = partitioner.partition_for_table(
            (source,),
            table_bbox=(0.0, 0.0, 100.0, 100.0),
        )
        partition = result.partitions[0]
        residual = partitioner.residual_fragment(source, partition)
        table = _partitioned_table(partition=partition, table_span=table_span)

        PdfAdapter._validate_partition_span_conservation(
            table=table,
            original=source,
            residual=residual,
            partition=partition,
        )

        incomplete_residual = PdfBlockObservation(
            page_number=residual.page_number,
            native_block_number=residual.native_block_number,
            native_order=residual.native_order,
            bbox=blank.bbox,
            displayed_bbox=blank.displayed_bbox,
            lines=(blank,),
        )
        with self.assertRaises(AdapterError):
            PdfAdapter._validate_partition_span_conservation(
                table=table,
                original=source,
                residual=incomplete_residual,
                partition=partition,
            )

    def test_duplicate_table_span_ownership_is_rejected(self) -> None:
        table_span = _span(
            "cell",
            (20.0, 20.0, 40.0, 30.0),
            native_order=10,
            line_index=0,
        )
        table_line = _line(
            (table_span,),
            bbox=(20.0, 20.0, 40.0, 30.0),
            native_order=20,
        )
        fragment = PdfTableSpanFragment(
            block_number=9,
            block_native_order=9,
            line_native_order=20,
            span=table_span,
        )
        cells = (
            PdfTableCellObservation(
                row_index=0,
                cell_index=0,
                bbox=(20.0, 20.0, 40.0, 30.0),
                displayed_bbox=(20.0, 20.0, 40.0, 30.0),
                text="cell",
                fragments=(fragment,),
            ),
            PdfTableCellObservation(
                row_index=0,
                cell_index=1,
                bbox=(40.0, 20.0, 60.0, 30.0),
                displayed_bbox=(40.0, 20.0, 60.0, 30.0),
                text="cell",
                fragments=(fragment,),
            ),
        )
        table = PdfBoundaryPartitionedTableObservation(
            table_index=0,
            bbox=(0.0, 0.0, 100.0, 100.0),
            displayed_bbox=(0.0, 0.0, 100.0, 100.0),
            rows=(
                PdfTableRowObservation(
                    row_index=0,
                    bbox=(20.0, 20.0, 60.0, 30.0),
                    displayed_bbox=(20.0, 20.0, 60.0, 30.0),
                    cells=cells,
                ),
            ),
            source_block_numbers=(9,),
            source_native_orders=(9,),
            detection_strategy="lines_strict_merged",
            logical_column_count=2,
            source_block_line_partitions=(),
        )
        partition = PdfBlockLinePartition(
            page_number=1,
            native_block_number=9,
            native_order=9,
            original_bbox=(20.0, 20.0, 60.0, 120.0),
            original_displayed_bbox=(20.0, 20.0, 60.0, 120.0),
            table_line_native_orders=(20,),
            residual_line_native_orders=(21,),
        )

        self.assertFalse(
            PdfBoundaryPartitionedTableDetector._partition_span_cover_is_exact(
                table,
                (_block((table_line,)),),
                (partition,),
            )
        )

    def test_partitioned_cell_text_trims_only_derived_outer_whitespace(self) -> None:
        partition = PdfBlockLinePartition(
            page_number=1,
            native_block_number=9,
            native_order=9,
            original_bbox=(0.0, 0.0, 100.0, 150.0),
            original_displayed_bbox=(0.0, 0.0, 100.0, 150.0),
            table_line_native_orders=(20,),
            residual_line_native_orders=(21,),
        )
        table = _partitioned_table(partition=partition)
        source_spans = [
            {
                "text": "  value \n",
                "native_order": 10,
                "line_native_order": 20,
            }
        ]
        cell = RawElement(
            text="  value \n",
            type_hint="TABLE_CELL",
            order=0,
            attributes={"pdf_source_spans": source_spans},
            provenance=Provenance(
                source="DERIVED",
                extractor="test",
            ),
        )

        normalized = PdfAdapter._annotate_partitioned_table_projection((cell,), table)[0]

        self.assertEqual(normalized.text, "value")
        self.assertEqual(
            normalized.attributes["pdf_source_spans"][0]["text"],
            "  value \n",
        )
        self.assertEqual(
            normalized.attributes["pdf_partitioned_table_text_normalization_version"],
            PDF_PARTITIONED_TABLE_TEXT_NORMALIZATION_VERSION,
        )

    def test_residual_annotation_is_fragment_scoped_without_rewriting_text(self) -> None:
        partition = PdfBlockLinePartition(
            page_number=1,
            native_block_number=9,
            native_order=9,
            original_bbox=(0.0, 0.0, 100.0, 150.0),
            original_displayed_bbox=(0.0, 0.0, 100.0, 150.0),
            table_line_native_orders=(20,),
            residual_line_native_orders=(21, 22),
        )
        owner = _partitioned_table(partition=partition)
        source_spans = [
            {"native_order": 11, "line_native_order": 21, "text": " "},
            {"native_order": 12, "line_native_order": 22, "text": "after "},
        ]
        residual = RawElement(
            text=" \nafter ",
            type_hint="PARAGRAPH",
            order=0,
            attributes={
                SOURCE_ANCHOR_ATTRIBUTE: {"kind": "pdf_native_block", "id": "page:1:block:9"},
                "pdf_native_order": 9,
                "pdf_spans": source_spans,
                "pdf_native_bbox_points": [10.0, 105.0, 50.0, 135.0],
            },
            provenance=Provenance(source="DERIVED", extractor="test"),
        )

        projected = PdfAdapter._annotate_residual_fragment(
            residual,
            partition=partition,
            owner_table=owner,
        )

        self.assertEqual(projected.text, residual.text)
        self.assertEqual(projected.attributes["pdf_spans"], source_spans)
        self.assertEqual(
            projected.attributes[SOURCE_ANCHOR_ATTRIBUTE],
            {"kind": "pdf_native_block_fragment", "id": "page:1:block:9:lines:21-22"},
        )
        self.assertEqual(
            projected.attributes["pdf_native_bbox_scope"],
            "source_line_fragment_union",
        )
        self.assertEqual(
            projected.attributes["pdf_original_native_block_bbox_points"],
            [0.0, 0.0, 100.0, 150.0],
        )

    def test_mixed_inside_and_outside_spans_on_one_line_fail_closed(self) -> None:
        mixed = _line(
            (
                _span("inside", (20.0, 20.0, 50.0, 30.0), native_order=1, line_index=0),
                _span(
                    "outside",
                    (120.0, 20.0, 170.0, 30.0),
                    native_order=2,
                    line_index=0,
                    span_index=1,
                ),
            ),
            bbox=(20.0, 20.0, 170.0, 30.0),
            native_order=1,
        )
        source = _block((mixed,))

        with self.assertRaises(PdfSourcePartitionError) as caught:
            PdfSourceBlockLinePartitioner().partition_for_table(
                (source,),
                table_bbox=(0.0, 0.0, 100.0, 100.0),
            )
        self.assertEqual(caught.exception.reason, "boundary_partition_ambiguous_block_geometry")

    def test_span_partially_crossing_table_boundary_is_never_split(self) -> None:
        crossing = _line(
            (
                _span(
                    "partial",
                    (90.0, 20.0, 120.0, 30.0),
                    native_order=1,
                    line_index=0,
                ),
            ),
            bbox=(90.0, 20.0, 120.0, 30.0),
            native_order=1,
        )
        source = _block((crossing,))

        with self.assertRaises(PdfSourcePartitionError) as caught:
            PdfSourceBlockLinePartitioner().partition_for_table(
                (source,),
                table_bbox=(0.0, 0.0, 100.0, 100.0),
            )
        self.assertEqual(caught.exception.reason, "boundary_partition_ambiguous_block_geometry")

    def test_outside_prefix_followed_by_table_content_is_not_supported(self) -> None:
        outside = _line(
            (_span("before", (10.0, 120.0, 50.0, 130.0), native_order=1, line_index=0),),
            bbox=(10.0, 120.0, 50.0, 130.0),
            native_order=1,
        )
        inside = _line(
            (_span("cell", (20.0, 20.0, 50.0, 30.0), native_order=2, line_index=1),),
            bbox=(20.0, 20.0, 50.0, 30.0),
            native_order=2,
        )
        source = _block((outside, inside))

        with self.assertRaises(PdfSourcePartitionError) as caught:
            PdfSourceBlockLinePartitioner().partition_for_table(
                (source,),
                table_bbox=(0.0, 0.0, 100.0, 100.0),
            )
        self.assertEqual(caught.exception.reason, "boundary_partition_requires_table_prefix")


if __name__ == "__main__":
    unittest.main()
