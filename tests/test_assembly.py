from __future__ import annotations

import unittest
from datetime import datetime, timezone

from source_understanding.assembly import AssemblyError, CanonicalDocumentAssembler
from source_understanding.relations.builder import RelationBuildPolicy, RelationBuildResult
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


def element(eid: str, order: int) -> Element:
    return Element(
        id=eid,
        type=ElementType.PARAGRAPH,
        order=order,
        raw_text=eid,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def unit(
    *,
    unit_type: LogicalUnitType = LogicalUnitType.TEXT_BLOCK,
    context: tuple[str, ...] = (),
) -> LogicalUnit:
    return LogicalUnit(
        id="u0",
        type=unit_type,
        element_ids=("e0", "e1"),
        context_node_ids=context,
        source=StructureSource.DERIVED,
        confidence=0.8,
    )


def processing(structure_version: str | None = None) -> ProcessingManifest:
    return ProcessingManifest(
        adapter_name="test-adapter",
        normalizer_version="1",
        structure_version=structure_version,
        processed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )


def stages(*, with_context: bool = False):
    elements = (element("e0", 0), element("e1", 1))
    node = (
        ContextNode(
            id="ctx",
            type="HEADING",
            label="Heading",
            level=1,
            source=StructureSource.EXPLICIT,
            confidence=0.9,
        )
        if with_context
        else None
    )
    context_nodes = (node,) if node is not None else ()
    paths = (("ctx",), ("ctx",)) if node is not None else ((), ())
    structure = (
        DocumentStructure(
            mode=StructureMode.LOCAL,
            source=StructureSource.DERIVED,
            confidence=0.6,
        )
        if node is not None
        else DocumentStructure()
    )

    grouping = GroupingResult(
        element_count=2,
        signal_version="1",
        boundary_version="1",
        policy=GroupingPolicy(),
        logical_units=(unit(),),
    )
    hierarchy = HierarchyResult(
        element_count=2,
        signal_version="1",
        boundary_version="1",
        policy=HierarchyPolicy(),
        context_nodes=context_nodes,
        assignments=tuple(
            ElementContextAssignment(
                element_id=item.id,
                context_node_ids=paths[index],
            )
            for index, item in enumerate(elements)
        ),
        structure=structure,
    )
    integration = ContextIntegrationResult(
        element_count=2,
        grouping_version="1",
        hierarchy_version="1",
        logical_units=(unit(context=paths[0] if paths[0] == paths[1] else ()),),
    )
    relations = RelationBuildResult(
        element_count=2,
        logical_unit_count=1,
        subdocument_count=0,
        policy=RelationBuildPolicy(),
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
            context_assigned_element_count=sum(bool(path) for path in paths),
            context_assignment_ratio=sum(bool(path) for path in paths) / 2,
            logical_unit_count=1,
            subdocument_count=0,
        ),
        quality=DocumentQuality(
            structure_quality=0.9,
            warnings=("structure-warning",),
            metrics={"structure_mode": structure.mode.value},
        ),
    )
    return elements, grouping, hierarchy, integration, relations, quality


class AssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assembler = CanonicalDocumentAssembler()

    def assemble(self, stage_values, **overrides):
        values = {
            "document_id": "doc",
            "content_hash": HASH,
            "processing": processing(),
            "elements": stage_values[0],
            "grouping_result": stage_values[1],
            "hierarchy_result": stage_values[2],
            "integration_result": stage_values[3],
            "relation_result": stage_values[4],
            "quality_report": stage_values[5],
        }
        values.update(overrides)
        return self.assembler.assemble(**values)

    def test_assembles_valid_document_and_stamps_structure_version(self) -> None:
        stage_values = stages(with_context=True)
        document = self.assemble(
            stage_values,
            metadata=DocumentMetadata(title="Example"),
            assets=(Asset(id="asset", type="image"),),
        )
        self.assertEqual(document.processing.structure_version, "1")
        self.assertEqual(document.metadata.title, "Example")
        self.assertEqual(document.logical_units[0].context_node_ids, ("ctx",))
        self.assertEqual(document.context_nodes[0].id, "ctx")
        self.assertEqual(document.assets[0].id, "asset")

    def test_merges_structure_quality_without_losing_adapter_quality(self) -> None:
        stage_values = stages()
        document = self.assemble(
            stage_values,
            base_quality=DocumentQuality(
                text_quality=0.95,
                order_quality=1.0,
                warnings=("adapter-warning",),
                metrics={"adapter_metric": 7},
            ),
        )
        self.assertEqual(document.quality.text_quality, 0.95)
        self.assertEqual(document.quality.structure_quality, 0.9)
        self.assertEqual(
            document.quality.warnings,
            ("adapter-warning", "structure-warning"),
        )
        self.assertEqual(document.quality.metrics["adapter_metric"], 7)

    def test_rejects_conflicting_structure_versions(self) -> None:
        with self.assertRaises(AssemblyError):
            self.assemble(stages(), processing=processing("legacy"))

    def test_rejects_stage_count_or_version_drift(self) -> None:
        stage_values = list(stages())
        stage_values[4] = RelationBuildResult(
            element_count=3,
            logical_unit_count=1,
            subdocument_count=0,
            policy=RelationBuildPolicy(),
            relations=(),
        )
        with self.assertRaises(AssemblyError):
            self.assemble(stage_values)

        stage_values = list(stages())
        stage_values[2] = stage_values[2].model_copy(update={"signal_version": "2"})
        with self.assertRaises(AssemblyError):
            self.assemble(stage_values)

    def test_rejects_context_integration_that_changes_non_context_fields(self) -> None:
        stage_values = list(stages())
        stage_values[3] = ContextIntegrationResult(
            element_count=2,
            grouping_version="1",
            hierarchy_version="1",
            logical_units=(unit(unit_type=LogicalUnitType.UNKNOWN_GROUP),),
        )
        with self.assertRaises(AssemblyError):
            self.assemble(stage_values)

    def test_rejects_hierarchy_assignment_order_drift(self) -> None:
        stage_values = list(stages())
        hierarchy = stage_values[2]
        stage_values[2] = HierarchyResult(
            element_count=2,
            signal_version="1",
            boundary_version="1",
            policy=HierarchyPolicy(),
            assignments=tuple(reversed(hierarchy.assignments)),
            structure=DocumentStructure(),
        )
        with self.assertRaises(AssemblyError):
            self.assemble(stage_values)

    def test_rejects_semantic_or_dangling_additional_relations(self) -> None:
        semantic = Relation(
            id="semantic",
            layer=RelationLayer.SEMANTIC,
            type=RelationType.SAME_TOPIC,
            source_id="e0",
            target_id="e1",
            confidence=0.7,
            source=StructureSource.INFERRED,
        )
        with self.assertRaises(AssemblyError):
            self.assemble(stages(), additional_relations=(semantic,))

        dangling = Relation(
            id="dangling",
            layer=RelationLayer.STRUCTURAL,
            type=RelationType.NEXT,
            source_id="missing",
            target_id="e1",
            confidence=1.0,
            source=StructureSource.DERIVED,
        )
        with self.assertRaises(AssemblyError):
            self.assemble(stages(), additional_relations=(dangling,))

    def test_deterministic(self) -> None:
        stage_values = stages()
        self.assertEqual(
            self.assemble(stage_values),
            self.assemble(stage_values),
        )


if __name__ == "__main__":
    unittest.main()
