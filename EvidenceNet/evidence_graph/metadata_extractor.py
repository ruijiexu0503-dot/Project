from __future__ import annotations

import re
from typing import Any

from .block_classifier import block_text


def source_record(block: dict[str, Any]) -> dict[str, Any]:
    return {"page": block.get("_page"), "block_id": block.get("block_id"),
            "bbox": block.get("bbox"), "original_text": block_text(block)}


def extract_document_metadata(doc_id: str, classified, source_files: list[str]):
    result = {"doc_id": doc_id, "title": None, "authors": [], "collaborations": [],
              "received_date": None, "published_date": None, "doi": None,
              "source_files": source_files, "metadata_source_blocks": []}
    for block, role in classified:
        text = block_text(block).strip()
        if role not in {"document_title", "author_metadata", "publication_metadata", "identifier_metadata"}:
            continue
        result["metadata_source_blocks"].append(source_record(block))
        clean = re.sub(r"^#{1,6}\s*", "", text).strip()
        if role == "document_title" and result["title"] is None: result["title"] = clean
        elif role == "identifier_metadata":
            match = re.search(r"10\.\d{4,9}/\S+", text, re.I)
            if match: result["doi"] = match.group(0).rstrip(".,;)")
        elif role == "publication_metadata":
            for kind in ("received", "published"):
                match = re.search(rf"{kind}\s+(\d{{1,2}}\s+[A-Za-z]+\s+\d{{4}})", text, re.I)
                if match: result[f"{kind}_date"] = match.group(1)
        elif role == "author_metadata":
            if re.search(r"\b(?:collaboration|consortium)\b", clean, re.I):
                result["collaborations"].append(clean.strip("() "))
            else: result["authors"].append(clean)
    return result

