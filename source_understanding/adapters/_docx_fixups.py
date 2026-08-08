from __future__ import annotations

from xml.etree import ElementTree as ET

from source_understanding.source_attributes import SOURCE_ANCHOR_ATTRIBUTE

from .base import AdapterDiagnostic, AdapterError
from ._docx_common import NS, W, Emitter, local_name, stable_group_id


class DocxFixupMixin:
    """Cross-cutting source-fidelity fixes kept separate from block mechanics."""

    def _emit_paragraph(
        self,
        emitter: Emitter,
        paragraph: ET.Element,
        *,
        part: str,
        zone: str,
        rels: dict[str, object],
        wrappers: tuple[dict[str, object], ...] = (),
    ) -> None:
        super()._emit_paragraph(
            emitter,
            paragraph,
            part=part,
            zone=zone,
            rels=rels,
            wrappers=wrappers,
        )
        math_nodes = [
            node
            for node in paragraph.iter()
            if local_name(node.tag) in {"oMath", "oMathPara"}
        ]
        if math_nodes and emitter.elements:
            last = emitter.elements[-1]
            attrs = dict(last.attributes)
            math_texts = ["".join(node.itertext()).strip() for node in math_nodes]
            math_texts = [value for value in math_texts if value]
            attrs["omml_count"] = len(math_nodes)
            if math_texts:
                attrs["omml_texts"] = math_texts
            update: dict[str, object] = {"attributes": attrs}
            if last.type_hint == "FORMULA" and (last.text is None or not last.text.strip()):
                update["text"] = "\n".join(math_texts) if math_texts else None
            emitter.elements[-1] = last.model_copy(update=update)

        ppr = paragraph.find("w:pPr", NS)
        sect = ppr.find("w:sectPr", NS) if ppr is not None else None
        if sect is not None:
            emitter.emit(
                text=None,
                type_hint="SEPARATOR",
                part=part,
                attributes={
                    "zone": zone,
                    "separator_kind": "section_break",
                    **self._section_properties(sect, rels),
                },
            )

    def _emit_table(
        self,
        package,
        emitter: Emitter,
        table: ET.Element,
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
        # The base extractor promotes direct child tables. Keep that behavior,
        # then additionally promote tables hidden under source wrappers (sdt,
        # customXml, tracked revisions) instead of silently flattening them.
        super()._emit_table(
            package,
            emitter,
            table,
            part=part,
            zone=zone,
            rels=rels,
            content_hash=content_hash,
            content_types=content_types,
            path=path,
            parent_group=parent_group,
            wrappers=wrappers,
        )
        group_id = stable_group_id("table", part, zone, path)
        for row_index, (row, row_wrappers) in enumerate(self._iter_wrapped(table, "tr")):
            for cell_index, (cell, cell_wrappers) in enumerate(self._iter_wrapped(row, "tc")):
                for nested_index, (nested, nested_wrappers) in enumerate(
                    self._iter_wrapped(cell, "tbl")
                ):
                    if not nested_wrappers:
                        continue  # direct nested tables were already promoted above.
                    self._emit_table(
                        package,
                        emitter,
                        nested,
                        part=part,
                        zone=zone,
                        rels=rels,
                        content_hash=content_hash,
                        content_types=content_types,
                        path=(
                            f"{path}/r{row_index}/c{cell_index}/"
                            f"wrapped_tbl{nested_index}"
                        ),
                        parent_group=group_id,
                        wrappers=(
                            *wrappers,
                            *row_wrappers,
                            *cell_wrappers,
                            *nested_wrappers,
                        ),
                    )

    def _node_text(self, node: ET.Element) -> str:
        """Collect row/cell text without duplicating nested-table descendants."""

        chunks: list[str] = []

        def walk(current: ET.Element) -> None:
            for child in list(current):
                name = local_name(child.tag)
                if name == "tbl":
                    continue
                if name == "p":
                    value = self._paragraph_text(child)
                    if value.strip():
                        chunks.append(value)
                    continue
                walk(child)

        walk(node)
        return "\n".join(chunks)

    def _flatten_note_text(self, node: ET.Element) -> str:
        """Preserve all paragraph text when a note/comment is intentionally flattened."""

        chunks: list[str] = []
        for paragraph in node.findall(".//w:p", NS):
            value = self._paragraph_text(paragraph)
            if value.strip():
                chunks.append(value)
        return "\n".join(chunks)

    def _read_notes(
        self,
        package,
        emitter: Emitter,
        part: str,
        kind: str,
    ) -> None:
        root = self._read_xml(package, part)
        if root is None:
            return
        tag = {"footnote": "footnote", "endnote": "endnote", "comment": "comment"}[kind]
        seen: set[str] = set()
        for node in root.findall(f"w:{tag}", NS):
            note_id = node.attrib.get(W + "id")
            if note_id is None:
                continue
            if kind in {"footnote", "endnote"} and note_id in {"-1", "0"}:
                continue
            if note_id in seen:
                raise AdapterError(f"duplicate {kind} id {note_id!r}")
            seen.add(note_id)
            complex_names = {
                local_name(item.tag)
                for item in node.iter()
                if local_name(item.tag)
                in {"tbl", "altChunk", "drawing", "pict", "object", "oMath", "oMathPara"}
            }
            if complex_names:
                self._diagnostics.append(
                    AdapterDiagnostic(
                        code=f"{kind.upper()}_COMPLEX_STRUCTURE_FLATTENED",
                        message=(
                            f"{kind} text was preserved but nested complex structure "
                            "was not promoted to first-class blocks"
                        ),
                        affects_structural_completeness=True,
                        part=part,
                        metadata={"id": note_id, "constructs": sorted(complex_names)},
                    )
                )
            attrs: dict[str, object] = {
                "zone": kind,
                "note_kind": kind,
                SOURCE_ANCHOR_ATTRIBUTE: {"kind": kind, "id": note_id},
            }
            if kind == "comment":
                author = node.attrib.get(W + "author")
                date = node.attrib.get(W + "date")
                if author:
                    attrs["author"] = author
                if date:
                    attrs["date"] = date
            emitter.emit(
                text=self._flatten_note_text(node),
                type_hint="FOOTNOTE",
                part=part,
                attributes=attrs,
            )

    def _heading_level(self, ppr: ET.Element | None, style_def: object | None) -> int | None:
        value = super()._heading_level(ppr, style_def)
        # OOXML outlineLvl=9 denotes body text, not a tenth heading level.
        return None if value == 10 else value
