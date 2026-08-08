from __future__ import annotations

import unittest

from source_understanding.atomic import ElementNormalizer
from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import SemanticAnnotationType
from source_understanding.schemas.element import Provenance, RawElement
from source_understanding.semantics.provider import (
    SemanticCapability,
    SemanticProviderCapabilities,
    SemanticTargetKind,
)


class V2ContractRegressionTests(unittest.TestCase):
    def test_element_id_does_not_churn_for_extractor_version_only_change(self):
        def source(version: str) -> RawElement:
            return RawElement(
                text="same source observation",
                type_hint="paragraph",
                order=0,
                attributes={"source_key": "p1"},
                provenance=Provenance(
                    source=StructureSource.EXPLICIT,
                    extractor="docx-ooxml",
                    extractor_version=version,
                ),
            )

        first = ElementNormalizer().normalize((source("1"),), document_id="doc")
        second = ElementNormalizer().normalize((source("2"),), document_id="doc")
        self.assertEqual(first.elements[0].id, second.elements[0].id)
        self.assertNotEqual(
            first.elements[0].provenance.extractor_version,
            second.elements[0].provenance.extractor_version,
        )

    def test_semantic_capabilities_reject_future_protocol(self):
        with self.assertRaisesRegex(ValueError, "unsupported semantic provider protocol_version"):
            SemanticProviderCapabilities(
                protocol_version="999",
                capabilities=(
                    SemanticCapability(
                        name="ner",
                        target_kinds=(SemanticTargetKind.ELEMENT,),
                        annotation_types=(SemanticAnnotationType.ENTITY,),
                        ontology_namespaces=("ner",),
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
