"""Content profiling and region routing for canonical source elements."""

from .content_profiler import (
    CONTENT_PROFILER_VERSION,
    ContentCategory,
    ContentProfile,
    ContentProfileSignals,
    ContentProfiler,
    ContentProfilingError,
    content_category_for_element,
    content_category_for_type,
)
from .regions import (
    CONTENT_REGION_POLICY_VERSION,
    CONTENT_REGION_SEGMENTER_VERSION,
    ContentRegionPolicy,
    ContentRegionSegmentationError,
    ContentRegionSegmentationResult,
    ContentRegionSegmenter,
)

__all__ = [
    "CONTENT_PROFILER_VERSION",
    "CONTENT_REGION_POLICY_VERSION",
    "CONTENT_REGION_SEGMENTER_VERSION",
    "ContentCategory",
    "ContentProfile",
    "ContentProfileSignals",
    "ContentProfiler",
    "ContentProfilingError",
    "ContentRegionPolicy",
    "ContentRegionSegmentationError",
    "ContentRegionSegmentationResult",
    "ContentRegionSegmenter",
    "content_category_for_element",
    "content_category_for_type",
]
