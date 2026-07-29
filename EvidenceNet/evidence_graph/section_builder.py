from __future__ import annotations

import re
from typing import Any

from .block_classifier import block_text


def build_sections(doc_id: str, classified):
    sections, active, assignments = [], [], {}
    for block, role in classified:
        if role == "section_heading":
            raw = block_text(block).strip()
            match = re.match(r"^(#{1,6})\s+", raw)
            level = len(match.group(1)) - 1 if match else 1
            level = max(1, level)
            title = re.sub(r"^#{1,6}\s*", "", raw).strip()
            while active and active[-1][0] >= level: active.pop()
            section_id = f"{doc_id}_SEC_{len(sections)+1:04d}"
            active.append((level, section_id, title))
            sections.append({"node_id": section_id, "section_id": section_id, "node_type": "section",
                             "doc_id": doc_id, "title": title, "level": level,
                             "parent_section_id": active[-2][1] if len(active)>1 else None,
                             "section_path": [x[2] for x in active], "source_block_id": block.get("block_id"),
                             "page": block.get("_page"), "bbox": block.get("bbox")})
        assignments[id(block)] = (active[-1][1] if active else None, [x[2] for x in active])
    return sections, assignments

