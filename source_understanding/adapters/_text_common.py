from __future__ import annotations

import re
from enum import StrEnum

from .base import AdapterError


class TextEncoding(StrEnum):
    """Deterministic text decoders; AUTO detects only explicit BOMs."""

    AUTO = "AUTO"
    UTF8 = "UTF-8"
    UTF16_LE = "UTF-16-LE"
    UTF16_BE = "UTF-16-BE"


def decode_text_payload(
    payload: bytes,
    encoding: StrEnum,
    *,
    adapter_label: str,
) -> tuple[str, str, str | None]:
    try:
        resolved_encoding = TextEncoding(encoding.value)
    except ValueError as exc:
        raise AdapterError(
            f"{adapter_label} has unsupported text encoding {encoding.value!r}"
        ) from exc
    bom: str | None = None
    decoder: str
    view = payload

    if resolved_encoding == TextEncoding.AUTO:
        if payload.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            raise AdapterError(
                f"{adapter_label} AUTO encoding does not support UTF-32; "
                "configure a dedicated adapter or transcode without losing "
                "source identity"
            )
        if payload.startswith(b"\xef\xbb\xbf"):
            decoder, bom, view = "utf-8", "UTF-8", payload[3:]
        elif payload.startswith(b"\xff\xfe"):
            decoder, bom, view = "utf-16-le", "UTF-16-LE", payload[2:]
        elif payload.startswith(b"\xfe\xff"):
            decoder, bom, view = "utf-16-be", "UTF-16-BE", payload[2:]
        else:
            decoder = "utf-8"
    else:
        decoder = {
            TextEncoding.UTF8: "utf-8",
            TextEncoding.UTF16_LE: "utf-16-le",
            TextEncoding.UTF16_BE: "utf-16-be",
        }[resolved_encoding]
        matching_bom = {
            TextEncoding.UTF8: (b"\xef\xbb\xbf", "UTF-8"),
            TextEncoding.UTF16_LE: (b"\xff\xfe", "UTF-16-LE"),
            TextEncoding.UTF16_BE: (b"\xfe\xff", "UTF-16-BE"),
        }[resolved_encoding]
        opposite_bom = {
            TextEncoding.UTF16_LE: b"\xfe\xff",
            TextEncoding.UTF16_BE: b"\xff\xfe",
        }.get(resolved_encoding)
        if opposite_bom is not None and payload.startswith(opposite_bom):
            raise AdapterError(
                f"{adapter_label} BOM conflicts with configured encoding "
                f"{resolved_encoding.value}"
            )
        if payload.startswith(matching_bom[0]):
            bom = matching_bom[1]
            view = payload[len(matching_bom[0]) :]

    try:
        return view.decode(decoder, errors="strict"), decoder.upper(), bom
    except UnicodeDecodeError as exc:
        raise AdapterError(
            f"{adapter_label} decode failed with {decoder} at byte range "
            f"[{exc.start}, {exc.end})"
        ) from exc


def source_lines(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(
        match.group(0)
        for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
        if match.group(0)
    )
