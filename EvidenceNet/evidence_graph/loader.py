from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def page_number(value: str) -> int:
    match = re.search(r"(\d+)(?!.*\d)", value)
    return int(match.group(1)) if match else 10**12


def load_aligned_document(aligned_root: str | Path, doc_id: str) -> list[dict[str, Any]]:
    directory = Path(aligned_root) / doc_id
    if not directory.is_dir():
        raise FileNotFoundError(f"Aligned document directory not found: {directory}")
    pages = []
    for path in directory.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("doc_id") not in (None, doc_id):
            raise ValueError(f"{path} has doc_id={data.get('doc_id')!r}, expected {doc_id!r}")
        data.setdefault("doc_id", doc_id)
        data["_source_file"] = str(path.resolve())
        pages.append(data)
    if not pages:
        raise FileNotFoundError(f"No page JSON files found in {directory}")
    return sorted(pages, key=lambda p: (page_number(str(p.get("page", ""))), p.get("page", "")))

