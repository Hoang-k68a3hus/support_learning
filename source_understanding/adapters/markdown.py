from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field

from source_understanding.schemas.context import SchemaModel, StructureSource
from source_understanding.schemas.document import DocumentMetadata
from source_understanding.schemas.element import Provenance, RawElement, SourceLocation
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    INTEGRITY_GROUP_ID_ATTRIBUTE,
    SOURCE_LABEL_ATTRIBUTE,
    SOURCE_ZONE_ATTRIBUTE,
)

from ._text_common import (
    decode_text_payload,
    source_lines,
)
from .base import (
    AdapterDiagnostic,
    AdapterDiagnosticLevel,
    AdapterError,
    SourceAdapterResult,
)


MARKDOWN_ADAPTER_VERSION = "1"
MARKDOWN_POLICY_VERSION = "1"
MARKDOWN_MEDIA_TYPE = "text/markdown"


class MarkdownDialect(StrEnum):
    COMMONMARK_BLOCK_SUBSET_V1 = "COMMONMARK_BLOCK_SUBSET_V1"


class MarkdownEncoding(StrEnum):
    """Deterministic decoders; AUTO only performs BOM detection, never guessing."""

    AUTO = "AUTO"
    UTF8 = "UTF-8"
    UTF16_LE = "UTF-16-LE"
    UTF16_BE = "UTF-16-BE"


class MarkdownAdapterPolicy(SchemaModel):
    version: str = MARKDOWN_POLICY_VERSION
    dialect: MarkdownDialect = MarkdownDialect.COMMONMARK_BLOCK_SUBSET_V1
    encoding: MarkdownEncoding = MarkdownEncoding.AUTO
    max_source_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1,
        le=256 * 1024 * 1024,
    )
    reject_nul: bool = True


@dataclass(frozen=True)
class _SourceLine:
    text: str
    start_char: int
    end_char: int
    line_number: int


_ATX_RE = re.compile(
    r"^(?P<indent> {0,3})(?P<marker>#{1,6})(?:[ \t]+(?P<label>.*)|[ \t]*)$"
)
_SETEXT_RE = re.compile(r"^ {0,3}(?P<marker>=+|-+)[ \t]*$")
_FENCE_RE = re.compile(
    r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$"
)
_LIST_ITEM_RE = re.compile(
    r"^(?P<indent> {0,3})(?P<marker>(?:[-+*]|\d{1,9}[.)]))(?P<spacing>[ \t]+).*$"
)
_BLOCKQUOTE_RE = re.compile(r"^ {0,3}(?P<markers>>+)(?:[ \t]|$)")


