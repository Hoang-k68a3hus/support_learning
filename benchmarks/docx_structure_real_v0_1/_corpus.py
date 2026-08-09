from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
FIXED_EVALUATION_TIME = datetime(2026, 8, 9, tzinfo=timezone.utc)
USER_AGENT = (
    "support-learning-structure-benchmark/0.1 "
    "(+https://github.com/Hoang-k68a3hus/support_learning)"
)


def _load_sources() -> tuple[dict[str, object], ...]:
    payload = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("sources.json must contain a documents list")
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in documents:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuntimeError("sources.json contains an invalid document record")
        source_id = item["id"]
        if source_id in seen:
            raise RuntimeError(f"sources.json contains duplicate id {source_id!r}")
        seen.add(source_id)
        output.append(dict(item))
    return tuple(output)


SOURCES = _load_sources()


def _download(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document,*/*;q=0.8"
            ),
        },
    )
    with urlopen(request, timeout=45) as response:
        payload = response.read()
    if not payload.startswith(b"PK"):
        raise RuntimeError(
            f"downloaded payload from {url!r} is not an OPC ZIP package"
        )
    return payload
