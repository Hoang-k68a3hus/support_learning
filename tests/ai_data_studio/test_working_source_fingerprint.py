from __future__ import annotations

import hashlib
import json
import unittest

from ai_data_studio.validation import (
    WORKING_ELEMENT_SNAPSHOT_HASH_VERSION,
    WORKING_TARGET_TEXT_SEPARATOR,
    build_target_text_snapshot,
    working_element_snapshot_hash,
)
from source_understanding.schemas.document import SemanticTextView

from tests.ai_data_studio._validation_fixtures import canonical_document


class WorkingSourceFingerprintTests(unittest.TestCase):
    def test_element_snapshot_hash_uses_the_declared_canonical_payload(self) -> None:
        document = canonical_document()
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
        expected = "sha256:" + hashlib.sha256(encoded).hexdigest()

        self.assertEqual(working_element_snapshot_hash(document), expected)

    def test_normalizer_output_change_changes_snapshot_not_content_hash(self) -> None:
        document = canonical_document()
        changed_element = document.elements[0].model_copy(
            update={"normalized_text": "Changed normalization"}
        )
        changed = document.model_copy(
            update={"elements": (changed_element, *document.elements[1:])}
        )

        self.assertEqual(changed.content_hash, document.content_hash)
        self.assertNotEqual(
            working_element_snapshot_hash(changed),
            working_element_snapshot_hash(document),
        )

    def test_target_text_snapshot_uses_canonical_order_and_fixed_separator(self) -> None:
        document = canonical_document()
        selected = (document.elements[1], document.elements[0])

        snapshot = build_target_text_snapshot(
            selected,
            view=SemanticTextView.RAW_TEXT,
        )

        self.assertEqual(
            snapshot,
            f"Gradient  descent{WORKING_TARGET_TEXT_SEPARATOR}minimizes loss.",
        )

    def test_target_text_views_do_not_fallback(self) -> None:
        document = canonical_document()
        normalized_only = (document.elements[3],)
        raw_only = (document.elements[4],)

        self.assertIsNone(
            build_target_text_snapshot(
                normalized_only,
                view=SemanticTextView.RAW_TEXT,
            )
        )
        self.assertIsNone(
            build_target_text_snapshot(
                raw_only,
                view=SemanticTextView.NORMALIZED_TEXT,
            )
        )


if __name__ == "__main__":
    unittest.main()
