from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import Field

from source_understanding.schemas.context import SchemaModel, StructureSource
from source_understanding.schemas.document import DocumentMetadata
from source_understanding.schemas.element import Provenance, RawElement, SourceLocation
from source_understanding.source_attributes import SOURCE_ZONE_ATTRIBUTE

from .base import (
    AdapterDiagnostic,
    AdapterDiagnosticLevel,
    AdapterError,
    SourceAdapterResult,
)
from ._text_common import (
    decode_text_payload,
    source_lines,
)


PLAIN_TEXT_ADAPTER_VERSION = "1"
PLAIN_TEXT_POLICY_VERSION = "1"
PLAIN_TEXT_MEDIA_TYPE = "text/plain"


class PlainTextEncoding(StrEnum):
    """Deterministic decoders; AUTO only performs BOM detection, never guessing."""

    AUTO = "AUTO"
    UTF8 = "UTF-8"
    UTF16_LE = "UTF-16-LE"
    UTF16_BE = "UTF-16-BE"


class PlainTextAdapterPolicy(SchemaModel):
    version: str = PLAIN_TEXT_POLICY_VERSION
    encoding: PlainTextEncoding = PlainTextEncoding.AUTO
    max_source_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)
    reject_nul: bool = True


class PlainTextAdapter:
    """Preserve a deterministic decoded text view as paragraphs and separators.

    Paragraph boundaries come only from explicit blank-line observations. The
    adapter does not infer headings, lists, Q&A, code, or semantic roles. Every
    emitted raw-text span includes its original line endings, so concatenating
    all RawElement texts reproduces the complete adapter source-text view.
    """

    name = "plain-text"
    version = PLAIN_TEXT_ADAPTER_VERSION
    media_types = (PLAIN_TEXT_MEDIA_TYPE,)
    extensions = (".txt", ".text")

    def __init__(self, policy: PlainTextAdapterPolicy | None = None) -> None:
        self.policy = policy if policy is not None else PlainTextAdapterPolicy()

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        if not isinstance(data, (bytes, bytearray)):
            raise AdapterError("plain-text adapter input must be bytes")
        payload = bytes(data)
        if len(payload) > self.policy.max_source_bytes:
            raise AdapterError("plain-text source exceeds max_source_bytes")

        text, encoding, bom = self._decode(payload)
        if self.policy.reject_nul and "\x00" in text:
            raise AdapterError(
                "plain-text source contains NUL characters; provide a correct "
                "encoding or a non-text adapter"
            )

        source_view_hash = "sha256:" + hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
        diagnostics: list[AdapterDiagnostic] = []
        if bom is not None:
            diagnostics.append(
                AdapterDiagnostic(
                    code="TEXT_ENCODING_BOM_DETECTED",
                    message=f"decoded explicit {bom} byte-order mark",
                    level=AdapterDiagnosticLevel.INFO,
                    metadata={"encoding": encoding, "bom": bom},
                )
            )

        raw_elements = self._elements(
            text,
            encoding=encoding,
            source_view_hash=source_view_hash,
        )
        if not raw_elements:
            diagnostics.append(
                AdapterDiagnostic(
                    code="EMPTY_DOCUMENT",
                    message="plain-text source contains no decoded characters",
                    affects_structural_completeness=True,
                )
            )

        return SourceAdapterResult(
            adapter_name=self.name,
            adapter_version=self.version,
            media_type=PLAIN_TEXT_MEDIA_TYPE,
            source_name=source_name,
            content_hash=SourceAdapterResult.hash_bytes(payload),
            raw_elements=raw_elements,
            metadata=DocumentMetadata(
                source_name=source_name,
                attributes={
                    "plain_text": {
                        "encoding": encoding,
                        "bom": bom,
                        "source_text_char_count": len(text),
                        "source_text_hash": source_view_hash,
                        "line_count": len(self._source_lines(text)),
                    }
                },
            ),
            diagnostics=tuple(diagnostics),
            configuration=self.policy.model_dump(mode="json"),
        )

    def _decode(self, payload: bytes) -> tuple[str, str, str | None]:
        return decode_text_payload(
            payload,
            self.policy.encoding,
            adapter_label="plain-text",
        )

    def _elements(
        self,
        text: str,
        *,
        encoding: str,
        source_view_hash: str,
    ) -> tuple[RawElement, ...]:
        lines = self._source_lines(text)
        if not lines:
            return ()

        blocks: list[tuple[bool, int, int, int, int, str]] = []
        char_cursor = 0
        line_number = 1
        block_blank: bool | None = None
        block_start_char = 0
        block_start_line = 1
        block_parts: list[str] = []

        def flush(end_char: int, end_line: int) -> None:
            if block_blank is None:
                return
            blocks.append(
                (
                    block_blank,
                    block_start_char,
                    end_char,
                    block_start_line,
                    end_line,
                    "".join(block_parts),
                )
            )

        for line in lines:
            blank = not line.rstrip("\r\n").strip()
            if block_blank is None:
                block_blank = blank
                block_start_char = char_cursor
                block_start_line = line_number
            elif blank != block_blank:
                flush(char_cursor, line_number - 1)
                block_parts = []
                block_blank = blank
                block_start_char = char_cursor
                block_start_line = line_number
            block_parts.append(line)
            char_cursor += len(line)
            line_number += 1
        flush(char_cursor, line_number - 1)

        return tuple(
            RawElement(
                text=value,
                type_hint="SEPARATOR" if blank else "PARAGRAPH",
                order=order,
                location=SourceLocation(
                    source=StructureSource.EXPLICIT,
                    start_char=start_char,
                    end_char=end_char,
                    line_start=line_start,
                    line_end=line_end,
                ),
                attributes={SOURCE_ZONE_ATTRIBUTE: "body"},
                provenance=Provenance(
                    source=StructureSource.EXPLICIT,
                    extractor=self.name,
                    extractor_version=self.version,
                    metadata={
                        "encoding": encoding,
                        "source_text_hash": source_view_hash,
                    },
                ),
            )
            for order, (
                blank,
                start_char,
                end_char,
                line_start,
                line_end,
                value,
            ) in enumerate(blocks)
        )

    @staticmethod
    def _source_lines(text: str) -> tuple[str, ...]:
        return source_lines(text)