class MarkdownAdapter:
    """Preserve Markdown source spans while exposing conservative block facts.

    V1 recognizes only unambiguous block syntax needed by structural parsing.
    Inline markup, front matter, and GFM tables remain inside paragraph/code raw
    spans rather than being guessed. Every decoded source character belongs to
    exactly one emitted RawElement and source locations never overlap.
    """

    name = "markdown-block-subset"
    version = MARKDOWN_ADAPTER_VERSION
    media_types = (MARKDOWN_MEDIA_TYPE, "text/x-markdown")
    extensions = (".md", ".markdown", ".mdown", ".mkd")

    def __init__(self, policy: MarkdownAdapterPolicy | None = None) -> None:
        self.policy = policy if policy is not None else MarkdownAdapterPolicy()

    def adapt(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
    ) -> SourceAdapterResult:
        if not isinstance(data, (bytes, bytearray)):
            raise AdapterError("Markdown adapter input must be bytes")
        payload = bytes(data)
        if len(payload) > self.policy.max_source_bytes:
            raise AdapterError("Markdown source exceeds max_source_bytes")

        text, encoding, bom = decode_text_payload(
            payload,
            self.policy.encoding,
            adapter_label="Markdown",
        )
        if self.policy.reject_nul and "\x00" in text:
            raise AdapterError(
                "Markdown source contains NUL characters; provide a correct "
                "encoding or a non-text adapter"
            )

        source_view_hash = "sha256:" + hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
        raw_elements, parser_diagnostics = self._elements(
            text,
            encoding=encoding,
            source_view_hash=source_view_hash,
        )
        diagnostics = list(parser_diagnostics)
        if bom is not None:
            diagnostics.insert(
                0,
                AdapterDiagnostic(
                    code="MARKDOWN_ENCODING_BOM_DETECTED",
                    message=f"decoded explicit {bom} byte-order mark",
                    level=AdapterDiagnosticLevel.INFO,
                    metadata={"encoding": encoding, "bom": bom},
                ),
            )
        if not raw_elements:
            diagnostics.append(
                AdapterDiagnostic(
                    code="EMPTY_DOCUMENT",
                    message="Markdown source contains no decoded characters",
                    affects_structural_completeness=True,
                )
            )

        return SourceAdapterResult(
            adapter_name=self.name,
            adapter_version=self.version,
            media_type=MARKDOWN_MEDIA_TYPE,
            source_name=source_name,
            content_hash=SourceAdapterResult.hash_bytes(payload),
            raw_elements=raw_elements,
            metadata=DocumentMetadata(
                source_name=source_name,
                attributes={
                    "markdown": {
                        "dialect": self.policy.dialect.value,
                        "encoding": encoding,
                        "bom": bom,
                        "source_text_char_count": len(text),
                        "source_text_hash": source_view_hash,
                        "line_count": len(source_lines(text)),
                        "source_text_view": "decoded_markdown_source",
                    }
                },
            ),
            diagnostics=tuple(diagnostics),
            configuration=self.policy.model_dump(mode="json"),
        )

    def _elements(
        self,
        text: str,
        *,
        encoding: str,
        source_view_hash: str,
    ) -> tuple[tuple[RawElement, ...], tuple[AdapterDiagnostic, ...]]:
        lines = self._located_lines(text)
        if not lines:
            return (), ()

        elements: list[RawElement] = []
        diagnostics: list[AdapterDiagnostic] = []

        def emit(
            start: int,
            end: int,
            type_hint: str,
            attributes: dict[str, object],
        ) -> None:
            first = lines[start]
            last = lines[end - 1]
            value = text[first.start_char : last.end_char]
            source_attributes = {
                SOURCE_ZONE_ATTRIBUTE: "body",
                **attributes,
            }
            elements.append(
                RawElement(
                    text=value,
                    type_hint=type_hint,
                    order=len(elements),
                    location=SourceLocation(
                        source=StructureSource.EXPLICIT,
                        start_char=first.start_char,
                        end_char=last.end_char,
                        line_start=first.line_number,
                        line_end=last.line_number,
                    ),
                    attributes=source_attributes,
                    provenance=Provenance(
                        source=StructureSource.EXPLICIT,
                        extractor=self.name,
                        extractor_version=self.version,
                        metadata={
                            "dialect": self.policy.dialect.value,
                            "encoding": encoding,
                            "source_text_hash": source_view_hash,
                        },
                    ),
                )
            )

        index = 0
        while index < len(lines):
            if self._is_blank(lines[index].text):
                end = index + 1
                while end < len(lines) and self._is_blank(lines[end].text):
                    end += 1
                emit(
                    index,
                    end,
                    "SEPARATOR",
                    {
                        "markdown_block_kind": "blank_lines",
                        "separator_kind": "blank_line",
                    },
                )
                index = end
                continue

            fence = self._fence_open(lines[index].text)
            if fence is not None:
                fence_char, fence_length, info = fence
                end = index + 1
                closed = False
                while end < len(lines):
                    if self._is_fence_close(
                        lines[end].text,
                        fence_char=fence_char,
                        minimum_length=fence_length,
                    ):
                        end += 1
                        closed = True
                        break
                    end += 1
                emit(
                    index,
                    end,
                    "CODE",
                    {
                        "markdown_block_kind": "fenced_code",
                        "markdown_fence_character": fence_char,
                        "markdown_fence_length": fence_length,
                        "markdown_info_string": info,
                        "markdown_fence_closed": closed,
                        "native_integrity_kind": "code",
                    },
                )
                if not closed:
                    diagnostics.append(
                        AdapterDiagnostic(
                            code="MARKDOWN_UNCLOSED_FENCE",
                            message=(
                                "fenced code block reaches end of source without "
                                "a matching closing fence"
                            ),
                            part="body",
                            metadata={
                                "line_start": lines[index].line_number,
                                "fence_character": fence_char,
                                "fence_length": fence_length,
                            },
                        )
                    )
                index = end
                continue

            atx = self._atx_heading(lines[index].text)
            if atx is not None:
                level, marker, label = atx
                attributes: dict[str, object] = {
                    "markdown_block_kind": "atx_heading",
                    "markdown_heading_marker": marker,
                    HEADING_LEVEL_ATTRIBUTE: level,
                }
                if label:
                    attributes[SOURCE_LABEL_ATTRIBUTE] = label
                emit(index, index + 1, "HEADING", attributes)
                index += 1
                continue

            if self._is_thematic_break(lines[index].text):
                emit(
                    index,
                    index + 1,
                    "SEPARATOR",
                    {
                        "markdown_block_kind": "thematic_break",
                        "separator_kind": "thematic_break",
                    },
                )
                index += 1
                continue

            list_item = self._list_item(lines[index].text)
            if list_item is not None:
                run_start = index
                group_id = f"markdown-list:{lines[run_start].start_char}"
                while index < len(lines):
                    current = self._list_item(lines[index].text)
                    if current is None:
                        break
                    marker, indentation, kind = current
                    item_start = index
                    index += 1
                    while (
                        index < len(lines)
                        and not self._is_blank(lines[index].text)
                        and self._list_item(lines[index].text) is None
                        and not self._starts_non_list_block(lines[index].text)
                    ):
                        index += 1
                    emit(
                        item_start,
                        index,
                        "LIST_ITEM",
                        {
                            "markdown_block_kind": "list_item",
                            "markdown_list_marker": marker,
                            "markdown_list_kind": kind,
                            "markdown_indentation": indentation,
                            "native_integrity_kind": "list",
                            INTEGRITY_GROUP_ID_ATTRIBUTE: group_id,
                            "markdown_integrity_group_provenance": "DERIVED",
                        },
                    )
                continue

            if self._blockquote_depth(lines[index].text) is not None:
                start = index
                depths: list[int] = []
                while index < len(lines):
                    depth = self._blockquote_depth(lines[index].text)
                    if depth is None:
                        break
                    depths.append(depth)
                    index += 1
                emit(
                    start,
                    index,
                    "PARAGRAPH",
                    {
                        "markdown_block_kind": "block_quote",
                        "markdown_blockquote_depths": depths,
                    },
                )
                continue

            paragraph_start = index
            emitted_heading = False
            while index < len(lines):
                if index > paragraph_start and self._starts_explicit_block(
                    lines[index].text
                ):
                    break
                if index + 1 < len(lines):
                    setext_level = self._setext_level(lines[index + 1].text)
                    if setext_level is not None:
                        label = self._setext_label(
                            lines[paragraph_start : index + 1]
                        )
                        attributes = {
                            "markdown_block_kind": "setext_heading",
                            "markdown_heading_marker": (
                                "=" if setext_level == 1 else "-"
                            ),
                            HEADING_LEVEL_ATTRIBUTE: setext_level,
                        }
                        if label:
                            attributes[SOURCE_LABEL_ATTRIBUTE] = label
                        emit(paragraph_start, index + 2, "HEADING", attributes)
                        index += 2
                        emitted_heading = True
                        break
                index += 1
                if index >= len(lines) or self._is_blank(lines[index].text):
                    break
            if not emitted_heading:
                emit(
                    paragraph_start,
                    index,
                    "PARAGRAPH",
                    {"markdown_block_kind": "paragraph"},
                )

        raw_elements = tuple(elements)
        reconstructed = "".join(item.text or "" for item in raw_elements)
        if reconstructed != text:
            raise AdapterError(
                "Markdown block parser failed its source-text preservation invariant"
            )
        return raw_elements, tuple(diagnostics)

    @staticmethod
    def _located_lines(text: str) -> tuple[_SourceLine, ...]:
        output: list[_SourceLine] = []
        cursor = 0
        for line_number, value in enumerate(source_lines(text), start=1):
            end = cursor + len(value)
            output.append(
                _SourceLine(
                    text=value,
                    start_char=cursor,
                    end_char=end,
                    line_number=line_number,
                )
            )
            cursor = end
        return tuple(output)

    @staticmethod
    def _line_content(value: str) -> str:
        return value.rstrip("\r\n")

    @classmethod
    def _is_blank(cls, value: str) -> bool:
        return not cls._line_content(value).strip()

    @classmethod
    def _atx_heading(cls, value: str) -> tuple[int, str, str] | None:
        match = _ATX_RE.fullmatch(cls._line_content(value))
        if match is None:
            return None
        marker = match.group("marker")
        label = match.group("label") or ""
        label = re.sub(r"[ \t]+#+[ \t]*$", "", label).strip()
        return len(marker), marker, label

    @classmethod
    def _setext_level(cls, value: str) -> int | None:
        match = _SETEXT_RE.fullmatch(cls._line_content(value))
        if match is None:
            return None
        return 1 if match.group("marker").startswith("=") else 2

    @classmethod
    def _setext_label(cls, lines: tuple[_SourceLine, ...]) -> str:
        return "\n".join(cls._line_content(line.text).strip() for line in lines).strip()

    @classmethod
    def _fence_open(cls, value: str) -> tuple[str, int, str] | None:
        match = _FENCE_RE.fullmatch(cls._line_content(value))
        if match is None:
            return None
        fence = match.group("fence")
        info = match.group("info").strip()
        if fence[0] == "`" and "`" in info:
            return None
        return fence[0], len(fence), info

    @classmethod
    def _is_fence_close(
        cls,
        value: str,
        *,
        fence_char: str,
        minimum_length: int,
    ) -> bool:
        content = cls._line_content(value)
        pattern = rf"^ {{0,3}}{re.escape(fence_char)}{{{minimum_length},}}[ \t]*$"
        return re.fullmatch(pattern, content) is not None

    @classmethod
    def _list_item(cls, value: str) -> tuple[str, int, str] | None:
        match = _LIST_ITEM_RE.fullmatch(cls._line_content(value))
        if match is None:
            return None
        marker = match.group("marker")
        kind = "ordered" if marker[0].isdigit() else "unordered"
        return marker, len(match.group("indent")), kind

    @classmethod
    def _blockquote_depth(cls, value: str) -> int | None:
        match = _BLOCKQUOTE_RE.match(cls._line_content(value))
        return None if match is None else len(match.group("markers"))

    @classmethod
    def _is_thematic_break(cls, value: str) -> bool:
        content = cls._line_content(value)
        indentation = len(content) - len(content.lstrip(" "))
        if indentation > 3:
            return False
        compact = re.sub(r"[ \t]", "", content[indentation:])
        return (
            len(compact) >= 3
            and compact[0] in {"*", "-", "_"}
            and set(compact) == {compact[0]}
        )

    @classmethod
    def _starts_explicit_block(cls, value: str) -> bool:
        return bool(
            cls._is_blank(value)
            or cls._fence_open(value) is not None
            or cls._atx_heading(value) is not None
            or cls._is_thematic_break(value)
            or cls._list_item(value) is not None
            or cls._blockquote_depth(value) is not None
        )

    @classmethod
    def _starts_non_list_block(cls, value: str) -> bool:
        return bool(
            cls._fence_open(value) is not None
            or cls._atx_heading(value) is not None
            or cls._is_thematic_break(value)
            or cls._blockquote_depth(value) is not None
        )
