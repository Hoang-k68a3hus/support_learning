from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import TypeVar

from pydantic import Field, model_validator

from source_understanding.assembly import CanonicalDocumentAssembler
from source_understanding.profiling.content_profiler import ContentProfile, ContentProfiler
from source_understanding.relations.builder import RelationBuildResult, StructuralRelationBuilder
from source_understanding.schemas.context import Identifier, SchemaModel
from source_understanding.schemas.document import (
    Asset,
    CanonicalDocument,
    ContentRegion,
    DocumentMetadata,
    DocumentQuality,
    ProcessingManifest,
)
from source_understanding.schemas.element import Element
from source_understanding.schemas.relation import Relation
from source_understanding.semantics.annotator import (
    SemanticAnnotationResult,
    SemanticAnnotator,
)
from source_understanding.structure.boundary import BoundaryScorer, BoundarySet
from source_understanding.structure.grouping import GroupingResult, LogicalGroupBuilder
from source_understanding.structure.hierarchy import HierarchyBuilder, HierarchyResult
from source_understanding.structure.integration import ContextIntegrationResult, ContextIntegrator
from source_understanding.structure.quality import (
    StructureQualityEstimator,
    StructureQualityReport,
)
from source_understanding.structure.signals import StructureSignalExtractor, StructureSignalSet


SOURCE_UNDERSTANDING_PIPELINE_VERSION = "1"
T = TypeVar("T")


class SourceUnderstandingPipelineError(ValueError):
    """One source-understanding stage failed or violated a stage boundary."""


class SemanticFailureMode(StrEnum):
    KEEP_STRUCTURAL = "KEEP_STRUCTURAL"
    RAISE = "RAISE"


class SemanticStageStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    COMPLETED = "COMPLETED"
    FAILED_OPTIONAL = "FAILED_OPTIONAL"


class SourceUnderstandingPipelinePolicy(SchemaModel):
    version: str = Field(
        default=SOURCE_UNDERSTANDING_PIPELINE_VERSION,
        min_length=1,
        max_length=128,
    )
    semantic_failure_mode: SemanticFailureMode = SemanticFailureMode.KEEP_STRUCTURAL


class SourceUnderstandingResult(SchemaModel):
    version: str = SOURCE_UNDERSTANDING_PIPELINE_VERSION
    document_id: Identifier
    content_profile: ContentProfile
    signal_set: StructureSignalSet
    boundary_set: BoundarySet
    grouping_result: GroupingResult
    hierarchy_result: HierarchyResult
    integration_result: ContextIntegrationResult
    relation_result: RelationBuildResult
    quality_report: StructureQualityReport
    structural_document: CanonicalDocument
    document: CanonicalDocument
    semantic_status: SemanticStageStatus
    semantic_result: SemanticAnnotationResult | None = None
    semantic_error: str | None = Field(default=None, max_length=8192)

    @model_validator(mode="after")
    def validate_result(self) -> "SourceUnderstandingResult":
        if self.structural_document.document_id != self.document_id:
            raise ValueError("structural_document document_id does not match pipeline result")
        if self.document.document_id != self.document_id:
            raise ValueError("final document_id does not match pipeline result")
        if self.document.content_hash != self.structural_document.content_hash:
            raise ValueError("semantic stage cannot change canonical content_hash")
        if self.document.source_revision != self.structural_document.source_revision:
            raise ValueError("semantic stage cannot change canonical source_revision")

        if self.semantic_status == SemanticStageStatus.COMPLETED:
            if self.semantic_result is None or self.semantic_error is not None:
                raise ValueError("completed semantic stage requires result and no error")
        elif self.semantic_status == SemanticStageStatus.FAILED_OPTIONAL:
            if self.semantic_result is not None or not self.semantic_error:
                raise ValueError("failed optional semantic stage requires error and no result")
            if self.document != self.structural_document:
                raise ValueError("failed optional semantic stage must keep structural document")
        elif self.semantic_status == SemanticStageStatus.NOT_CONFIGURED:
            if self.semantic_result is not None or self.semantic_error is not None:
                raise ValueError("unconfigured semantic stage cannot carry result/error")
            if self.document != self.structural_document:
                raise ValueError("unconfigured semantic stage must keep structural document")
        return self


