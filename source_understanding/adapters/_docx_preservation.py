from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

from source_understanding.source_attributes import SOURCE_REFERENCES_ATTRIBUTE

from ._docx_common import Emitter, NS, local_name
from .base import AdapterDiagnostic, AdapterError


class DocxPreservationMixin:
    """Convert unsupported block-level OOXML into opaque source observations.

    The structural extractor is intentionally conservative, but unsupported
    structure must never mean silent source loss.  We let the normal extractor
    handle every construct it understands, then intercept only its explicit
    ``UNHANDLED_BLOCK_*`` fallback.  The unsupported block is preserved as one
    ``UNKNOWN`` RawElement with source-near text/relationship metadata while the
    diagnostic still marks structural understanding as incomplete.
    """

    def _emit_block(
        self,
        package: zipfile.ZipFile,
        emitter: Emitter,
        node: ET.Element,
        *,
        part: str,
        zone: str,
        rels: dict[str, object],
        content_hash: str,
        content_types: dict[str, str],
        path: str,
        parent_group: str | None,
        wrappers: tuple[dict[str, object], ...] = (),
    ) -> None:
        element_count_before = len(emitter.elements)
        diagnostic_count_before = len(self._diagnostics)

        super()._emit_block(
            package,
            emitter,
            node,
            part=part,
            zone=zone,
            rels=rels,
            content_hash=content_hash,
            content_types=content_types,
            path=path,
            parent_group=parent_group,
            wrappers=wrappers,
        )

        name = local_name(node.tag)
        expected_code = f"UNHANDLED_BLOCK_{name.upper()}"
        emitted_diagnostics = self._diagnostics[diagnostic_count_before:]
        unhandled = [item for item in emitted_diagnostics if item.code == expected_code]
        if not unhandled:
            return
        if len(unhandled) != 1:
            raise AdapterError(
                f"DOCX unsupported block {name!r} emitted duplicate diagnostics"
            )
        if len(emitter.elements) != element_count_before:
            raise AdapterError(
                f"DOCX unsupported block {name!r} emitted content before opaque fallback"
            )

        # Replace the extractor's diagnostic with a richer preservation-aware one.
        self._diagnostics[diagnostic_count_before:] = [
            item for item in emitted_diagnostics if item.code != expected_code
        ]

        text = self._opaque_block_text(node)
        attributes: dict[str, object] = {
            "zone": zone,
            "opaque_block_local_name": name,
            "opaque_block_path": path,
        }
        if parent_group is not None:
            attributes["opaque_parent_integrity_group_id"] = parent_group
        if wrappers:
            attributes["source_wrappers"] = list(wrappers)

        references = self._source_references(node)
        if references:
            attributes[SOURCE_REFERENCES_ATTRIBUTE] = references
        hyperlinks = self._hyperlinks(node, rels)
        if hyperlinks:
            attributes["hyperlinks"] = hyperlinks
        bookmarks = self._bookmarks(node)
        if bookmarks:
            attributes["bookmarks"] = bookmarks
        comments = self._reference_ids(node, "commentReference")
        if comments:
            attributes["comment_reference_ids"] = comments
        fields = self._field_instructions(node)
        if fields:
            attributes["field_instructions"] = fields
        breaks = self._explicit_breaks(node)
        if breaks:
            attributes["explicit_breaks"] = breaks
        asset_ids = self._asset_ids_in_node(node, part)
        if asset_ids:
            attributes["asset_ids"] = asset_ids
        alt_text = self._drawing_alt_text(node)
        if alt_text:
            attributes["drawing_alt_text"] = alt_text

        emitter.emit(
            text=text,
            type_hint="UNKNOWN",
            part=part,
            attributes=attributes,
        )
        self._diagnostics.append(
            AdapterDiagnostic(
                code=expected_code,
                message=(
                    "DOCX block-level construct is not structurally interpreted; "
                    "its source-near content was preserved as an opaque element"
                ),
                affects_structural_completeness=True,
                part=part,
                metadata={
                    "local_name": name,
                    "path": path,
                    "opaque_element_order": emitter.elements[-1].order,
                    "text_preserved": text is not None and bool(text.strip()),
                    "asset_count": len(asset_ids),
                },
            )
        )

    def _opaque_block_text(self, node: ET.Element) -> str | None:
        paragraphs = node.findall(".//w:p", NS)
        if paragraphs:
            chunks = [
                value
                for paragraph in paragraphs
                if (value := self._paragraph_text(paragraph)).strip()
            ]
            if chunks:
                return "\n".join(chunks)

        value = self._paragraph_text(node)
        return value if value.strip() else None
