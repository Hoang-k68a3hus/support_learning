from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from xml.etree import ElementTree as ET

from source_understanding.schemas.document import Asset, DocumentMetadata

from ._docx_common import (
    NS,
    W,
    ListLevel,
    Relationship,
    int_attr,
    local_name,
    optional_text,
)
from .base import AdapterDiagnostic, AdapterDiagnosticLevel, AdapterError


class DocxPackageMixin:
    def _validate_package(self, package: zipfile.ZipFile) -> None:
        infos = package.infolist()
        if len(infos) > self.policy.max_entry_count:
            raise AdapterError(
                f"DOCX entry count exceeds max_entry_count={self.policy.max_entry_count}"
            )
        names: set[str] = set()
        total = 0
        for info in infos:
            name = info.filename
            if name in names:
                raise AdapterError(f"DOCX contains duplicate OPC part name {name!r}")
            names.add(name)
            if "\\" in name or name.startswith("/"):
                raise AdapterError(f"DOCX contains unsafe OPC path {name!r}")
            normalized = posixpath.normpath(name)
            if normalized == ".." or normalized.startswith("../"):
                raise AdapterError(f"DOCX OPC path escapes package root: {name!r}")
            if info.flag_bits & 0x1:
                raise AdapterError(f"encrypted DOCX entry is unsupported: {name!r}")
            total += info.file_size
        if total > self.policy.max_total_uncompressed_bytes:
            raise AdapterError(
                "DOCX total uncompressed size exceeds configured safety limit"
            )
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise AdapterError("DOCX package is missing required OOXML parts")

    def _read_xml(self, package: zipfile.ZipFile, part: str) -> ET.Element | None:
        try:
            info = package.getinfo(part)
        except KeyError:
            return None
        if info.file_size > self.policy.max_xml_part_bytes:
            raise AdapterError(
                f"XML part {part!r} exceeds max_xml_part_bytes="
                f"{self.policy.max_xml_part_bytes}"
            )
        data = package.read(part)
        if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.I):
            raise AdapterError(
                f"DTD/entity declarations are forbidden in XML part {part!r}"
            )
        try:
            return ET.fromstring(data)
        except ET.ParseError as exc:
            raise AdapterError(f"malformed XML part {part!r}: {exc}") from exc

    def _content_types(self, package: zipfile.ZipFile) -> dict[str, str]:
        root = self._read_xml(package, "[Content_Types].xml")
        if root is None:
            return {}
        defaults: dict[str, str] = {}
        overrides: dict[str, str] = {}
        for node in root:
            name = local_name(node.tag)
            if name == "Default":
                ext = node.attrib.get("Extension")
                media = node.attrib.get("ContentType")
                if ext and media:
                    key = ext.casefold()
                    if key in defaults and defaults[key] != media:
                        raise AdapterError(
                            f"conflicting content type default for extension {ext!r}"
                        )
                    defaults[key] = media
            elif name == "Override":
                part = node.attrib.get("PartName")
                media = node.attrib.get("ContentType")
                if part and media:
                    part = part.lstrip("/")
                    if part in overrides and overrides[part] != media:
                        raise AdapterError(
                            f"conflicting content type override for {part!r}"
                        )
                    overrides[part] = media
        result = dict(overrides)
        for info in package.infolist():
            if info.filename in result:
                continue
            ext = (
                info.filename.rsplit(".", 1)[-1].casefold()
                if "." in info.filename
                else ""
            )
            if ext in defaults:
                result[info.filename] = defaults[ext]
        return result

    def _read_metadata(
        self,
        package: zipfile.ZipFile,
        *,
        source_name: str | None,
    ) -> DocumentMetadata:
        title = None
        authors: tuple[str, ...] = ()
        created = None
        root = self._read_xml(package, "docProps/core.xml")
        if root is not None:
            title = optional_text(root.find("dc:title", NS))
            creator = optional_text(root.find("dc:creator", NS))
            if creator:
                authors = (creator,)
            created_text = optional_text(root.find("dcterms:created", NS))
            if created_text:
                try:
                    created = datetime.fromisoformat(
                        created_text.replace("Z", "+00:00")
                    )
                except ValueError:
                    self._diagnostics.append(
                        AdapterDiagnostic(
                            code="INVALID_CORE_CREATED_AT",
                            message="DOCX created datetime could not be parsed",
                            level=AdapterDiagnosticLevel.INFO,
                            metadata={"value": created_text},
                        )
                    )
        language = self._default_language(package)
        return DocumentMetadata(
            title=title,
            authors=authors,
            created_at=created,
            language=language,
            source_name=source_name,
            attributes={"format": "docx", "reflowable": True},
        )

    def _default_language(self, package: zipfile.ZipFile) -> str | None:
        root = self._read_xml(package, "word/styles.xml")
        if root is None:
            return None
        lang = root.find(".//w:docDefaults/w:rPrDefault/w:rPr/w:lang", NS)
        if lang is None:
            return None
        return lang.attrib.get(W + "val") or lang.attrib.get(W + "eastAsia")

    def _read_numbering(
        self,
        package: zipfile.ZipFile,
    ) -> dict[tuple[str, int], ListLevel]:
        root = self._read_xml(package, "word/numbering.xml")
        if root is None:
            return {}
        abstract: dict[str, dict[int, ListLevel]] = defaultdict(dict)
        for node in root.findall("w:abstractNum", NS):
            abstract_id = node.attrib.get(W + "abstractNumId")
            if abstract_id is None:
                continue
            for lvl in node.findall("w:lvl", NS):
                ilvl = int_attr(lvl, "ilvl")
                if ilvl is None:
                    continue
                fmt = lvl.find("w:numFmt", NS)
                text = lvl.find("w:lvlText", NS)
                abstract[abstract_id][ilvl] = ListLevel(
                    num_format=fmt.attrib.get(W + "val") if fmt is not None else None,
                    level_text=text.attrib.get(W + "val") if text is not None else None,
                )
        result: dict[tuple[str, int], ListLevel] = {}
        seen_num: set[str] = set()
        for node in root.findall("w:num", NS):
            num_id = node.attrib.get(W + "numId")
            if num_id is None:
                continue
            if num_id in seen_num:
                raise AdapterError(f"duplicate DOCX numId {num_id!r}")
            seen_num.add(num_id)
            abs_node = node.find("w:abstractNumId", NS)
            abs_id = abs_node.attrib.get(W + "val") if abs_node is not None else None
            if abs_id is None:
                continue
            for ilvl, level in abstract.get(abs_id, {}).items():
                result[(num_id, ilvl)] = level
        return result

    def _relationships(
        self,
        package: zipfile.ZipFile,
        source_part: str,
    ) -> dict[str, Relationship]:
        directory, filename = posixpath.split(source_part)
        rel_part = posixpath.join(directory, "_rels", filename + ".rels")
        root = self._read_xml(package, rel_part)
        if root is None:
            return {}
        result: dict[str, Relationship] = {}
        base = posixpath.dirname(source_part)
        for node in root.findall("rels:Relationship", NS):
            rel_id = node.attrib.get("Id")
            rel_type = node.attrib.get("Type")
            target = node.attrib.get("Target")
            if not rel_id or not rel_type or target is None:
                continue
            if rel_id in result:
                raise AdapterError(
                    f"duplicate relationship Id {rel_id!r} in {rel_part!r}"
                )
            external = node.attrib.get("TargetMode", "").casefold() == "external"
            resolved = target
            if not external:
                if "\\" in target:
                    raise AdapterError(
                        f"relationship {rel_id!r} uses invalid OPC path separator"
                    )
                resolved = posixpath.normpath(posixpath.join(base, target))
                if (
                    resolved == ".."
                    or resolved.startswith("../")
                    or resolved.startswith("/")
                ):
                    raise AdapterError(
                        f"relationship {rel_id!r} escapes OPC package root"
                    )
            result[rel_id] = Relationship(rel_id, rel_type, resolved, external)
        return result

    def _register_assets(
        self,
        package: zipfile.ZipFile,
        source_part: str,
        relationships: dict[str, Relationship],
        content_hash: str,
        content_types: dict[str, str],
    ) -> None:
        if not self.policy.extract_assets:
            return
        for rel_id, rel in relationships.items():
            if rel.external or "/image" not in rel.rel_type:
                continue
            asset_id = self._register_part_asset(
                package,
                source_part=source_part,
                target_part=rel.target,
                content_hash=content_hash,
                content_types=content_types,
                missing_code="MISSING_IMAGE_PART",
            )
            if asset_id:
                self._asset_id_by_rel[(source_part, rel_id)] = asset_id

    def _register_part_asset(
        self,
        package: zipfile.ZipFile,
        *,
        source_part: str,
        target_part: str,
        content_hash: str,
        content_types: dict[str, str],
        missing_code: str,
    ) -> str | None:
        try:
            info = package.getinfo(target_part)
        except KeyError:
            self._diagnostics.append(
                AdapterDiagnostic(
                    code=missing_code,
                    message="DOCX relationship targets a missing OPC part",
                    affects_structural_completeness=True,
                    part=source_part,
                    metadata={"target": target_part},
                )
            )
            return None
        if target_part not in self._assets_by_part:
            digest = hashlib.sha256(
                (content_hash + "|" + target_part).encode("utf-8")
            ).hexdigest()[:24]
            metadata: dict[str, object] = {
                "opc_part": target_part,
                "byte_size": info.file_size,
                "source_part": source_part,
            }
            if info.file_size <= self.policy.max_asset_bytes:
                payload = package.read(target_part)
                metadata["sha256"] = hashlib.sha256(payload).hexdigest()
                metadata["payload_hash_assessed"] = True
            else:
                metadata["payload_hash_assessed"] = False
                metadata["payload_hash_skip_reason"] = "max_asset_bytes"
                self._diagnostics.append(
                    AdapterDiagnostic(
                        code="ASSET_PAYLOAD_HASH_SKIPPED_TOO_LARGE",
                        message=(
                            "large DOCX asset preserved by descriptor without "
                            "payload hashing"
                        ),
                        part=target_part,
                        metadata={"byte_size": info.file_size},
                    )
                )
            self._assets_by_part[target_part] = Asset(
                id=f"asset_{digest}",
                type=content_types.get(target_part, "application/octet-stream"),
                uri=f"opc:///{target_part}",
                metadata=metadata,
            )
        return self._assets_by_part[target_part].id

    @staticmethod
    def _num_pr(num_pr: ET.Element | None) -> tuple[str | None, int]:
        if num_pr is None:
            return None, 0
        num = num_pr.find("w:numId", NS)
        lvl = num_pr.find("w:ilvl", NS)
        num_id = num.attrib.get(W + "val") if num is not None else None
        ilvl = int_attr(lvl, "val") or 0
        return num_id, ilvl
