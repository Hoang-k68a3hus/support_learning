from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import PdfBlockObservation, PdfOccludedTextObservation, PdfRect


@dataclass(frozen=True, slots=True)
class PdfVisibilityPolicy:
    """Conservative paint-order policy for excluding fully covered native text."""

    minimum_trace_overlap_ratio: float = 0.50
    minimum_occlusion_coverage_ratio: float = 0.95
    minimum_fill_opacity: float = 0.98


class PdfVisibilityResolver:
    """Partition native text into visible and fully occluded source observations.

    PyMuPDF TextPage extraction can return text objects that are later painted over
    by opaque vector fills. Those objects remain real PDF source objects, but they
    are not visible document content and must not become retrieval text. M1 uses
    paint sequence only for a high-confidence exclusion: a later opaque fill must
    cover almost the entire native block bbox. Missing or ambiguous paint evidence
    always preserves the text block.
    """

    def __init__(self, policy: PdfVisibilityPolicy | None = None) -> None:
        self.policy = policy if policy is not None else PdfVisibilityPolicy()

    def partition(
        self,
        page: Any,
        blocks: tuple[PdfBlockObservation, ...],
    ) -> tuple[
        tuple[PdfBlockObservation, ...],
        tuple[PdfOccludedTextObservation, ...],
    ]:
        if not blocks:
            return blocks, ()

        traces = self._text_traces(page)
        occluders = self._opaque_fill_occluders(page)
        if not traces or not occluders:
            return blocks, ()

        visible: list[PdfBlockObservation] = []
        occluded: list[PdfOccludedTextObservation] = []
        for block in blocks:
            text_seqnos = [
                seqno
                for seqno, bbox in traces
                if self._coverage(bbox, block.bbox)
                >= self.policy.minimum_trace_overlap_ratio
            ]
            if not text_seqnos:
                visible.append(block)
                continue

            paint_seqno = max(text_seqnos)
            best_occluder: tuple[float, int, PdfRect] | None = None
            for occluder_seqno, occluder_bbox in occluders:
                if occluder_seqno <= paint_seqno:
                    continue
                coverage = self._coverage(block.bbox, occluder_bbox)
                if coverage < self.policy.minimum_occlusion_coverage_ratio:
                    continue
                candidate = (coverage, occluder_seqno, occluder_bbox)
                if best_occluder is None or candidate[:2] > best_occluder[:2]:
                    best_occluder = candidate

            if best_occluder is None:
                visible.append(block)
                continue

            coverage, occluder_seqno, occluder_bbox = best_occluder
            occluded.append(
                PdfOccludedTextObservation(
                    native_block_number=block.native_block_number,
                    native_order=block.native_order,
                    bbox=block.bbox,
                    displayed_bbox=block.displayed_bbox,
                    text_character_count=block.text_character_count,
                    paint_seqno=paint_seqno,
                    occluder_seqno=occluder_seqno,
                    occluder_bbox=occluder_bbox,
                    coverage_ratio=coverage,
                )
            )

        return tuple(visible), tuple(occluded)

    @staticmethod
    def _text_traces(page: Any) -> tuple[tuple[int, PdfRect], ...]:
        try:
            raw_traces = page.get_texttrace()
        except Exception:
            return ()

        output: list[tuple[int, PdfRect]] = []
        for item in raw_traces:
            if not isinstance(item, dict):
                continue
            seqno = item.get("seqno")
            bbox = PdfVisibilityResolver._rect(item.get("bbox"))
            if isinstance(seqno, int) and bbox is not None:
                output.append((seqno, bbox))
        return tuple(output)

    def _opaque_fill_occluders(self, page: Any) -> tuple[tuple[int, PdfRect], ...]:
        try:
            drawings = page.get_drawings()
        except Exception:
            return ()

        output: list[tuple[int, PdfRect]] = []
        for item in drawings:
            if not isinstance(item, dict):
                continue
            seqno = item.get("seqno")
            opacity = item.get("fill_opacity")
            drawing_type = str(item.get("type", ""))
            bbox = self._rect(item.get("rect"))
            if (
                not isinstance(seqno, int)
                or not isinstance(opacity, (int, float))
                or bbox is None
            ):
                continue
            if "f" not in drawing_type:
                continue
            if float(opacity) < self.policy.minimum_fill_opacity:
                continue
            if not self._is_axis_aligned_rectangle_fill(item, bbox):
                continue
            output.append((seqno, bbox))
        return tuple(output)

    @classmethod
    def _is_axis_aligned_rectangle_fill(
        cls,
        drawing: dict[str, object],
        bbox: PdfRect,
    ) -> bool:
        """Accept only rectangle-like fills to avoid bbox-only occlusion guesses."""

        tolerance = 0.5
        items = drawing.get("items")
        if not isinstance(items, (list, tuple)):
            return False

        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            if item[0] != "re":
                continue
            rect = cls._rect(item[1])
            if rect is not None and max(
                abs(rect[index] - bbox[index]) for index in range(4)
            ) <= tolerance:
                return True

        edges: set[str] = set()
        line_count = 0
        x0, y0, x1, y1 = bbox
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            if item[0] != "l":
                continue
            start = cls._point(item[1])
            end = cls._point(item[2])
            if start is None or end is None:
                return False
            sx, sy = start
            ex, ey = end
            if abs(sx - ex) > tolerance and abs(sy - ey) > tolerance:
                return False
            if not all(
                abs(x - x0) <= tolerance
                or abs(x - x1) <= tolerance
                or abs(y - y0) <= tolerance
                or abs(y - y1) <= tolerance
                for x, y in (start, end)
            ):
                return False
            line_count += 1
            if abs(sy - ey) <= tolerance:
                if abs(sy - y0) <= tolerance:
                    edges.add("top")
                if abs(sy - y1) <= tolerance:
                    edges.add("bottom")
            if abs(sx - ex) <= tolerance:
                if abs(sx - x0) <= tolerance:
                    edges.add("left")
                if abs(sx - x1) <= tolerance:
                    edges.add("right")

        return line_count >= 3 and len(edges) >= 3

    @staticmethod
    def _point(value: object) -> tuple[float, float] | None:
        try:
            return (float(getattr(value, "x")), float(getattr(value, "y")))
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _rect(value: object) -> PdfRect | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple)) and len(value) == 4:
            coords = tuple(float(item) for item in value)
        else:
            try:
                coords = (
                    float(getattr(value, "x0")),
                    float(getattr(value, "y0")),
                    float(getattr(value, "x1")),
                    float(getattr(value, "y1")),
                )
            except (TypeError, ValueError, AttributeError):
                return None
        x0, y0, x1, y1 = coords
        if x1 < x0 or y1 < y0:
            return None
        return (x0, y0, x1, y1)

    @staticmethod
    def _area(rect: PdfRect) -> float:
        return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])

    @classmethod
    def _coverage(cls, target: PdfRect, cover: PdfRect) -> float:
        denominator = cls._area(target)
        if denominator <= 0:
            return 0.0
        intersection = max(0.0, min(target[2], cover[2]) - max(target[0], cover[0]))
        intersection *= max(0.0, min(target[3], cover[3]) - max(target[1], cover[1]))
        return intersection / denominator
