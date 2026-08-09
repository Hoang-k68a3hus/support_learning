from __future__ import annotations

from collections.abc import Mapping, Sequence

from ai_data_studio.schemas import (
    WORKING_RECORD_SCHEMA_VERSION,
    SemanticWorkingRecord,
)
from ai_data_studio.validation.review import validate_review_chain
from source_understanding.evaluation import GoldSemanticDocument, SemanticGoldDataset
from source_understanding.schemas.context import Identifier
from source_understanding.schemas.document import CanonicalDocument
from source_understanding.semantics.provider import SemanticTargetKind

from .compiler import SemanticGoldCompiler as _BaseSemanticGoldCompiler
from .eligibility import (
    GOLD_ELIGIBILITY_POLICY_HASH_VERSION,
    GoldEligibilityPolicy,
    gold_eligibility_policy_hash,
)
from .errors import GoldEligibilityError, GoldSourceResolutionError
from .splits import DatasetSplit, DatasetSplitManifest


SEMANTIC_GOLD_COMPILER_VERSION = "2"


class SemanticGoldCompiler(_BaseSemanticGoldCompiler):
    """Gold compiler with fail-closed checks for gold-critical working state.

    M2.1 remains the complete audit validator. The compiler nevertheless
    re-checks the subset of cross-object invariants whose violation could create
    a semantically wrong but internally valid Gold V3 artifact: exact target
    topology, review decision-hash continuity, and one terminal guideline per
    compiled document.
    """

    version = SEMANTIC_GOLD_COMPILER_VERSION

    def compile_document(
        self,
        *,
        document: CanonicalDocument,
        records: Sequence[SemanticWorkingRecord],
        split: DatasetSplit,
        policy: GoldEligibilityPolicy,
    ) -> GoldSemanticDocument:
        _validate_gold_target_topology(document=document, records=records)
        _validate_review_integrity(records)
        guideline_version = _resolve_guideline_version(records, policy=policy)
        gold = super().compile_document(
            document=document,
            records=records,
            split=split,
            policy=policy,
        )
        metadata = dict(gold.metadata)
        metadata.update(
            {
                "compiler_version": self.version,
                "working_schema_version": WORKING_RECORD_SCHEMA_VERSION,
                "eligibility_policy_name": policy.name,
                "eligibility_policy_version": policy.version,
                "eligibility_policy_hash": gold_eligibility_policy_hash(policy),
            }
        )
        if guideline_version is not None:
            metadata["guideline_version"] = guideline_version
        payload = gold.model_dump(mode="python")
        payload["metadata"] = metadata
        return GoldSemanticDocument.model_validate(payload)

    def compile_dataset(
        self,
        *,
        name: str,
        documents: Mapping[Identifier, CanonicalDocument],
        records: Sequence[SemanticWorkingRecord],
        split_manifest: DatasetSplitManifest,
        policy: GoldEligibilityPolicy,
    ) -> SemanticGoldDataset:
        dataset = super().compile_dataset(
            name=name,
            documents=documents,
            records=records,
            split_manifest=split_manifest,
            policy=policy,
        )
        guideline_versions = tuple(
            sorted(
                {
                    case.metadata["guideline_version"]
                    for case in dataset.cases
                    if "guideline_version" in case.metadata
                }
            )
        )
        metadata = dict(dataset.metadata)
        metadata.update(
            {
                "compiler_version": self.version,
                "eligibility_policy_name": policy.name,
                "eligibility_policy_version": policy.version,
                "eligibility_policy_hash": gold_eligibility_policy_hash(policy),
                "guideline_versions": list(guideline_versions),
            }
        )
        payload = dataset.model_dump(mode="python")
        payload["metadata"] = metadata
        return SemanticGoldDataset.model_validate(payload)


def _validate_review_integrity(
    records: Sequence[SemanticWorkingRecord],
) -> None:
    invalid: list[tuple[str, tuple[str, ...]]] = []
    for record in sorted(records, key=lambda item: item.record_id):
        issues = validate_review_chain(
            reviews=record.reviews,
            current_decision_hash=record.decision_hash,
            record_id=record.record_id,
        )
        errors = tuple(
            issue.code.value
            for issue in issues
            if issue.severity.value == "ERROR"
        )
        if errors:
            invalid.append((record.record_id, errors))
    if invalid:
        raise GoldEligibilityError(tuple(invalid))


def _resolve_guideline_version(
    records: Sequence[SemanticWorkingRecord],
    *,
    policy: GoldEligibilityPolicy,
) -> str | None:
    versions = tuple(
        sorted(
            {
                record.reviews[-1].guideline_version
                for record in records
                if record.reviews
            }
        )
    )
    if len(versions) > 1:
        raise GoldEligibilityError(
            tuple(
                (
                    record.record_id,
                    ("MIXED_REVIEW_GUIDELINES",),
                )
                for record in sorted(records, key=lambda item: item.record_id)
            )
        )
    if policy.require_review and not versions:
        return None
    return versions[0] if versions else None


def _validate_gold_target_topology(
    *,
    document: CanonicalDocument,
    records: Sequence[SemanticWorkingRecord],
) -> None:
    elements_by_id = {element.id: element for element in document.elements}
    logical_units_by_id = {unit.id: unit for unit in document.logical_units}

    for record in sorted(records, key=lambda item: item.record_id):
        target = record.target
        if target.target_kind == SemanticTargetKind.ELEMENT:
            element = elements_by_id.get(target.target_id)
            if element is None:
                raise GoldSourceResolutionError(
                    f"cannot compile record {record.record_id!r}: ELEMENT target "
                    f"{target.target_id!r} does not exist in the canonical document"
                )
            expected_ids = (element.id,)
            expected_orders = (element.order,)
            expected_logical_type = None
        else:
            logical_unit = logical_units_by_id.get(target.target_id)
            if logical_unit is None:
                raise GoldSourceResolutionError(
                    f"cannot compile record {record.record_id!r}: LOGICAL_UNIT "
                    f"target {target.target_id!r} does not exist in the canonical document"
                )
            expected_ids = tuple(logical_unit.element_ids)
            expected_orders = tuple(
                elements_by_id[element_id].order for element_id in expected_ids
            )
            expected_logical_type = logical_unit.type.value

        if target.element_ids != expected_ids:
            raise GoldSourceResolutionError(
                f"cannot compile record {record.record_id!r}: target element_ids "
                "do not exactly match canonical target membership"
            )
        if target.element_orders != expected_orders:
            raise GoldSourceResolutionError(
                f"cannot compile record {record.record_id!r}: target element_orders "
                "do not exactly match canonical target order"
            )
        if (
            target.target_kind == SemanticTargetKind.LOGICAL_UNIT
            and target.logical_unit_type != expected_logical_type
        ):
            raise GoldSourceResolutionError(
                f"cannot compile record {record.record_id!r}: logical_unit_type "
                f"{target.logical_unit_type!r} does not match canonical type "
                f"{expected_logical_type!r}"
            )


__all__ = [
    "GOLD_ELIGIBILITY_POLICY_HASH_VERSION",
    "SEMANTIC_GOLD_COMPILER_VERSION",
    "SemanticGoldCompiler",
    "gold_eligibility_policy_hash",
]
