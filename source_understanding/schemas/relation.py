from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .context import Confidence, Identifier, JsonObject, SchemaModel, StructureSource


class RelationType(StrEnum):
    NEXT = "NEXT"
    PREVIOUS = "PREVIOUS"
    PARENT_OF = "PARENT_OF"
    CHILD_OF = "CHILD_OF"
    CONTINUES = "CONTINUES"
    QUESTION_ANSWER = "QUESTION_ANSWER"
    CAPTION_OF = "CAPTION_OF"
    FOOTNOTE_OF = "FOOTNOTE_OF"
    EXPLAINS = "EXPLAINS"
    REFERS_TO = "REFERS_TO"
    SAME_TOPIC = "SAME_TOPIC"
    PREREQUISITE_OF = "PREREQUISITE_OF"
    PART_OF = "PART_OF"
    SEQUENCE_BEFORE = "SEQUENCE_BEFORE"
    DUPLICATE_OF = "DUPLICATE_OF"


class Relation(SchemaModel):
    id: Identifier
    type: RelationType
    source_id: Identifier
    target_id: Identifier
    confidence: Confidence
    source: StructureSource
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_endpoints(self) -> Relation:
        if self.source_id == self.target_id:
            raise ValueError("relation cannot target its own source")
        return self
