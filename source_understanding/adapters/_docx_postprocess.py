from __future__ import annotations

from source_understanding.source_attributes import (
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)

from ._docx_common import Emitter, stable_group_id


class DocxPostprocessMixin:
    """Normalize source-near integrity facts after all DOCX stories are emitted.

    Numbering metadata is not sufficient to make a heading a list member. Word
    documents in the wild can attach numPr to heading styles (including numId=0).
    Rebuild only list integrity runs from contiguous LIST_ITEM elements so an
    explicit heading always remains a structural boundary while retaining its
    numbering metadata as a source observation.
    """

    def _normalize_list_integrity(self, emitter: Emitter) -> None:
        current_key: tuple[str, str, str] | None = None
        current_group: str | None = None
        rewritten = []

        for raw in emitter.elements:
            attributes = dict(raw.attributes)
            type_hint = raw.type_hint

            if type_hint == "LIST_ITEM":
                num_id = attributes.get("numbering_id")
                part = attributes.get("opc_part")
                zone = attributes.get(SOURCE_ZONE_ATTRIBUTE) or attributes.get("zone")
                if isinstance(num_id, str) and isinstance(part, str) and isinstance(zone, str):
                    key = (part, zone, num_id)
                    if current_key != key or current_group is None:
                        current_group = stable_group_id(
                            "list", part, zone, num_id, str(raw.order)
                        )
                    current_key = key
                    attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] = current_group
                    attributes.pop(INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE, None)
                else:
                    current_key = None
                    current_group = None
                    attributes.pop(INTEGRITY_GROUP_ID_ATTRIBUTE, None)
                    attributes.pop(INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE, None)
            else:
                current_key = None
                current_group = None
                if type_hint == "HEADING":
                    attributes.pop(INTEGRITY_GROUP_ID_ATTRIBUTE, None)
                    attributes.pop(INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE, None)

            if attributes == dict(raw.attributes):
                rewritten.append(raw)
            else:
                rewritten.append(raw.model_copy(update={"attributes": attributes}))

        emitter.elements[:] = rewritten
