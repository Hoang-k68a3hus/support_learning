from __future__ import annotations

import unittest

from source_understanding.adapters import DocxAdapter
from source_understanding.adapters._docx_common import Emitter
from source_understanding.source_attributes import INTEGRITY_GROUP_ID_ATTRIBUTE


class DocxListIntegrityRunTests(unittest.TestCase):
    def _emit_list_item(
        self,
        emitter: Emitter,
        text: str,
        *,
        num_id: str,
        level: int,
        number_format: str,
    ) -> None:
        emitter.emit(
            text=text,
            type_hint="LIST_ITEM",
            part="word/document.xml",
            attributes={
                "zone": "body",
                "numbering_id": num_id,
                "numbering_level": level,
                "number_format": number_format,
            },
        )

    def test_compatible_numid_switch_stays_one_contiguous_integrity_run(self) -> None:
        adapter = DocxAdapter()
        emitter = Emitter(adapter)
        self._emit_list_item(emitter, "A", num_id="6", level=0, number_format="bullet")
        self._emit_list_item(emitter, "B", num_id="3", level=0, number_format="bullet")
        self._emit_list_item(emitter, "C", num_id="6", level=0, number_format="bullet")

        adapter._normalize_list_integrity(emitter)

        group_ids = {
            item.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] for item in emitter.elements
        }
        self.assertEqual(len(group_ids), 1)
        self.assertEqual(
            [item.attributes["numbering_id"] for item in emitter.elements],
            ["6", "3", "6"],
        )

    def test_incompatible_format_or_level_starts_new_integrity_run(self) -> None:
        adapter = DocxAdapter()
        emitter = Emitter(adapter)
        self._emit_list_item(emitter, "A", num_id="1", level=0, number_format="bullet")
        self._emit_list_item(emitter, "B", num_id="2", level=0, number_format="decimal")
        self._emit_list_item(emitter, "C", num_id="3", level=1, number_format="decimal")

        adapter._normalize_list_integrity(emitter)

        group_ids = [
            item.attributes[INTEGRITY_GROUP_ID_ATTRIBUTE] for item in emitter.elements
        ]
        self.assertEqual(len(set(group_ids)), 3)

    def test_non_list_element_terminates_contiguous_run(self) -> None:
        adapter = DocxAdapter()
        emitter = Emitter(adapter)
        self._emit_list_item(emitter, "A", num_id="1", level=0, number_format="bullet")
        emitter.emit(
            text="Body",
            type_hint="PARAGRAPH",
            part="word/document.xml",
            attributes={"zone": "body"},
        )
        self._emit_list_item(emitter, "B", num_id="2", level=0, number_format="bullet")

        adapter._normalize_list_integrity(emitter)

        first = emitter.elements[0].attributes[INTEGRITY_GROUP_ID_ATTRIBUTE]
        last = emitter.elements[2].attributes[INTEGRITY_GROUP_ID_ATTRIBUTE]
        self.assertNotEqual(first, last)


if __name__ == "__main__":
    unittest.main()
