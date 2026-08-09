from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from xml.etree import ElementTree as ET

from pydantic import Field, model_validator

from source_understanding.schemas.context import SchemaModel, StructureSource
from source_understanding.schemas.element import Provenance, RawElement, StyleInfo
from source_understanding.source_attributes import SOURCE_ZONE_ATTRIBUTE
from .base import AdapterError

DOCX_ADAPTER_VERSION = "3"
DOCX_POLICY_VERSION = "1"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "rels": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
W = "{%s}" % NS["w"]
R = "{%s}" % NS["r"]
M = "{%s}" % NS["m"]
A = "{%s}" % NS["a"]
WP = "{%s}" % NS["wp"]
RELS = "{%s}" % NS["rels"]
CT = "{%s}" % NS["ct"]


class RevisionView(StrEnum):
    FINAL = "FINAL"
    ORIGINAL = "ORIGINAL"
    ALL = "ALL"


class DocxAdapterPolicy(SchemaModel):
    version: str = DOCX_POLICY_VERSION
    include_headers_footers: bool = True
    include_notes: bool = True
    include_comments: bool = True
    extract_assets: bool = True
    revision_view: RevisionView = RevisionView.FINAL
    max_package_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    max_entry_count: int = Field(default=10_000, ge=10)
    max_total_uncompressed_bytes: int = Field(default=512 * 1024 * 1024, ge=1024)
    max_xml_part_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    max_asset_bytes: int = Field(default=128 * 1024 * 1024, ge=1024)
    max_elements: int = Field(default=200_000, ge=1)
    max_text_chars_per_element: int = Field(default=1_000_000, ge=1)

    @model_validator(mode="after")
    def validate_limits(self) -> "DocxAdapterPolicy":
        if self.max_xml_part_bytes > self.max_total_uncompressed_bytes:
            raise ValueError("max_xml_part_bytes cannot exceed max_total_uncompressed_bytes")
        return self


@dataclass(frozen=True)
class Relationship:
    rel_id: str
    rel_type: str
    target: str
    external: bool


@dataclass(frozen=True)
class StyleDef:
    style_id: str
    name: str | None
    outline_level: int | None
    num_id: str | None
    ilvl: int | None
    based_on: str | None


@dataclass(frozen=True)
class ListLevel:
    num_format: str | None
    level_text: str | None


class Emitter:
    def __init__(self, adapter: object) -> None:
        self.adapter = adapter
        self.elements: list[RawElement] = []

    def emit(
        self,
        *,
        text: str | None,
        type_hint: str,
        part: str,
        attributes: dict[str, object] | None = None,
        style: StyleInfo | None = None,
        source: StructureSource = StructureSource.EXPLICIT,
    ) -> None:
        policy = self.adapter.policy
        if len(self.elements) >= policy.max_elements:
            raise AdapterError(f"DOCX element count exceeds max_elements={policy.max_elements}")
        if text is not None and len(text) > policy.max_text_chars_per_element:
            raise AdapterError(
                "DOCX element text exceeds max_text_chars_per_element; refusing lossy truncation"
            )
        attrs = {"opc_part": part, **(attributes or {})}
        zone = attrs.get("zone")
        if isinstance(zone, str) and zone:
            attrs.setdefault(SOURCE_ZONE_ATTRIBUTE, zone)
        self.elements.append(
            RawElement(
                text=text,
                type_hint=type_hint,
                order=len(self.elements),
                location=None,
                style=style,
                attributes=attrs,
                provenance=Provenance(
                    source=source,
                    extractor=self.adapter.name,
                    extractor_version=self.adapter.version,
                    metadata={
                        "media_type": DOCX_MEDIA_TYPE,
                        "location_policy": "reflowable_docx_no_page_or_bbox",
                    },
                ),
            )
        )


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def optional_text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def int_attr(node: ET.Element | None, name: str) -> int | None:
    if node is None:
        return None
    value = node.attrib.get(W + name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def half_points(node: ET.Element | None) -> float | None:
    if node is None:
        return None
    value = node.attrib.get(W + "val")
    if value is None:
        return None
    try:
        return int(value) / 2.0
    except ValueError:
        return None


def on_off(node: ET.Element | None) -> bool | None:
    if node is None:
        return None
    value = (node.attrib.get(W + "val") or "true").casefold()
    return value not in {"0", "false", "off", "no"}


def stable_group_id(*parts: str) -> str:
    return "srcgrp_" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
