from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from source_understanding.schemas.context import ContentHash, Identifier, JsonObject, SchemaModel, StructureMode
from source_understanding.schemas.element import ElementType
from source_understanding.schemas.logical_unit import LogicalUnitType
from source_understanding.schemas.relation import RelationType


DOCUMENT_STRUCTURE_EVAL_SCHEMA_VERSION = "0.1"
DOCX_GOLD_BENCHMARK_VERSION = "0.1"


class BenchmarkSplit(StrEnum):
    DEV = "dev"
    TEST = "test"


class BenchmarkSourceKind(StrEnum):
    GENERATED = "generated"
    PUBLIC = "public"
    HUMAN_AUTHORED = "human_authored"


class GoldSourceAnchor(SchemaModel):
    """Source-stable hint used to align gold Elements with predicted Elements.

    Alignment deliberately does not depend on production Element ids.

    ``exact_text`` lives on GoldElement rather than here. Text-bearing nodes are
    aligned by exact source text + OPC part/zone whenever unique. Textless
    structural nodes use ``source_kind`` + ``occurrence``. Notes/comments may use
    their explicit native ``source_anchor_kind``/``source_anchor_id``.
    """

    opc_part: str = Field(min_length=1, max_length=1024)
    source_zone: str | None = Field(default=None, min_length=1, max_length=128)
    source_kind: str | None = Field(default=None, min_length=1, max_length=128)
    occurrence: int | None = Field(default=None, ge=0)
    source_anchor_kind: str | None = Field(default=None, min_length=1, max_length=128)
    source_anchor_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_anchor(self) -> "GoldSourceAnchor":
        paired = (self.source_anchor_kind is None) == (self.source_anchor_id is None)
        if not paired:
            raise ValueError(
                "source_anchor_kind and source_anchor_id must be provided together"
            )
        if self.occurrence is not None and self.source_kind is None:
            raise ValueError("occurrence requires source_kind")
        return self


class GoldElement(SchemaModel):
    id: Identifier
    order: int = Field(ge=0)
    anchor: GoldSourceAnchor
    text: str | None = None
    type: ElementType
    heading_level: int | None = Field(default=None, ge=1, le=64)
    required: bool = True
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_heading_level(self) -> "GoldElement":
        if self.heading_level is not None and self.type != ElementType.HEADING:
            raise ValueError("heading_level is only valid for HEADING gold elements")
        return self


class GoldLogicalUnit(SchemaModel):
    id: Identifier
    type: LogicalUnitType
    element_ids: tuple[Identifier, ...] = Field(min_length=1)
    exact_match: bool = True
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_members(self) -> "GoldLogicalUnit":
        if len(self.element_ids) != len(set(self.element_ids)):
            raise ValueError("gold logical unit element_ids must be unique")
        return self


class GoldContextNode(SchemaModel):
    id: Identifier
    anchor_element_id: Identifier
    type: str = Field(min_length=1, max_length=128)
    level: int | None = Field(default=None, ge=0)
    parent_id: Identifier | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_parent(self) -> "GoldContextNode":
        if self.parent_id == self.id:
            raise ValueError("gold context node cannot be its own parent")
        return self


class GoldRegion(SchemaModel):
    id: Identifier
    element_ids: tuple[Identifier, ...] = Field(min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=128)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_members(self) -> "GoldRegion":
        if len(self.element_ids) != len(set(self.element_ids)):
            raise ValueError("gold region element_ids must be unique")
        return self


class GoldRelation(SchemaModel):
    id: Identifier
    type: RelationType
    source_id: Identifier
    target_id: Identifier
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_not_self_relation(self) -> "GoldRelation":
        if self.source_id == self.target_id:
            raise ValueError("gold relation cannot target its own source")
        return self


class ExpectedAdapterDiagnostic(SchemaModel):
    code: str = Field(min_length=1, max_length=256)
    min_count: int = Field(default=1, ge=1)
    affects_structural_completeness: bool | None = None
    metadata: JsonObject = Field(default_factory=dict)


