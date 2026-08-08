from __future__ import annotations

import unittest
from datetime import datetime, timezone

from source_understanding.assembly import AssemblyError, CanonicalDocumentAssembler
from source_understanding.relations.builder import RelationBuildResult
from source_understanding.schemas.context import ContextNode, StructureMode, StructureSource
from source_understanding.schemas.document import (
    Asset,
    DocumentMetadata,
    DocumentQuality,
    DocumentStructure,
    ProcessingManifest,
)
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.schemas.relation import Relation, RelationLayer, RelationType
from source_understanding.structure.boundary import BoundaryPolicy
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.hierarchy import (
    ElementContextAssignment,
    HierarchyPolicy,
    HierarchyResult,
)
from source_understanding.structure.integration import ContextIntegrationResult
from source_understanding.structure.quality import (
    StructureQualityMetrics,
    StructureQualityPolicy,
    StructureQualityReport,
)


HASH = "sha256:" + "a" * 64


def element(eid: str, order: int, etype: ElementType = ElementType.PARAGRAPH) -> Element:
    return Element(
        id=eid,
        type=etype,
        order=order,
        raw_text=eid,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def unit(uid: str, ids: tuple[str, ...], context: tuple[str, ...] = ()) -> LogicalUnit:
    return LogicalUnit(
        id=uid,
        type=LogicalUnitType.TEXT_BLOCK,
        element_ids=ids,
        context_node_ids=context,
        source=StructureSource.DERIVED,
        confidence=0.8,
    )


def fixture(
    *,
    structure: DocumentStructure | None = None,
    context_nodes: tuple[ContextNode, ...] = (),
    paths: tuple[tuple[str, ...], ...] | None = None,
):
    elements = (element("e0", 0), element("e1", 1))
    base_unit = unit("u0", ("e0", "e1"))
    grouping = GroupingResult(
        element_count=2,
        signal_version="1",
        boundary_version="1",
        policy=GroupingPolicy(),
        logical_units=(base_unit,),
    )
    resolved_paths = paths if paths is not None else ((), ())
    hierarchy = HierarchyResult(
        element_count=2,
        signal_version="1",
        boundary_version="1",
        policy=HierarchyPolicy(),
        context_nodes=context_nodes,
        assignments=tuple(
            ElementContextAssignment(
                element_id=item.id,
                context_node_ids=resolved_paths[index],
            )
            for index, item in enumerate(elements)
        ),
        structure=structure if structure is not None else DocumentStructure(),
    )
    integrated_unit = unit(
        "u0",
        ("e0", "e1"),
        context=resolved_paths[0] if resolved_paths[0] == resolved_paths[1] else (),
    )
    integration = ContextIntegrationResult(
        element_count=2,
        grouping_version="1",
        hierarchy_version="1",
        logical_units=(integrated_unit,),
    )
    relations = RelationBuildResult(
        element_count=2,
        logical_unit_count=1,
        subdocument_count=0,
        relations=(),
    )
    quality = StructureQualityReport(
        policy=StructureQualityPolicy(),
        metrics=StructureQualityMetrics(
            element_count=2,
            grouped_element_count=2,
            context_anchor_count=0,
            structurally_accounted_count=2,
            structurally_accounted_ratio=1.0,
            unknown_element_count=0,
            unknown_element_ratio=0.0,
            boundary_count=1,
            unknown_boundary_count=0,
            boundary_certainty_ratio=1.0,
            unresolved_integrity_count=0,
            integrity_resolution_ratio=1.0,
            context_node_count=len(context_nodes),
            context_assigned_element_count=sum(bool(path) for path in resolved_paths),
            context_assignment_ratio=sum(bool(path) for path in resolved_paths) / 2,
            logical_unit_count=1,
            subdocument_count=0,
        ),
        quality=DocumentQuality(
            structure_quality=0.9,
            warnings=("structure-warning",),
            metrics={
                "structure_mode": (
                    structure.mode.value
                    if structure is not None
                    else StructureMode.UNKNOWN.value
                ),
                "structure_quality_version": "1",
            },
        ),
    )
    return elements, grouping, hierarchy, integration, relations, quality


def processing(structure_version: str | None = None) -> ProcessingManifest:
    return ProcessingManifest(
        adapter_name="test-adapter",
        normalizer_version="1",
        structure_version=structure_version,
        processed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )


class AssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assembler = CanonicalDocumentAssembler()

    def test_assembles_valid_canonical_document_and_stamps_structure_version(self) -> None:
        stages = fixture()
        document = self.assembler.assemble(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=stages[0],
            grouping_result=stages[1],
            hierarchy_result=stages[2],
            integration_result=stages[3],
            relation_result=stages[4],
            quality_report=stages[5],
            metadata=DocumentMetadata(title="Example"),
        )
        self.assertEqual(document.processing.structure_version, "1")
        self.assertEqual(document.metadata.title, "Example")
        self.assertEqual(document.logical_units, stages[3].logical_units)
        self.assertEqual(document.structure.mode, StructureMode.UNKNOWN)
        self.assertEqual(document.quality.structure_quality, 0.9)

    def test_preserves_base_quality_while_merging_structure_quality(self) -> None:
        stages = fixture()
        base = DocumentQuality(
            text_quality=0.95,
            order_quality=1.0,
            warnings=("adapter-warning",),
            metrics={"adapter_metric": 7},
        )
        document = self.assembler.assemble(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=stages[0],
            grouping_result=stages[1],
            hierarchy_result=stages[2],
            integration_result=stages[3],
            relation_result=stages[4],
            quality_report=stages[5],
            base_quality=base,
        )
        self.assertEqual(document.quality.text_quality, 0.95)
        self.assertEqual(document.quality.order_quality, 1.0)
        self.assertEqual(document.quality.structure_quality, 0.9)
        self.assertEqual(
            document.quality.warnings,
            ("adapter-warning", "structure-warning"),
        )
        self.assertEqual(document.quality.metrics["adapter_metric"], 7)

    def test_rejects_conflicting_base_structure_quality(self) -> None:
        stages = fixture()
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
                base_quality=DocumentQuality(structure_quality=0.1),
            )

    def test_rejects_conflicting_processing_structure_version(self) -> None:
        stages = fixture()
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing("legacy"),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
            )

    def test_rejects_stage_element_count_mismatch(self) -> None:
        stages = list(fixture())
        stages[4] = RelationBuildResult(
            element_count=3,
            logical_unit_count=1,
            subdocument_count=0,
            relations=(),
        )
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
            )

    def test_rejects_signal_version_drift_between_grouping_and_hierarchy(self) -> None:
        stages = list(fixture())
        stages[2] = stages[2].model_copy(update={"signal_version": "2"})
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
            )

    def test_rejects_context_integration_that_mutates_non_context_fields(self) -> None:
        stages = list(fixture())
        changed = LogicalUnit(
            id="u0",
            type=LogicalUnitType.UNKNOWN_GROUP,
            element_ids=("e0", "e1"),
            source=StructureSource.DERIVED,
            confidence=0.8,
        )
        stages[3] = ContextIntegrationResult(
            element_count=2,
            grouping_version="1",
            hierarchy_version="1",
            logical_units=(changed,),
        )
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
            )

    def test_rejects_hierarchy_assignment_order_drift(self) -> None:
        stages = list(fixture())
        stages[2] = HierarchyResult(
            element_count=2,
            signal_version="1",
            boundary_version="1",
            policy=HierarchyPolicy(),
            assignments=tuple(reversed(stages[2].assignments)),
            structure=DocumentStructure(),
        )
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
            )

    def test_preserves_assets_and_context_nodes(self) -> None:
        node = ContextNode(
            id="ctx",
            type="HEADING",
            label="Heading",
            level=1,
            source=StructureSource.EXPLICIT,
            confidence=0.9,
        )
        structure = DocumentStructure(
            mode=StructureMode.LOCAL,
            source=StructureSource.DERIVED,
            confidence=0.6,
        )
        stages = fixture(
            structure=structure,
            context_nodes=(node,),
            paths=(("ctx",), ("ctx",)),
        )
        document = self.assembler.assemble(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=stages[0],
            grouping_result=stages[1],
            hierarchy_result=stages[2],
            integration_result=stages[3],
            relation_result=stages[4],
            quality_report=stages[5],
            assets=(Asset(id="asset", type="image"),),
        )
        self.assertEqual(document.context_nodes, (node,))
        self.assertEqual(document.assets[0].id, "asset")
        self.assertEqual(document.logical_units[0].context_node_ids, ("ctx",))

    def test_rejects_semantic_additional_relation_before_semantic_stage(self) -> None:
        stages = fixture()
        semantic = Relation(
            id="r",
            layer=RelationLayer.SEMANTIC,
            type=RelationType.SAME_TOPIC,
            source_id="e0",
            target_id="e1",
            confidence=0.7,
            source=StructureSource.INFERRED,
        )
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
                additional_relations=(semantic,),
            )

    def test_final_canonical_validation_rejects_dangling_additional_relation(self) -> None:
        stages = fixture()
        dangling = Relation(
            id="r",
            layer=RelationLayer.STRUCTURAL,
            type=RelationType.NEXT,
            source_id="missing",
            target_id="e1",
            confidence=1.0,
            source=StructureSource.DERIVED,
        )
        with self.assertRaises(AssemblyError):
            self.assembler.assemble(
                document_id="doc",
                content_hash=HASH,
                processing=processing(),
                elements=stages[0],
                grouping_result=stages[1],
                hierarchy_result=stages[2],
                integration_result=stages[3],
                relation_result=stages[4],
                quality_report=stages[5],
                additional_relations=(dangling,),
            )

    def test_deterministic(self) -> None:
        stages = fixture()
        kwargs = dict(
            document_id="doc",
            content_hash=HASH,
            processing=processing(),
            elements=stages[0],
            grouping_result=stages[1],
            hierarchy_result=stages[2],
            integration_result=stages[3],
            relation_result=stages[4],
            quality_report=stages[5],
        )
        self.assertEqual(
            self.assembler.assemble(**kwargs),
            self.assembler.assemble(**kwargs),
        )


if __name__ == "__main__":
    unittest.main()
