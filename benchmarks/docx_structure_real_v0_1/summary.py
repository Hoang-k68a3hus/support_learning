from __future__ import annotations

import argparse
import json

from .discover import SOURCES, discover_source


def _source(source_id: str) -> dict[str, str]:
    for item in SOURCES:
        if item["id"] == source_id:
            return item
    raise SystemExit(f"unknown source id: {source_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    item = discover_source(_source(args.source))
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
