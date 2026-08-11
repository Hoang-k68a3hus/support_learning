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
    Rebuild list integrity from contiguous LIST_ITEM elements while retaining each
    element's original numbering_id as a source observation.

    A change of Word ``numId`` alone is not a trustworthy logical-list boundary:
    authoring tools routinely switch numbering definitions inside one visible
    list. Contiguous fragments may therefore share one integrity run when their
    observed numbering level/format remain compatible. Headings and all non-list
    material still terminate the run.
    """

    def _normalize_list_integrity(self, emitter: Emitter) -> None:
        current_part_zone: tuple[str, str] | None = None
        current_group: str | None = None
        previous_numbering: tuple[str, int | None, str | None] | None = None
        rewritten = []

        for raw in emitter.elements:
            attributes = dict(raw.attributes)
            type_hint = raw.type_hint

            if type_hint == "LIST_ITEM":
                num_id = attributes.get("numbering_id")
                part = attributes.get("opc_part")
                zone = attributes.get(SOURCE_ZONE_ATTRIBUTE) or attributes.get("zone")
                level = attributes.get("numbering_level")
                number_format = attributes.get("number_format")
                if (
                    isinstance(num_id, str)
                    and num_id != "0"
                    and isinstance(part, str)
                    and isinstance(zone, str)
                    and (level is None or isinstance(level, int))
                    and (number_format is None or isinstance(number_format, str))
                ):
                    part_zone = (part, zone)
                    numbering = (num_id, level, number_format)
                    compatible = (
                        current_part_zone == part_zone
                        and current_group is not None
                        and previous_numbering is not None
                        and self._compatible_contiguous_numbering(
                            previous_numbering,
                            numbering,
                        )
                    )
                    if not compatible:
                        current_group = stable_group_id(
                            "list", part, zone, num_id, str(raw.order)
                        )
                    current_part_zone = part_zone
                    previous_numbering = numbering
                    attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] = current_group
                    attributes.pop(INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE, None)
                else:
                    current_part_zone = None
                    current_group = None
                    previous_numbering = None
                    attributes.pop(INTEGRITY_GROUP_ID_ATTRIBUTE, None)
                    attributes.pop(INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE, None)
            else:
                current_part_zone = None
                current_group = None
                previous_numbering = None
                if type_hint == "HEADING":
                    attributes.pop(INTEGRITY_GROUP_ID_ATTRIBUTE, None)
                    attributes.pop(INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE, None)

            if attributes == dict(raw.attributes):
                rewritten.append(raw)
            else:
                rewritten.append(raw.model_copy(update={"attributes": attributes}))

        emitter.elements[:] = rewritten

    @staticmethod
    def _compatible_contiguous_numbering(
        previous: tuple[str, int | None, str | None],
        current: tuple[str, int | None, str | None],
    ) -> bool:
        previous_id, previous_level, previous_format = previous
        current_id, current_level, current_format = current
        if previous_id == current_id:
            return True
        if previous_level is None or current_level is None:
            return False
        if previous_level != current_level:
            return False
        if previous_format is None or current_format is None:
            return False
        return previous_format.casefold() == current_format.casefold()
