from __future__ import annotations

from collections import Counter
from typing import Any

from .loader import page_number


def order_blocks(pages: list[dict[str, Any]], conflict_threshold: int = 3):
    ordered, issues = [], []
    for page in pages:
        page_id = str(page.get("page", ""))
        blocks = page.get("aligned_blocks", [])
        counts = Counter(b.get("final_order") for b in blocks if b.get("final_order") is not None)
        for value, count in counts.items():
            if count > 1:
                issues.append({"type": "duplicated_final_order", "page": page_id,
                               "final_order": value, "count": count})
        for index, block in enumerate(blocks):
            b = dict(block)
            b["_page"] = page_id
            b["_page_width"] = page.get("page_width")
            b["_page_height"] = page.get("page_height")
            b["_source_file"] = page.get("_source_file")
            b["_array_index"] = index
            final = b.get("final_order")
            if not isinstance(final, (int, float)):
                issues.append({"type": "missing_or_invalid_final_order", "page": page_id,
                               "block_id": b.get("block_id")})
            deep = b.get("deepseek_order")
            if isinstance(final, (int, float)) and isinstance(deep, (int, float)) and abs(final-deep) > conflict_threshold:
                issues.append({"type": "deepseek_order_conflict", "page": page_id,
                               "block_id": b.get("block_id"), "final_order": final, "deepseek_order": deep})
            geom = b.get("geometry_order")
            if isinstance(final, (int, float)) and isinstance(geom, (int, float)) and final != geom:
                issues.append({"type": "geometry_order_conflict", "page": page_id,
                               "block_id": b.get("block_id"), "final_order": final, "geometry_order": geom})
            ordered.append(b)
    def key(b):
        final = b.get("final_order")
        fallback = b.get("deepseek_order")
        order = final if isinstance(final, (int, float)) else fallback if isinstance(fallback, (int, float)) else 10**12
        return (page_number(b["_page"]), order, str(b.get("block_id", "")), b["_array_index"])
    return sorted(ordered, key=key), issues

