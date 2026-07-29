from __future__ import annotations

import re
from typing import Any

ROLES = {"evidence_content", "document_title", "author_metadata", "publication_metadata",
         "identifier_metadata", "section_heading", "header", "footer", "footnote",
         "ocr_noise", "unresolved"}


def block_text(block: dict[str, Any]) -> str:
    value = block.get("markdown")
    return str(value if value is not None else block.get("text") or "")


def classify_block_role(block: dict[str, Any]) -> str:
    raw, text = block_text(block), block_text(block).strip()
    label = str(block.get("matched_region_label") or "").lower()
    region_role = str(block.get("matched_region_role") or "").lower()
    block_type = str(block.get("block_type") or "").lower()
    flags = " ".join(map(str, block.get("flags") or [])).lower()
    if label in {"header", "header_text"} or region_role == "header": return "header"
    if label == "footer" or region_role == "footer": return "footer"
    if label == "footnote" or region_role == "footnote": return "footnote"
    if label in {"doc_title", "document_title"}: return "document_title"
    if re.match(r"^#(?!#)\s+", text): return "document_title"
    if label in {"paragraph_title", "section_heading"} or re.match(r"^#{2,6}\s+", text): return "section_heading"
    if "heading" in block_type and text: return "section_heading"
    if re.match(r"^(?:doi\s*:|https?://(?:dx\.)?doi\.org/)", text, re.I): return "identifier_metadata"
    if re.search(r"\b(?:received|accepted|published)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", text, re.I): return "publication_metadata"
    if (len(text) <= 250 and not re.match(r"^\s*\[\d+\]", text)
            and re.search(r"\b(?:collaboration|consortium)\b", text, re.I)):
        return "author_metadata"
    if re.match(r"^[A-Z](?:\.\s*)?[A-Z]?\.?(?:\s+[A-Z][\w'’-]+)+(?:\s+et al\.)?\s*(?:\\\(|\(|$)", text): return "author_metadata"
    visible = re.sub(r"[\W_]+", "", re.sub(r"\\[()\[\]]", "", text), flags=re.UNICODE)
    if not text or len(visible) <= 1 or (len(visible) <= 3 and not any(c.isalpha() for c in visible)):
        return "ocr_noise"
    if any(token in flags for token in ("ocr_noise", "garbage", "meaningless")): return "ocr_noise"
    if block_type in {"text", "paragraph", "caption", "list", "formula", "reference"} or text:
        return "evidence_content"
    return "unresolved"
