from __future__ import annotations

import io
import zipfile

from source_understanding.schemas.document import Asset

from ._docx_common import (
    DOCX_ADAPTER_VERSION,
    DOCX_MEDIA_TYPE,
    DocxAdapterPolicy,
    Emitter,
)
from ._docx_extract import DocxExtractMixin
from ._docx_fixups import DocxFixupMixin
from ._docx_package import DocxPackageMixin
from ._docx_postprocess import DocxPostprocessMixin
from ._docx_preservation import DocxPreservationMixin
from ._docx_styles import DocxStyleMixin
from ._docx_text import DocxTextMixin
from .base import AdapterDiagnostic, AdapterError, SourceAdapterResult


class DocxAdapter(
    DocxStyleMixin,
    DocxPackageMixin,
    DocxPostprocessMixin,
    DocxFixupMixin,
    DocxPreservationMixin,
    DocxExtractMixin,
    DocxTextMixin,
):
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
                self._normalize_list_integrity(emitter)
                assets = tuple(
                    self._assets_by_part[key] for key in sorted(self._assets_by_part)
                )
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
