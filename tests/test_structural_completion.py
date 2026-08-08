from __future__ import annotations

import unittest

from source_understanding.relations.builder import RelationBuildError, StructuralRelationBuilder
from source_understanding.schemas.context import ContextNode, StructureMode, StructureSource
from source_understanding.schemas.document import DocumentStructure, SubDocument
from source_understanding.schemas.element import Element, ElementType, Provenance
from source_understanding.schemas.logical_unit import LogicalUnit, LogicalUnitType
from source_understanding.schemas.relation import RelationType
from source_understanding.structure.boundary import (
    BoundaryClass,
    BoundaryDecision,
    BoundaryPolicy,
    BoundaryReason,
    BoundarySet,
)
from source_understanding.structure.grouping import GroupingPolicy, GroupingResult
from source_understanding.structure.hierarchy import (
    ElementContextAssignment,
    HierarchyPolicy,
    HierarchyResult,
)
from source_understanding.structure.integration import ContextIntegrationError, ContextIntegrator
from source_understanding.structure.quality import StructureQualityError, StructureQualityEstimator


def element(eid: str, order: int, etype: ElementType = ElementType.PARAGRAPH) -> Element:
    return Element(
        id=eid,
        order=order,
        type=etype,
        raw_text=eid,
        provenance=Provenance(source=StructureSource.EXPLICIT, extractor="test"),
    )


def unit(
    uid: str,
    ids: tuple[str, ...],
    utype: LogicalUnitType = LogicalUnitType.TEXT_BLOCK,
    *,
    source: StructureSource = StructureSource.DERIVED,
    confidence: float = 0.9,
    context: tuple[str, ...] = (),
) -> LogicalUnit:
    return LogicalUnit(
        id=uid,
        type=utype,
        element_ids=ids,
        context_node_ids=context,
        source=source,
        confidence=confidence,
    )


def grouping(
    elements: tuple[Element, ...],
    units: tuple[LogicalUnit, ...],
    *,
    subdocs: tuple[SubDocument, ...] = (),
    ungrouped: tuple[str, ...] = (),
) -> GroupingResult:
    return GroupingResult(
        element_count=len(elements),
        signal_version="1",
        boundary_version="1",
        policy=GroupingPolicy(),
        logical_units=units,
        subdocuments=subdocs,
        ungrouped_element_ids=ungrouped,
    )


def hierarchy(
    elements: tuple[Element, ...],
    paths: dict[str, tuple[str, ...]],
    nodes: tuple[ContextNode, ...] = (),
    mode: StructureMode = StructureMode.UNKNOWN,
) -> HierarchyResult:
    structure = (
        DocumentStructure()
        if mode == StructureMode.UNKNOWN
        else DocumentStructure(mode=mode, source=StructureSource.DERIVED, confidence=0.8)
    )
    return HierarchyResult(
        element_count=len(elements),
        signal_version="1",
        boundary_version="1",
        policy=HierarchyPolicy(),
        context_nodes=nodes,
        assignments=tuple(
            ElementContextAssignment(
                element_id=item.id,
                context_node_ids=paths.get(item.id, ()),
            )
            for item in elements
        ),
        structure=structure,
    )


def boundaries(
    elements: tuple[Element, ...],
    classes: tuple[BoundaryClass, ...] | None = None,
    unresolved: tuple[int, ...] = (),
) -> BoundarySet:
    resolved = classes or (BoundaryClass.SOFT,) * max(0, len(elements) - 1)
    return BoundarySet(
        element_count=len(elements),
        signal_version="1",
        policy=BoundaryPolicy(),
        boundaries=tuple(
            BoundaryDecision(
                id=f"b{index}",
                left_element_id=elements[index].id,
                right_element_id=elements[index + 1].id,
                classification=classification,
                score=0.0,
                reasons=(BoundaryReason.CONTENT_INTEGRITY_UNRESOLVED,)
                if index in unresolved
                else (),
            )
            for index, classification in enumerate(resolved)
        ),
    )


class ContextIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.integrator = ContextIntegrator()
        self.elements = (element("e0", 0), element("e1", 1), element("e2", 2))
        self.root = ContextNode(
            id="c0",
            type="TITLE",
            label="Root",
            level=0,
            source=StructureSource.EXPLICIT,
            confidence=0.9,
            attributes={"anchor_element_id": "e0"},
        )
        self.left = ContextNode(
            id="c1",
            type="HEADING",
            label="Left",
            level=1,
            parent_id="c0",
            source=StructureSource.EXPLICIT,
            confidence=0.9,
        )
        self.right = ContextNode(
            id="c2",
            type="HEADING",
            label="Right",
            level=1,
            parent_id="c0",
            source=StructureSource.EXPLICIT,
            confidence=0.9,
        )

    def test_common_context_is_longest_common_prefix(self) -> None:
        grouped = grouping(self.elements, (unit("u0", ("e1", "e2")),), ungrouped=("e0",))
        hierarchy_result = hierarchy(
            self.elements,
            {"e0": ("c0",), "e1": ("c0", "c1"), "e2": ("c0", "c2")},
            (self.root, self.left, self.right),
            StructureMode.HIERARCHICAL,
        )
        result = self.integrator.integrate(grouped, hierarchy_result)
        self.assertEqual(result.logical_units[0].context_node_ids, ("c0",))

    def test_same_subsection_keeps_full_shared_path(self) -> None:
        grouped = grouping(self.elements, (unit("u0", ("e1", "e2")),), ungrouped=("e0",))
        hierarchy_result = hierarchy(
            self.elements,
            {"e0": ("c0",), "e1": ("c0", "c1"), "e2": ("c0", "c1")},
            (self.root, self.left),
            StructureMode.HIERARCHICAL,
        )
        result = self.integrator.integrate(grouped, hierarchy_result)
        self.assertEqual(result.logical_units[0].context_node_ids, ("c0", "c1"))

    def test_existing_conflicting_context_is_rejected(self) -> None:
        grouped = grouping(
            self.elements,
            (unit("u0", ("e1",), context=("c0",)),),
            ungrouped=("e0", "e2"),
        )
        hierarchy_result = hierarchy(
            self.elements,
            {"e1": ("c0", "c1")},
            (self.root, self.left),
            StructureMode.HIERARCHICAL,
        )
        with self.assertRaises(ContextIntegrationError):
            self.integrator.integrate(grouped, hierarchy_result)

    def test_invalid_assignment_path_is_rejected(self) -> None:
        grouped = grouping(self.elements, (unit("u0", ("e1",)),), ungrouped=("e0", "e2"))
        hierarchy_result = hierarchy(
            self.elements,
            {"e1": ("c1", "c0")},
            (self.root, self.left),
            StructureMode.HIERARCHICAL,
        )
        with self.assertRaises(ContextIntegrationError):
            self.integrator.integrate(grouped, hierarchy_result)


class StructuralRelationBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = StructuralRelationBuilder()
        self.elements = (
            element("q", 0, ElementType.QUESTION),
            element("a", 1, ElementType.ANSWER),
            element("p", 2),
        )
        self.qa = unit(
            "qa",
            ("q", "a"),
            LogicalUnitType.QA_PAIR,
            source=StructureSource.INFERRED,
            confidence=0.8,
        )
        self.text = unit("txt", ("p",))

    def test_builds_only_grounded_structural_relations(self) -> None:
        subdoc = SubDocument(
            id="sd",
            element_ids=("q", "a", "p"),
            confidence=0.85,
            source=StructureSource.INFERRED,
        )
        result = self.builder.build(self.elements, (self.qa, self.text), (subdoc,))
        self.assertEqual(len(result.relations), 8)
        types = [relation.type for relation in result.relations]
        self.assertEqual(types.count(RelationType.NEXT), 2)
        self.assertEqual(types.count(RelationType.PART_OF), 5)
        self.assertEqual(types.count(RelationType.QUESTION_ANSWER), 1)
        self.assertTrue(
            all(
                relation.type not in {RelationType.SAME_TOPIC, RelationType.CONTINUES}
                for relation in result.relations
            )
        )
        qa_relation = next(
            relation
            for relation in result.relations
            if relation.type == RelationType.QUESTION_ANSWER
        )
        self.assertEqual((qa_relation.source_id, qa_relation.target_id), ("q", "a"))
        self.assertEqual(qa_relation.source, StructureSource.INFERRED)
        self.assertEqual(qa_relation.confidence, 0.8)

    def test_partial_subdocument_intersection_is_rejected(self) -> None:
        crossing = unit("cross", ("a", "p"))
        subdoc = SubDocument(
            id="sd",
            element_ids=("q", "a"),
            confidence=0.8,
            source=StructureSource.INFERRED,
        )
        with self.assertRaises(RelationBuildError):
            self.builder.build(self.elements, (crossing,), (subdoc,))

    def test_malformed_qa_pair_is_rejected(self) -> None:
        malformed = unit("qa3", ("q", "a", "p"), LogicalUnitType.QA_PAIR)
        with self.assertRaises(RelationBuildError):
            self.builder.build(self.elements, (malformed,))

    def test_relation_ids_and_order_are_deterministic(self) -> None:
        first = self.builder.build(self.elements, (self.qa, self.text))
        second = self.builder.build(self.elements, (self.qa, self.text))
        self.assertEqual(first, second)


class StructureQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.estimator = StructureQualityEstimator()

    def test_flat_typed_source_is_not_penalized_for_lacking_hierarchy(self) -> None:
        elements = (element("e0", 0), element("e1", 1))
        grouped = grouping(elements, (unit("u", ("e0", "e1")),))
        hierarchy_result = hierarchy(elements, {}, (), StructureMode.UNKNOWN)
        report = self.estimator.estimate(
            elements,
            boundaries(elements),
            grouped,
            hierarchy_result,
        )
        self.assertEqual(report.quality.structure_quality, 1.0)
        self.assertEqual(report.quality.warnings, ())

    def test_heading_anchor_counts_as_structurally_accounted(self) -> None:
        elements = (element("h", 0, ElementType.HEADING), element("p", 1))
        node = ContextNode(
            id="c",
            type="HEADING",
            label="H",
            level=1,
            source=StructureSource.EXPLICIT,
            confidence=0.9,
            attributes={"anchor_element_id": "h"},
        )
        grouped = grouping(elements, (unit("u", ("p",)),), ungrouped=("h",))
        hierarchy_result = hierarchy(
            elements,
            {"h": ("c",), "p": ("c",)},
            (node,),
            StructureMode.LOCAL,
        )
        report = self.estimator.estimate(
            elements,
            boundaries(elements),
            grouped,
            hierarchy_result,
        )
        self.assertEqual(report.metrics.structurally_accounted_ratio, 1.0)
        self.assertEqual(report.quality.structure_quality, 1.0)

    def test_unresolved_integrity_and_ungrouped_content_lower_quality(self) -> None:
        elements = (
            element("r0", 0, ElementType.TABLE_ROW),
            element("r1", 1, ElementType.TABLE_CELL),
        )
        grouped = grouping(elements, (), ungrouped=("r0", "r1"))
        hierarchy_result = hierarchy(elements, {})
        boundary_result = boundaries(
            elements,
            (BoundaryClass.UNKNOWN,),
            unresolved=(0,),
        )
        report = self.estimator.estimate(
            elements,
            boundary_result,
            grouped,
            hierarchy_result,
        )
        self.assertLess(report.quality.structure_quality, 0.5)
        self.assertIn("low structural accounting coverage", report.quality.warnings)
        self.assertIn("high unresolved boundary ratio", report.quality.warnings)
        self.assertIn(
            "content-integrity continuity remains unresolved",
            report.quality.warnings,
        )

    def test_unknown_elements_receive_explicit_penalty(self) -> None:
        elements = (element("u", 0, ElementType.UNKNOWN),)
        grouped = grouping(
            elements,
            (unit("lu", ("u",), LogicalUnitType.UNKNOWN_GROUP),),
        )
        hierarchy_result = hierarchy(elements, {})
        report = self.estimator.estimate(
            elements,
            boundaries(elements),
            grouped,
            hierarchy_result,
        )
        self.assertEqual(report.metrics.unknown_element_ratio, 1.0)
        self.assertEqual(report.quality.structure_quality, 0.5)
        self.assertIn("high UNKNOWN element ratio", report.quality.warnings)

    def test_mismatched_stage_counts_are_rejected(self) -> None:
        elements = (element("e0", 0), element("e1", 1))
        grouped = GroupingResult(
            element_count=1,
            signal_version="1",
            boundary_version="1",
            policy=GroupingPolicy(),
            logical_units=(),
            subdocuments=(),
            ungrouped_element_ids=("e0",),
        )
        hierarchy_result = hierarchy(elements, {})
        with self.assertRaises(StructureQualityError):
            self.estimator.estimate(
                elements,
                boundaries(elements),
                grouped,
                hierarchy_result,
            )


if __name__ == "__main__":
    unittest.main()
