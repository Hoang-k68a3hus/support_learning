from __future__ import annotations

from xml.etree import ElementTree as ET

from ._docx_common import Emitter, local_name, stable_group_id


class DocxTextboxMixin:
    """Promote effective Word text-box tables without duplicating fallback branches."""

    def _emit_block(
        self,
        package,
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
        if local_name(node.tag) != "p":
            return

        # DocxFixupMixin emits a paragraph-level section break from pPr after the
        # paragraph. Embedded text-box blocks are still inside that paragraph, so
        # keep them before the section boundary in canonical source order.
        trailing_section_separator = None
        if len(emitter.elements) > element_count_before:
            candidate = emitter.elements[-1]
            if (
                candidate.type_hint == "SEPARATOR"
                and candidate.attributes.get("separator_kind") == "section_break"
            ):
                trailing_section_separator = emitter.elements.pop()

        self._emit_embedded_textbox_tables(
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

        if trailing_section_separator is not None:
            emitter.elements.append(
                trailing_section_separator.model_copy(
                    update={"order": len(emitter.elements)}
                )
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
                self._emit_embedded_textbox_tables(
                    package,
                    emitter,
                    cell,
                    part=part,
                    zone=zone,
                    rels=rels,
                    content_hash=content_hash,
                    content_types=content_types,
                    path=f"{path}/r{row_index}/c{cell_index}",
                    parent_group=group_id,
                    wrappers=(*wrappers, *row_wrappers, *cell_wrappers),
                )

    def _emit_embedded_textbox_tables(
        self,
        package,
        emitter: Emitter,
        container: ET.Element,
        *,
        part: str,
        zone: str,
        rels: dict[str, object],
        content_hash: str,
        content_types: dict[str, str],
        path: str,
        parent_group: str | None,
        wrappers: tuple[dict[str, object], ...],
    ) -> None:
        for relative_path, table, embedded_wrappers in self._iter_effective_textbox_tables(
            container
        ):
            self._emit_table(
                package,
                emitter,
                table,
                part=part,
                zone=zone,
                rels=rels,
                content_hash=content_hash,
                content_types=content_types,
                path=f"{path}/embedded/{relative_path}",
                parent_group=parent_group,
                wrappers=(*wrappers, *embedded_wrappers),
            )

    def _iter_effective_textbox_tables(
        self,
        container: ET.Element,
    ) -> tuple[tuple[str, ET.Element, tuple[dict[str, object], ...]], ...]:
        """Find first-class tables in the effective text-box source view.

        Word commonly serializes the same text-box twice inside
        ``mc:AlternateContent``: a modern ``Choice`` and a legacy ``Fallback``.
        Traversing both duplicates source content. The adapter therefore selects
        the first Choice when present, otherwise Fallback, and promotes only
        tables below ``txbxContent``. Normal direct/nested Word tables remain
        owned by the regular table extractor.
        """

        tables: list[tuple[str, ET.Element, tuple[dict[str, object], ...]]] = []
        contextual_names = {
            "sdt",
            "customXml",
            "ins",
            "del",
            "moveFrom",
            "moveTo",
            "drawing",
            "pict",
            "wsp",
            "txbx",
            "textbox",
            "txbxContent",
        }
        revision_names = {"ins", "del", "moveFrom", "moveTo"}

        def wrapper_for(node: ET.Element, path: str) -> dict[str, object]:
            name = local_name(node.tag)
            wrapper: dict[str, object] = {"kind": name, "path": path}
            if name == "sdt":
                wrapper.update(self._sdt_properties(node))
            return wrapper

        def selected_alternate_branch(
            node: ET.Element,
        ) -> tuple[ET.Element | None, int | None]:
            children = list(node)
            for index, child in enumerate(children):
                if local_name(child.tag) == "Choice":
                    return child, index
            for index, child in enumerate(children):
                if local_name(child.tag) == "Fallback":
                    return child, index
            return None, None

        def walk(
            node: ET.Element,
            node_path: str,
            context: tuple[dict[str, object], ...],
            *,
            inside_textbox: bool,
        ) -> None:
            name = local_name(node.tag)
            if name == "AlternateContent":
                branch, branch_index = selected_alternate_branch(node)
                if branch is None or branch_index is None:
                    return
                alternate_wrapper = {
                    "kind": "AlternateContent",
                    "path": node_path,
                }
                branch_name = local_name(branch.tag)
                branch_path = f"{node_path}/{branch_name}[{branch_index}]"
                branch_wrapper: dict[str, object] = {
                    "kind": branch_name,
                    "path": branch_path,
                    "alternate_branch": "SELECTED",
                }
                requires = branch.attrib.get("Requires")
                if requires:
                    branch_wrapper["requires"] = requires
                branch_context = (*context, alternate_wrapper, branch_wrapper)
                for index, child in enumerate(list(branch)):
                    child_path = f"{branch_path}/{local_name(child.tag)}[{index}]"
                    walk(
                        child,
                        child_path,
                        branch_context,
                        inside_textbox=inside_textbox,
                    )
                return

            if name in revision_names and not self._include_revision(name):
                return

            next_context = context
            if name in contextual_names:
                next_context = (*context, wrapper_for(node, node_path))
            next_inside_textbox = inside_textbox or name == "txbxContent"

            if name == "tbl":
                if next_inside_textbox:
                    tables.append((node_path, node, next_context))
                return

            for index, child in enumerate(list(node)):
                child_path = f"{node_path}/{local_name(child.tag)}[{index}]"
                walk(
                    child,
                    child_path,
                    next_context,
                    inside_textbox=next_inside_textbox,
                )

        walk(container, local_name(container.tag), (), inside_textbox=False)
        return tuple(tables)
