#!/usr/bin/env python3
"""Select difficult pages and run region ownership postprocessor for validation.

Produces per-page JSON/PNG and a CSV summary under output/region_ownership_validation/
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from region_ownership import (
    load_elements_for_doc,
    has_ad_cue,
    is_body_seed,
    is_title_seed,
    assign_ownership_for_doc,
)


def score_page(elements: List[dict]) -> float:
    # elements are Element dataclass instances
    el_list = elements
    ad_cues = sum(1 for e in el_list if has_ad_cue(e.text))
    body = sum(1 for e in el_list if is_body_seed(e))
    titles = sum(1 for e in el_list if is_title_seed(e))
    images = sum(1 for e in el_list if e.type == "image")
    # multi-column proxy: count unique center-x quantiles among body blocks
    centers = [((e.bbox[0] + e.bbox[2]) / 2) for e in el_list if e.bbox]
    unique_centers = len(set(int(c // 200) for c in centers))
    score = 0.0
    if ad_cues and body:
        score += 5.0
    score += min(3, titles) * 1.2
    score += min(2, images) * 0.8
    score += (unique_centers - 1) * 1.5
    score += min(3, ad_cues) * 1.0
    return score


def main(parse_root: Path, out_root: Path, select_n: int = 15) -> int:
    parse_root = Path(parse_root)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    docs = sorted([p for p in parse_root.iterdir() if p.is_dir()])
    candidates: List[tuple[float, str, str]] = []  # (score, doc_id, page_name)

    for doc in docs:
        pages = load_elements_for_doc(parse_root, doc.name)
        for page_name, elements in pages.items():
            s = score_page(elements)
            if s > 0:
                candidates.append((s, doc.name, page_name))

    candidates.sort(reverse=True)
    selected = candidates[:select_n]

    # run postprocessor per doc for docs that appear in selected set
    docs_to_run = sorted({doc for _, doc, _ in selected})
    for doc_id in docs_to_run:
        assign_ownership_for_doc(parse_root, doc_id, out_root)

    # collect per-element rows into CSV
    rows: List[Dict[str, Any]] = []
    for _, doc_id, page_name in selected:
        json_path = out_root / f"{doc_id}_{page_name}_ownership.json"
        img_path = out_root / f"{doc_id}_{page_name}_ownership.png"
        if not json_path.exists():
            continue
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for r in data.get("regions", []):
            rows.append(
                {
                    "document_id": doc_id,
                    "page": data.get("page"),
                    "element_id": r.get("element_id"),
                    "owner": r.get("owner"),
                    "confidence": r.get("confidence"),
                    "reason": ";".join(r.get("reason") or []),
                    "bbox": json.dumps(r.get("bbox") or []),
                    "text_preview": "",
                }
            )

    csv_path = out_root / "region_ownership_validation_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["document_id", "page", "element_id", "owner", "confidence", "reason", "bbox", "text_preview"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # also write selected pages manifest
    manifest_path = out_root / "selected_pages.json"
    manifest_path.write_text(json.dumps([{"score": s, "doc": d, "page": p} for s, d, p in selected], indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} region rows for {len(selected)} pages to {out_root}")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--parse-root", default="output/deepseekocr2_split_render")
    parser.add_argument("--out-root", default="parsing/output/region_ownership_validation")
    parser.add_argument("--select", type=int, default=15)
    args = parser.parse_args()
    raise SystemExit(main(Path(args.parse_root), Path(args.out_root), args.select))
