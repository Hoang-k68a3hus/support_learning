from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import Field

from source_understanding.completion import UnderstandingCompletionBuilder
from source_understanding.pipeline import SourceUnderstandingPipeline, SourceUnderstandingResult
from source_understanding.schemas.context import Identifier, SchemaModel
from source_understanding.schemas.document import ContentRegion, DocumentQuality
from source_understanding.schemas.relation import Relation

from .base import (
    SOURCE_ADAPTER_PROTOCOL_VERSION,
    AdapterError,
    SourceAdapter,
    SourceAdapterResult,
    validate_adapter,
)


SOURCE_ADAPTER_RUNNER_VERSION = "1"


class AdaptedSourceUnderstandingResult(SchemaModel):
    version: str = SOURCE_ADAPTER_RUNNER_VERSION
    document_id: Identifier
    adapter_result: SourceAdapterResult
    understanding: SourceUnderstandingResult


class SourceAdapterRunner:
    """Bridge exact source bytes into the format-agnostic understanding pipeline.

    The adapter remains responsible only for source-near extraction. The runner
    verifies adapter identity/hash/protocol, then delegates normalization and all
    structural interpretation to ``SourceUnderstandingPipeline``.
    """

    version = SOURCE_ADAPTER_RUNNER_VERSION

    def __init__(
        self,
        pipeline: SourceUnderstandingPipeline | None = None,
        *,
        completion_builder: UnderstandingCompletionBuilder | None = None,
    ) -> None:
        self._pipeline = pipeline if pipeline is not None else SourceUnderstandingPipeline()
        self._completion_builder = (
            completion_builder if completion_builder is not None else UnderstandingCompletionBuilder()
        )

    def understand_bytes(
        self,
        data: bytes,
        *,
        adapter: SourceAdapter,
        document_id: str,
        source_name: str | None = None,
        source_revision: str | None = None,
        processed_at: datetime | None = None,
        base_quality: DocumentQuality | None = None,
        regions: Sequence[ContentRegion] = (),
        additional_relations: Sequence[Relation] = (),
    ) -> AdaptedSourceUnderstandingResult:
        if not isinstance(data, (bytes, bytearray)):
            raise AdapterError("source adapter runner requires exact source bytes")
        payload = bytes(data)
        name, version, media_types, _extensions = validate_adapter(adapter)
        adapted = adapter.adapt(payload, source_name=source_name)
        self._validate_adapter_result(
            adapted,
            payload=payload,
            adapter_name=name,
            adapter_version=version,
            media_types=media_types,
        )
        timestamp = processed_at if processed_at is not None else datetime.now(UTC)
        processing = adapted.processing_manifest(processed_at=timestamp)
        understanding = self._pipeline.understand_raw(
            document_id=document_id,
            content_hash=adapted.content_hash,
            processing=processing,
            raw_elements=adapted.raw_elements,
            source_revision=source_revision,
            metadata=adapted.metadata,
            base_quality=base_quality,
            regions=regions,
            assets=adapted.assets,
            additional_relations=additional_relations,
        )
        completion = self._completion_builder.build(
            document=understanding.document,
            boundary_set=understanding.boundary_set,
            grouping_result=understanding.grouping_result,
            hierarchy_result=understanding.hierarchy_result,
            integrity_report=understanding.integrity_report,
            quality_report=understanding.quality_report,
            region_result=understanding.region_result,
            semantic_status=understanding.semantic_status.value,
            semantic_result=understanding.semantic_result,
            adapter_diagnostics=adapted.diagnostics,
        )
        understanding = understanding.model_copy(update={"completion_report": completion})
        return AdaptedSourceUnderstandingResult(
            document_id=document_id,
            adapter_result=adapted,
            understanding=understanding,
        )

    @staticmethod
    def _validate_adapter_result(
        result: SourceAdapterResult,
        *,
        payload: bytes,
        adapter_name: str,
        adapter_version: str,
        media_types: tuple[str, ...],
    ) -> None:
        if result.protocol_version != SOURCE_ADAPTER_PROTOCOL_VERSION:
            raise AdapterError(
                "unsupported source adapter protocol_version: "
                f"{result.protocol_version!r} != {SOURCE_ADAPTER_PROTOCOL_VERSION!r}"
            )
        if result.adapter_name != adapter_name or result.adapter_version != adapter_version:
            raise AdapterError("source adapter result identity disagrees with active adapter")
        if result.media_type not in media_types:
            raise AdapterError(
                f"source adapter returned undeclared media_type {result.media_type!r}"
            )
        expected_hash = SourceAdapterResult.hash_bytes(payload)
        if result.content_hash != expected_hash:
            raise AdapterError(
                "source adapter content_hash does not match exact input bytes"
            )
