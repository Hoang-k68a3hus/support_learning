from __future__ import annotations

import argparse
import hashlib
import json

from .discover import SOURCES, _download, _package_inventory, discover_source


def _source(source_id: str) -> dict[str, str]:
    for item in SOURCES:
        if item["id"] == source_id:
            return item
    raise SystemExit(f"unknown source id: {source_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    source = _source(args.source)
    try:
        item = discover_source(source)
    except Exception as exc:
        payload = _download(source["url"])
        item = {
            **source,
            "bytes": len(payload),
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "package": _package_inventory(payload),
            "adapter": {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
            "pipeline": {"status": "not_run"},
        }
    compact = {
        key: item.get(key)
        for key in (
            "id", "file_name", "document_class", "url", "source_page", "license",
            "bytes", "sha256", "package", "adapter", "pipeline", "adapter_diagnostics",
        )
    }
    print("REAL_DOCX_SUMMARY_JSON=" + json.dumps(compact, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
