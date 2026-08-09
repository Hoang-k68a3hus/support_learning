from __future__ import annotations

import zipfile

from ._docx_common import NS, W, StyleDef, int_attr
from .base import AdapterDiagnostic, AdapterDiagnosticLevel, AdapterError


class DocxStyleMixin:
    """Resolve DOCX styles conservatively, including compatible duplicate styleIds.

    Some real Word packages contain repeated style definitions. The adapter merges
    definitions only when non-null structural fields are compatible. Conflicting
    non-null structural values remain an error rather than silently choosing one.
    """

    def _read_styles(self, package: zipfile.ZipFile) -> dict[str, StyleDef]:
        root = self._read_xml(package, "word/styles.xml")
        if root is None:
            return {}
        raw: dict[str, StyleDef] = {}
        duplicate_counts: dict[str, int] = {}
        for style in root.findall("w:style", NS):
            style_id = style.attrib.get(W + "styleId")
            if not style_id:
                continue
            name_node = style.find("w:name", NS)
            based = style.find("w:basedOn", NS)
            outline = style.find("w:pPr/w:outlineLvl", NS)
            num_pr = style.find("w:pPr/w:numPr", NS)
            num_id, ilvl = self._num_pr(num_pr)
            current = StyleDef(
                style_id=style_id,
                name=name_node.attrib.get(W + "val") if name_node is not None else None,
                outline_level=int_attr(outline, "val"),
                num_id=num_id,
                ilvl=ilvl,
                based_on=based.attrib.get(W + "val") if based is not None else None,
            )
            previous = raw.get(style_id)
            if previous is None:
                raw[style_id] = current
                continue
            raw[style_id] = self._merge_compatible_style(previous, current)
            duplicate_counts[style_id] = duplicate_counts.get(style_id, 1) + 1

        for style_id, count in sorted(duplicate_counts.items()):
            self._diagnostics.append(
                AdapterDiagnostic(
                    code="COMPATIBLE_DUPLICATE_STYLE_MERGED",
                    message="compatible duplicate DOCX style definitions were merged",
                    level=AdapterDiagnosticLevel.INFO,
                    part="word/styles.xml",
                    metadata={"style_id": style_id, "definition_count": count},
                )
            )

        resolved: dict[str, StyleDef] = {}

        def resolve(style_id: str, trail: tuple[str, ...] = ()) -> StyleDef:
            if style_id in resolved:
                return resolved[style_id]
            if style_id in trail:
                raise AdapterError(f"DOCX style inheritance cycle at {style_id!r}")
            item = raw[style_id]
            parent = None
            if item.based_on:
                if item.based_on in raw:
                    parent = resolve(item.based_on, (*trail, style_id))
                else:
                    self._diagnostics.append(
                        AdapterDiagnostic(
                            code="MISSING_BASE_STYLE",
                            message="DOCX style basedOn target is missing",
                            affects_structural_completeness=True,
                            part="word/styles.xml",
                            metadata={"style_id": style_id, "based_on": item.based_on},
                        )
                    )
            resolved_item = StyleDef(
                style_id=item.style_id,
                name=item.name or (parent.name if parent else None),
                outline_level=(
                    item.outline_level
                    if item.outline_level is not None
                    else (parent.outline_level if parent else None)
                ),
                num_id=item.num_id or (parent.num_id if parent else None),
                ilvl=(
                    item.ilvl
                    if item.num_id is not None
                    else (parent.ilvl if parent else item.ilvl)
                ),
                based_on=item.based_on,
            )
            resolved[style_id] = resolved_item
            return resolved_item

        for style_id in raw:
            resolve(style_id)
        return resolved

    @staticmethod
    def _merge_compatible_style(left: StyleDef, right: StyleDef) -> StyleDef:
        conflicts: dict[str, tuple[object, object]] = {}
        for field_name in ("outline_level", "num_id", "ilvl", "based_on"):
            left_value = getattr(left, field_name)
            right_value = getattr(right, field_name)
            if left_value is not None and right_value is not None and left_value != right_value:
                conflicts[field_name] = (left_value, right_value)
        if conflicts:
            rendered = ", ".join(
                f"{name}={values[0]!r}/{values[1]!r}"
                for name, values in sorted(conflicts.items())
            )
            raise AdapterError(
                f"conflicting duplicate DOCX styleId {left.style_id!r}: {rendered}"
            )
        return StyleDef(
            style_id=left.style_id,
            name=right.name or left.name,
            outline_level=(
                right.outline_level if right.outline_level is not None else left.outline_level
            ),
            num_id=right.num_id if right.num_id is not None else left.num_id,
            ilvl=right.ilvl if right.ilvl is not None else left.ilvl,
            based_on=right.based_on if right.based_on is not None else left.based_on,
        )