class SourceUnderstandingPipeline:
    """Orchestrate deterministic document understanding from canonical Elements.

    Retrieval, indexing, embeddings, reranking, generation, and citation are
    deliberately outside this class. Its terminal artifact is a validated
    CanonicalDocument with optional semantic enrichment.
    """

    version = SOURCE_UNDERSTANDING_PIPELINE_VERSION

    def __init__(
        self,
        *,
        profiler: ContentProfiler | None = None,
        signal_extractor: StructureSignalExtractor | None = None,
        boundary_scorer: BoundaryScorer | None = None,
        group_builder: LogicalGroupBuilder | None = None,
        hierarchy_builder: HierarchyBuilder | None = None,
        context_integrator: ContextIntegrator | None = None,
        relation_builder: StructuralRelationBuilder | None = None,
        quality_estimator: StructureQualityEstimator | None = None,
        assembler: CanonicalDocumentAssembler | None = None,
        semantic_annotator: SemanticAnnotator | None = None,
        policy: SourceUnderstandingPipelinePolicy | None = None,
    ) -> None:
        self._profiler = profiler if profiler is not None else ContentProfiler()
        self._signal_extractor = (
            signal_extractor if signal_extractor is not None else StructureSignalExtractor()
        )
        self._boundary_scorer = boundary_scorer if boundary_scorer is not None else BoundaryScorer()
        self._group_builder = group_builder if group_builder is not None else LogicalGroupBuilder()
        self._hierarchy_builder = (
            hierarchy_builder if hierarchy_builder is not None else HierarchyBuilder()
        )
        self._context_integrator = (
            context_integrator if context_integrator is not None else ContextIntegrator()
        )
        self._relation_builder = (
            relation_builder if relation_builder is not None else StructuralRelationBuilder()
        )
        self._quality_estimator = (
            quality_estimator if quality_estimator is not None else StructureQualityEstimator()
        )
        self._assembler = assembler if assembler is not None else CanonicalDocumentAssembler()
        self._semantic_annotator = semantic_annotator
        self._policy = policy if policy is not None else SourceUnderstandingPipelinePolicy()

    def understand(
        self,
        *,
        document_id: str,
        content_hash: str,
        processing: ProcessingManifest,
        elements: Sequence[Element],
        source_revision: str | None = None,
        metadata: DocumentMetadata | None = None,
        base_quality: DocumentQuality | None = None,
        regions: Sequence[ContentRegion] = (),
        assets: Sequence[Asset] = (),
        additional_relations: Sequence[Relation] = (),
    ) -> SourceUnderstandingResult:
        element_snapshot = tuple(elements)
        region_snapshot = tuple(regions)
        asset_snapshot = tuple(assets)
        extra_relation_snapshot = tuple(additional_relations)
        self._validate_source_identity(document_id, content_hash)

        content_profile = self._stage(
            "content profiling",
            lambda: self._profiler.analyze(element_snapshot),
        )
        signal_set = self._stage(
            "structure signal extraction",
            lambda: self._signal_extractor.extract(element_snapshot),
        )
        boundary_set = self._stage(
            "boundary scoring",
            lambda: self._boundary_scorer.score(element_snapshot, signal_set),
        )
        grouping_result = self._stage(
            "logical grouping",
            lambda: self._group_builder.build(element_snapshot, signal_set, boundary_set),
        )
        hierarchy_result = self._stage(
            "hierarchy understanding",
            lambda: self._hierarchy_builder.build(element_snapshot, signal_set, boundary_set),
        )
        integration_result = self._stage(
            "context integration",
            lambda: self._context_integrator.integrate(grouping_result, hierarchy_result),
        )
        relation_result = self._stage(
            "structural relation building",
            lambda: self._relation_builder.build(
                element_snapshot,
                integration_result.logical_units,
                grouping_result.subdocuments,
            ),
        )
        quality_report = self._stage(
            "structure quality estimation",
            lambda: self._quality_estimator.estimate(
                element_snapshot,
                boundary_set,
                grouping_result,
                hierarchy_result,
            ),
        )

        self._validate_stage_counts(
            len(element_snapshot),
            content_profile,
            signal_set,
            boundary_set,
            grouping_result,
            hierarchy_result,
            integration_result,
            relation_result,
            quality_report,
        )
        processing_with_manifest = self._processing_with_pipeline_manifest(
            processing,
            content_profile,
            signal_set,
            boundary_set,
            grouping_result,
            hierarchy_result,
            integration_result,
            relation_result,
            quality_report,
        )
        structural_document = self._stage(
            "canonical assembly",
            lambda: self._assembler.assemble(
                document_id=document_id,
                content_hash=content_hash,
                source_revision=source_revision,
                processing=processing_with_manifest,
                metadata=metadata,
                elements=element_snapshot,
                grouping_result=grouping_result,
                hierarchy_result=hierarchy_result,
                integration_result=integration_result,
                relation_result=relation_result,
                quality_report=quality_report,
                base_quality=base_quality,
                regions=region_snapshot,
                assets=asset_snapshot,
                additional_relations=extra_relation_snapshot,
            ),
        )

        final_document = structural_document
        semantic_status = SemanticStageStatus.NOT_CONFIGURED
        semantic_result: SemanticAnnotationResult | None = None
        semantic_error: str | None = None

        if self._semantic_annotator is not None:
            try:
                semantic_result = self._semantic_annotator.annotate(structural_document)
                self._validate_semantic_boundary(
                    structural_document,
                    semantic_result.document,
                )
            except Exception as exc:
                if self._policy.semantic_failure_mode == SemanticFailureMode.RAISE:
                    raise SourceUnderstandingPipelineError(
                        f"semantic enrichment failed: {exc}"
                    ) from exc
                semantic_status = SemanticStageStatus.FAILED_OPTIONAL
                semantic_error = self._diagnostic_message(exc)
                semantic_result = None
            else:
                semantic_status = SemanticStageStatus.COMPLETED
                final_document = semantic_result.document

        return SourceUnderstandingResult(
            document_id=document_id,
            content_profile=content_profile,
            signal_set=signal_set,
            boundary_set=boundary_set,
            grouping_result=grouping_result,
            hierarchy_result=hierarchy_result,
            integration_result=integration_result,
            relation_result=relation_result,
            quality_report=quality_report,
            structural_document=structural_document,
            document=final_document,
            semantic_status=semantic_status,
            semantic_result=semantic_result,
            semantic_error=semantic_error,
        )

    def _processing_with_pipeline_manifest(
        self,
        processing: ProcessingManifest,
        content_profile: ContentProfile,
        signal_set: StructureSignalSet,
        boundary_set: BoundarySet,
        grouping_result: GroupingResult,
        hierarchy_result: HierarchyResult,
        integration_result: ContextIntegrationResult,
        relation_result: RelationBuildResult,
        quality_report: StructureQualityReport,
    ) -> ProcessingManifest:
        configuration = dict(processing.configuration)
        configuration["source_understanding_pipeline"] = {
            "pipeline_version": self.version,
            "policy": self._policy.model_dump(mode="json"),
            "content_profiler_version": content_profile.version,
            "structure_signal_version": signal_set.version,
            "boundary_version": boundary_set.version,
            "boundary_policy": boundary_set.policy.model_dump(mode="json"),
            "grouping_version": grouping_result.version,
            "grouping_policy": grouping_result.policy.model_dump(mode="json"),
            "hierarchy_version": hierarchy_result.version,
            "hierarchy_policy": hierarchy_result.policy.model_dump(mode="json"),
            "context_integration_version": integration_result.version,
            "relation_builder_version": relation_result.version,
            "relation_policy": relation_result.policy.model_dump(mode="json"),
            "structure_quality_version": quality_report.version,
            "structure_quality_policy": quality_report.policy.model_dump(mode="json"),
            "assembly_version": getattr(self._assembler, "version", "unknown"),
        }
        data = processing.model_dump(mode="python")
        data["configuration"] = configuration
        return ProcessingManifest.model_validate(data)

    @staticmethod
    def _validate_stage_counts(
        expected: int,
        content_profile: ContentProfile,
        signal_set: StructureSignalSet,
        boundary_set: BoundarySet,
        grouping_result: GroupingResult,
        hierarchy_result: HierarchyResult,
        integration_result: ContextIntegrationResult,
        relation_result: RelationBuildResult,
        quality_report: StructureQualityReport,
    ) -> None:
        counts = {
            "content_profile": content_profile.element_count,
            "signals": signal_set.element_count,
            "boundaries": boundary_set.element_count,
            "grouping": grouping_result.element_count,
            "hierarchy": hierarchy_result.element_count,
            "integration": integration_result.element_count,
            "relations": relation_result.element_count,
            "quality": quality_report.metrics.element_count,
        }
        mismatched = {name: count for name, count in counts.items() if count != expected}
        if mismatched:
            raise SourceUnderstandingPipelineError(
                f"source-understanding stage element_count mismatch: expected {expected}, "
                f"got {mismatched}"
            )

    @staticmethod
    def _validate_semantic_boundary(
        structural: CanonicalDocument,
        enriched: CanonicalDocument,
    ) -> None:
        immutable_fields = (
            "schema_version",
            "document_id",
            "content_hash",
            "source_revision",
            "metadata",
            "structure",
            "elements",
            "regions",
            "logical_units",
            "context_nodes",
            "relations",
            "assets",
            "subdocuments",
            "quality",
        )
        changed = [
            field_name
            for field_name in immutable_fields
            if getattr(structural, field_name) != getattr(enriched, field_name)
        ]
        if changed:
            raise SourceUnderstandingPipelineError(
                "semantic stage mutated canonical source/structure fields: "
                f"{changed}"
            )

        processing_fields = (
            "adapter_name",
            "adapter_version",
            "normalizer_version",
            "structure_version",
            "processed_at",
        )
        changed_processing = [
            field_name
            for field_name in processing_fields
            if getattr(structural.processing, field_name)
            != getattr(enriched.processing, field_name)
        ]
        if changed_processing:
            raise SourceUnderstandingPipelineError(
                "semantic stage mutated non-semantic processing identity: "
                f"{changed_processing}"
            )

        structural_config = dict(structural.processing.configuration)
        enriched_config = dict(enriched.processing.configuration)
        enriched_config.pop("semantic_understanding", None)
        if structural_config != enriched_config:
            raise SourceUnderstandingPipelineError(
                "semantic stage mutated processing configuration outside its namespace"
            )

    @staticmethod
    def _validate_source_identity(document_id: str, content_hash: str) -> None:
        if not isinstance(document_id, str) or not document_id.strip():
            raise SourceUnderstandingPipelineError("document_id must be a non-blank string")
        if not isinstance(content_hash, str) or not content_hash.strip():
            raise SourceUnderstandingPipelineError("content_hash must be a non-blank string")

    @staticmethod
    def _diagnostic_message(exc: Exception) -> str:
        message = f"{type(exc).__name__}: {exc}"
        return message[:8192]

    @staticmethod
    def _stage(name: str, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except SourceUnderstandingPipelineError:
            raise
        except Exception as exc:
            raise SourceUnderstandingPipelineError(f"{name} failed: {exc}") from exc