class UnsupportedConstruct(SchemaModel):
    construct_type: str = Field(min_length=1, max_length=256)
    expected_behavior: str = Field(min_length=1, max_length=256)
    expected_diagnostic_code: str | None = Field(default=None, min_length=1, max_length=256)
    metadata: JsonObject = Field(default_factory=dict)


class GoldSourceDescriptor(SchemaModel):
    file_name: str = Field(min_length=1, max_length=1024)
    sha256: ContentHash
    language: str = Field(default="en", min_length=2, max_length=64)
    document_class: str = Field(min_length=1, max_length=128)
    source_kind: BenchmarkSourceKind = BenchmarkSourceKind.GENERATED
    generator_id: str | None = Field(default=None, min_length=1, max_length=256)
    provenance: JsonObject = Field(default_factory=dict)


class GoldDocumentStructure(SchemaModel):
    schema_version: str = DOCUMENT_STRUCTURE_EVAL_SCHEMA_VERSION
    benchmark_version: str = DOCX_GOLD_BENCHMARK_VERSION
    document_id: Identifier
    source: GoldSourceDescriptor
    elements: tuple[GoldElement, ...] = Field(min_length=1)
    logical_units: tuple[GoldLogicalUnit, ...] = Field(default_factory=tuple)
    evaluated_logical_unit_types: tuple[LogicalUnitType, ...] = Field(default_factory=tuple)
    context_nodes: tuple[GoldContextNode, ...] = Field(default_factory=tuple)
    regions: tuple[GoldRegion, ...] = Field(default_factory=tuple)
    relations: tuple[GoldRelation, ...] = Field(default_factory=tuple)
    evaluated_relation_types: tuple[RelationType, ...] = Field(default_factory=tuple)
    expected_diagnostics: tuple[ExpectedAdapterDiagnostic, ...] = Field(default_factory=tuple)
    unsupported_constructs: tuple[UnsupportedConstruct, ...] = Field(default_factory=tuple)
    expected_structure_mode: StructureMode | None = None
    expected_structural_ready: bool | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "GoldDocumentStructure":
        element_ids = [item.id for item in self.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("gold elements contain duplicate ids")
        orders = [item.order for item in self.elements]
        if len(orders) != len(set(orders)):
            raise ValueError("gold elements contain duplicate order values")
        if orders != sorted(orders):
            raise ValueError("gold elements must be stored in ascending order")
        element_set = set(element_ids)

        logical_ids = [item.id for item in self.logical_units]
        context_ids = [item.id for item in self.context_nodes]
        region_ids = [item.id for item in self.regions]
        relation_ids = [item.id for item in self.relations]
        for name, values in (
            ("logical_units", logical_ids),
            ("context_nodes", context_ids),
            ("regions", region_ids),
            ("relations", relation_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"gold {name} contain duplicate ids")

        namespaces = {
            "elements": set(element_ids),
            "logical_units": set(logical_ids),
            "context_nodes": set(context_ids),
            "regions": set(region_ids),
        }
        names = list(namespaces)
        for index, left in enumerate(names):
            for right in names[index + 1 :]:
                overlap = namespaces[left] & namespaces[right]
                if overlap:
                    raise ValueError(
                        f"gold id collision between {left} and {right}: {sorted(overlap)}"
                    )

        element_order = {item.id: item.order for item in self.elements}
        for unit in self.logical_units:
            self._require_subset(
                f"logical unit {unit.id} element_ids", unit.element_ids, element_set
            )
            self._require_order(
                f"logical unit {unit.id} element_ids", unit.element_ids, element_order
            )

        seen_region_members: dict[str, str] = {}
        for region in self.regions:
            self._require_subset(
                f"region {region.id} element_ids", region.element_ids, element_set
            )
            self._require_order(
                f"region {region.id} element_ids", region.element_ids, element_order
            )
            for element_id in region.element_ids:
                previous = seen_region_members.get(element_id)
                if previous is not None:
                    raise ValueError(
                        f"gold element {element_id!r} belongs to multiple regions: "
                        f"{previous!r}, {region.id!r}"
                    )
                seen_region_members[element_id] = region.id

        if self.regions:
            covered = set(seen_region_members)
            if covered != element_set:
                missing = sorted(element_set - covered)
                extra = sorted(covered - element_set)
                raise ValueError(
                    "gold regions must cover every gold element exactly once; "
                    f"missing={missing}, extra={extra}"
                )

        if len(self.evaluated_logical_unit_types) != len(set(self.evaluated_logical_unit_types)):
            raise ValueError("evaluated_logical_unit_types must be unique")
        gold_unit_types = {item.type for item in self.logical_units}
        undeclared_unit_types = gold_unit_types - set(self.evaluated_logical_unit_types)
        if undeclared_unit_types:
            raise ValueError(
                "every gold logical unit type must appear in evaluated_logical_unit_types: "
                f"{sorted(item.value for item in undeclared_unit_types)}"
            )

        context_set = set(context_ids)
        context_by_id = {item.id: item for item in self.context_nodes}
        for node in self.context_nodes:
            if node.anchor_element_id not in element_set:
                raise ValueError(
                    f"gold context node {node.id!r} anchors unknown element "
                    f"{node.anchor_element_id!r}"
                )
            if node.parent_id is not None and node.parent_id not in context_set:
                raise ValueError(
                    f"gold context node {node.id!r} references unknown parent "
                    f"{node.parent_id!r}"
                )
        for node in self.context_nodes:
            seen: set[str] = set()
            current: str | None = node.id
            while current is not None:
                if current in seen:
                    raise ValueError(f"gold context hierarchy contains cycle at {current!r}")
                seen.add(current)
                parent = context_by_id.get(current)
                current = parent.parent_id if parent is not None else None

        relation_targets = (
            element_set | set(logical_ids) | set(context_ids) | set(region_ids)
        )
        for relation in self.relations:
            if relation.source_id not in relation_targets:
                raise ValueError(
                    f"gold relation {relation.id!r} has unknown source "
                    f"{relation.source_id!r}"
                )
            if relation.target_id not in relation_targets:
                raise ValueError(
                    f"gold relation {relation.id!r} has unknown target "
                    f"{relation.target_id!r}"
                )

        if len(self.evaluated_relation_types) != len(set(self.evaluated_relation_types)):
            raise ValueError("evaluated_relation_types must be unique")
        gold_relation_types = {item.type for item in self.relations}
        undeclared = gold_relation_types - set(self.evaluated_relation_types)
        if undeclared:
            raise ValueError(
                "every gold relation type must appear in evaluated_relation_types: "
                f"{sorted(item.value for item in undeclared)}"
            )
        return self

    @staticmethod
    def _require_subset(name: str, values: tuple[str, ...], valid: set[str]) -> None:
        missing = set(values) - valid
        if missing:
            raise ValueError(f"{name} references unknown ids: {sorted(missing)}")

    @staticmethod
    def _require_order(
        name: str, values: tuple[str, ...], order: dict[str, int]
    ) -> None:
        resolved = [order[value] for value in values]
        if resolved != sorted(resolved):
            raise ValueError(f"{name} must follow gold source order")


class BenchmarkCase(SchemaModel):
    document_id: Identifier
    source_file: str = Field(min_length=1, max_length=1024)
    annotation_file: str = Field(min_length=1, max_length=1024)
    sha256: ContentHash
    split: BenchmarkSplit = BenchmarkSplit.DEV
    tags: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_tags(self) -> "BenchmarkCase":
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("benchmark case tags must be unique")
        return self


class BenchmarkManifest(SchemaModel):
    name: str = Field(min_length=1, max_length=256)
    benchmark_version: str = DOCX_GOLD_BENCHMARK_VERSION
    schema_version: str = DOCUMENT_STRUCTURE_EVAL_SCHEMA_VERSION
    generator_id: str = Field(min_length=1, max_length=256)
    generator_seed: int
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cases(self) -> "BenchmarkManifest":
        ids = [item.document_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark manifest document ids must be unique")
        source_files = [item.source_file for item in self.cases]
        annotation_files = [item.annotation_file for item in self.cases]
        if len(source_files) != len(set(source_files)):
            raise ValueError("benchmark manifest source files must be unique")
        if len(annotation_files) != len(set(annotation_files)):
            raise ValueError("benchmark manifest annotation files must be unique")
        return self
