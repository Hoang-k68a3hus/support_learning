from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from source_understanding.schemas.context import ContentHash
from source_understanding.schemas.document import CanonicalDocument, SemanticTextView
from source_understanding.schemas.element import Element


WORKING_ELEMENT_SNAPSHOT_HASH_VERSION = "1"
WORKING_TARGET_TEXT_SEPARATOR = "\n\n"


def working_element_snapshot_hash(document: CanonicalDocument) -> ContentHash:
    payload = {
        "hash_version": WORKING_ELEMENT_SNAPSHOT_HASH_VERSION,
        "document_id": document.document_id,
        "content_hash": document.content_hash,
        "elements": [
            {
                "id": element.id,
                "order": element.order,
                "type": element.type.value,
                "raw_text": element.raw_text,
                "normalized_text": element.normalized_text,
            }
            for element in document.elements
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_target_text_snapshot(
    elements: Sequence[Element],
    *,
    view: SemanticTextView,
) -> str | None:
    ordered = tuple(sorted(elements, key=lambda element: element.order))
    values = tuple(
        element.raw_text
        if view == SemanticTextView.RAW_TEXT
        else element.normalized_text
        for element in ordered
    )
    present_values = tuple(value for value in values if value is not None)
    if not present_values:
        return None
    return WORKING_TARGET_TEXT_SEPARATOR.join(present_values)
