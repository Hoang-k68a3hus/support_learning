from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import Field, model_validator

from ai_data_studio.schemas import (
    AdjudicationConfidence,
    AnnotationDecisionState,
    SemanticWorkingRecord,
    WorkingRecordStatus,
)
from source_understanding.schemas.context import ContentHash, SchemaModel
from source_understanding.schemas.document import (
    SemanticPayloadMode,
    semantic_payload_mode_for_type,
)


GOLD_ELIGIBILITY_POLICY_HASH_VERSION = "1"


class GoldIneligibilityReason(StrEnum):
    STATUS_NOT_ALLOWED = "STATUS_NOT_ALLOWED"
    DECISIONS_INCOMPLETE = "DECISIONS_INCOMPLETE"
    UNDECIDED_PRESENT = "UNDECIDED_PRESENT"
    CONFIDENCE_TOO_LOW = "CONFIDENCE_TOO_LOW"
    MISSING_REVIEW = "MISSING_REVIEW"
    MISSING_RULE_KEYS = "MISSING_RULE_KEYS"
    PAYLOAD_MODE_NOT_ALLOWED = "PAYLOAD_MODE_NOT_ALLOWED"


class GoldEligibilityPolicy(SchemaModel):
    name: str = Field(
        default="semantic-gold-strict",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    version: str = Field(
        default="1",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    allowed_statuses: tuple[WorkingRecordStatus, ...] = (
        WorkingRecordStatus.PASS,
    )
    minimum_confidence: AdjudicationConfidence = AdjudicationConfidence.HIGH
    require_review: bool = True
    require_positive_rule_keys: bool = True
    allowed_payload_modes: tuple[SemanticPayloadMode, ...] = (
        SemanticPayloadMode.LABEL_ONLY,
        SemanticPayloadMode.EXTRACTIVE,
    )

    @model_validator(mode="after")
    def validate_policy(self) -> "GoldEligibilityPolicy":
        if not self.allowed_statuses:
            raise ValueError("gold eligibility allowed_statuses must not be empty")
        if len(self.allowed_statuses) != len(set(self.allowed_statuses)):
            raise ValueError("gold eligibility allowed_statuses must be unique")
        canonical_statuses = tuple(
            status for status in WorkingRecordStatus if status in self.allowed_statuses
        )
        if self.allowed_statuses != canonical_statuses:
            raise ValueError(
                "gold eligibility allowed_statuses must use canonical order"
            )
        if not self.allowed_payload_modes:
            raise ValueError(
                "gold eligibility allowed_payload_modes must not be empty"
            )
        if len(self.allowed_payload_modes) != len(set(self.allowed_payload_modes)):
            raise ValueError(
                "gold eligibility allowed_payload_modes must be unique"
            )
        canonical_payload_modes = tuple(
            mode
            for mode in SemanticPayloadMode
            if mode in self.allowed_payload_modes
        )
        if self.allowed_payload_modes != canonical_payload_modes:
            raise ValueError(
                "gold eligibility allowed_payload_modes must use canonical order"
            )
        return self


class GoldEligibilityResult(SchemaModel):
    eligible: bool
    reasons: tuple[GoldIneligibilityReason, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> "GoldEligibilityResult":
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("gold ineligibility reasons must be unique")
        canonical_reasons = tuple(
            reason for reason in GoldIneligibilityReason if reason in self.reasons
        )
        if self.reasons != canonical_reasons:
            raise ValueError("gold ineligibility reasons must use canonical order")
        if self.eligible == bool(self.reasons):
            raise ValueError(
                "gold eligibility result must be eligible exactly when reasons "
                "are empty"
            )
        return self


class GoldEligibilityEvaluator:
    def evaluate(
        self,
        record: SemanticWorkingRecord,
        *,
        policy: GoldEligibilityPolicy,
    ) -> GoldEligibilityResult:
        reasons: set[GoldIneligibilityReason] = set()
        if record.status not in policy.allowed_statuses:
            reasons.add(GoldIneligibilityReason.STATUS_NOT_ALLOWED)

        decision_types = {decision.annotation_type for decision in record.decisions}
        if decision_types != set(record.evaluated_types):
            reasons.add(GoldIneligibilityReason.DECISIONS_INCOMPLETE)
        if any(
            decision.state == AnnotationDecisionState.UNDECIDED
            for decision in record.decisions
        ):
            reasons.add(GoldIneligibilityReason.UNDECIDED_PRESENT)

        minimum_rank = _CONFIDENCE_RANK[policy.minimum_confidence]
        if any(
            _CONFIDENCE_RANK[decision.confidence] < minimum_rank
            for decision in record.decisions
        ):
            reasons.add(GoldIneligibilityReason.CONFIDENCE_TOO_LOW)
        if policy.require_review and not record.reviews:
            reasons.add(GoldIneligibilityReason.MISSING_REVIEW)
        if policy.require_positive_rule_keys and any(
            decision.state == AnnotationDecisionState.POSITIVE
            and not decision.rule_keys
            for decision in record.decisions
        ):
            reasons.add(GoldIneligibilityReason.MISSING_RULE_KEYS)

        allowed_payload_modes = set(policy.allowed_payload_modes)
        if any(
            decision.state == AnnotationDecisionState.POSITIVE
            and semantic_payload_mode_for_type(decision.annotation_type)
            not in allowed_payload_modes
            for decision in record.decisions
        ):
            reasons.add(GoldIneligibilityReason.PAYLOAD_MODE_NOT_ALLOWED)

        ordered_reasons = tuple(
            reason for reason in GoldIneligibilityReason if reason in reasons
        )
        return GoldEligibilityResult(
            eligible=not ordered_reasons,
            reasons=ordered_reasons,
        )


def gold_eligibility_policy_hash(policy: GoldEligibilityPolicy) -> ContentHash:
    payload = {
        "hash_version": GOLD_ELIGIBILITY_POLICY_HASH_VERSION,
        "policy": policy.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


_CONFIDENCE_RANK = {
    AdjudicationConfidence.LOW: 0,
    AdjudicationConfidence.MEDIUM: 1,
    AdjudicationConfidence.HIGH: 2,
}
