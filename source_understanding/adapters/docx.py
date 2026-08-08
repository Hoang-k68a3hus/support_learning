from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

from source_understanding.schemas.context import StructureSource
from source_understanding.schemas.document import Asset
from source_understanding.schemas.element import StyleInfo
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    INTEGRITY_PARENT_GROUP_ID_ATTRIBUTE,
    SOURCE_ANCHOR_ATTRIBUTE,
    SOURCE_REFERENCES_ATTRIBUTE,
)

from .base import AdapterDiagnostic, AdapterDiagnosticLevel, AdapterError, SourceAdapterResult
from ._docx_common import (
    A, M, NS, R, W, WP,
    DOCX_ADAPTER_VERSION, DOCX_MEDIA_TYPE, DOCX_POLICY_VERSION,
    DocxAdapterPolicy, Emitter, RevisionView,
    half_points, int_attr, local_name, on_off, stable_group_id,
)
from ._docx_package import DocxPackageMixin
from ._docx_extract import DocxExtractMixin
from ._docx_text import DocxTextMixin


class DocxAdapter(DocxPackageMixin, DocxExtractMixin, DocxTextMixin):
    """Source-near OOXML adapter for Word documents.

    DOCX is reflowable, therefore this adapter intentionally emits no page or
    bounding-box coordinates. Native OOXML structure is preserved as RawElement
    type hints and format-agnostic source attributes for the downstream core.
    """

    name = "docx-ooxml"
    version = DOCX_ADAPTER_VERSION
    media_types = (DOCX_MEDIA_TYPE,)
    extensions = (".docx",)

    def __init__(self, policy: DocxAdapterPolicy | None = None) -> None:
        self.policy = policy if policy is not None else DocxAdapterPolicy()
        self._reset_state()

    def adapt(self, data: bytes, *, source_name: str | None = None) -> SourceAdapterResult:
        self._reset_state()
        if not isinstance(data, (bytes, bytearray)):
            raise AdapterError("DOCX adapter input must be bytes")
        payload = bytes(data)
        if not payload:
            raise AdapterError("DOCX package is empty")
        if len(payload) > self.policy.max_package_bytes:
            raise AdapterError("DOCX package exceeds max_package_bytes")
        content_hash = SourceAdapterResult.hash_bytes(payload)
        try:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as package:
                self._validate_package(package)
                content_types = self._content_types(package)
                self._styles = self._read_styles(package)
                self._numbering = self._read_numbering(package)
                metadata = self._read_metadata(package, source_name=source_name)
                emitter = Emitter(self)
                self._read_document(package, emitter, content_hash, content_types)
                if self.policy.include_notes:
                    self._read_notes(package, emitter, "word/footnotes.xml", "footnote")
                    self._read_notes(package, emitter, "word/endnotes.xml", "endnote")
                if self.policy.include_comments:
                    self._read_notes(package, emitter, "word/comments.xml", "comment")
                if self.policy.include_headers_footers:
                    self._read_header_footer_parts(
                        package, emitter, content_hash, content_types
                    )
                assets = tuple(self._assets_by_part[key] for key in sorted(self._assets_by_part))
        except zipfile.BadZipFile as exc:
            raise AdapterError("input is not a valid DOCX/ZIP package") from exc
        if not emitter.elements:
            self._diagnostics.append(
                AdapterDiagnostic(
                    code="EMPTY_DOCUMENT",
                    message="DOCX contains no extractable source elements",
                    affects_structural_completeness=True,
                )
            )
        return SourceAdapterResult(
            adapter_name=self.name,
            adapter_version=self.version,
            media_type=DOCX_MEDIA_TYPE,
            source_name=source_name,
            content_hash=content_hash,
            raw_elements=tuple(emitter.elements),
            assets=assets,
            metadata=metadata,
            diagnostics=tuple(self._diagnostics),
            configuration=self.policy.model_dump(mode="json"),
        )

    def _reset_state(self) -> None:
        self._diagnostics: list[AdapterDiagnostic] = []
        self._styles = {}
        self._numbering = {}
        self._assets_by_part: dict[str, Asset] = {}
        self._asset_id_by_rel: dict[tuple[str, str], str] = {}
        self._header_footer_parts: set[str] = set()
        self._list_run: dict[tuple[str, str], tuple[str, str]] = {}
