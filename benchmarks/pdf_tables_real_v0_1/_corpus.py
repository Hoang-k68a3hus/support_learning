from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parent
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_RAW_PREFIX = "https://raw.githubusercontent.com/"
_MAX_SOURCE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RealPdfSource:
    id: str
    file_name: str
    url: str
    upstream_repository: str
    upstream_commit: str
    upstream_path: str
    git_blob_sha: str
    bytes: int
    source_class: str
    rights_note: str

    @classmethod
    def from_json(cls, value: dict[str, object]) -> "RealPdfSource":
        source = cls(
            id=str(value["id"]),
            file_name=str(value["file_name"]),
            url=str(value["url"]),
            upstream_repository=str(value["upstream_repository"]),
            upstream_commit=str(value["upstream_commit"]),
            upstream_path=str(value["upstream_path"]),
            git_blob_sha=str(value["git_blob_sha"]),
            bytes=int(value["bytes"]),
            source_class=str(value["class"]),
            rights_note=str(value["rights_note"]),
        )
        source.validate()
        return source

    def validate(self) -> None:
        if not self.id.strip() or not self.file_name.endswith(".pdf"):
            raise ValueError(f"invalid PDF source identity: {self.id!r}")
        if not _HEX40.fullmatch(self.upstream_commit):
            raise ValueError(f"invalid upstream commit for {self.id}")
        if not _HEX40.fullmatch(self.git_blob_sha):
            raise ValueError(f"invalid git blob SHA for {self.id}")
        if self.bytes <= 0 or self.bytes > _MAX_SOURCE_BYTES:
            raise ValueError(f"invalid byte size for {self.id}: {self.bytes}")
        expected_url = (
            f"{_RAW_PREFIX}{self.upstream_repository}/{self.upstream_commit}/"
            f"{self.upstream_path}"
        )
        if self.url != expected_url:
            raise ValueError(f"unpinned or inconsistent source URL for {self.id}")
        if not self.rights_note.strip():
            raise ValueError(f"missing rights note for {self.id}")


def load_sources() -> tuple[RealPdfSource, ...]:
    payload = json.loads((_ROOT / "sources.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported real-PDF source manifest schema")
    sources = tuple(RealPdfSource.from_json(item) for item in payload["sources"])
    ids = [item.id for item in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate real-PDF source id")
    return sources


def git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return sha1(header + payload, usedforsecurity=False).hexdigest()


def download_source(source: RealPdfSource) -> bytes:
    request = Request(source.url, headers={"User-Agent": "support-learning-real-pdf-benchmark/1"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - immutable HTTPS fixture URL
        payload = response.read(_MAX_SOURCE_BYTES + 1)
    if len(payload) > _MAX_SOURCE_BYTES:
        raise ValueError(f"source exceeds benchmark byte limit: {source.id}")
    if len(payload) != source.bytes:
        raise ValueError(
            f"source byte-size drift for {source.id}: expected {source.bytes}, got {len(payload)}"
        )
    if git_blob_sha(payload) != source.git_blob_sha:
        raise ValueError(f"source git-blob drift for {source.id}")
    if not payload.startswith(b"%PDF-"):
        raise ValueError(f"downloaded source is not a PDF: {source.id}")
    return payload


def sha256_hex(payload: bytes) -> str:
    return sha256(payload).hexdigest()
