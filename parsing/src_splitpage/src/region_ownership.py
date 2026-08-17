#!/usr/bin/env python3
"""Region-level article/advertisement ownership postprocessor.

Produces per-page JSON ownership assignments and a visualization overlay.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    from .plan_article_splits_rule_based import AD_CONTACT_PATTERNS, AD_STRONG_PATTERNS
except Exception:
    # allow running as a script where package-relative import may fail
    from plan_article_splits_rule_based import AD_CONTACT_PATTERNS, AD_STRONG_PATTERNS


@dataclass
class Element:
    element_id: str
    order: int
    type: str
    text: str
    bbox: List[int] | None
    bbox_norm: List[float] | None
    markdown_level: int | None = None


def load_elements_for_doc(parse_root: Path, doc_id: str) -> Dict[str, List[Element]]:
    doc_dir = Path(parse_root) / doc_id
    pages: Dict[str, List[Element]] = {}
    for page_dir in sorted([p for p in doc_dir.glob("page_*") if p.is_dir()]):
        el_path = page_dir / "elements.json"
        if not el_path.exists():
            continue
        data = json.loads(el_path.read_text(encoding="utf-8"))
        els: List[Element] = []
        for e in data.get("elements", []):
            els.append(
                Element(
                    element_id=e.get("element_id"),
                    order=int(e.get("order") or 0),
                    type=str(e.get("type") or ""),
                    text=str(e.get("text") or ""),
                    bbox=e.get("bbox"),
                    bbox_norm=e.get("bbox_norm"),
                    markdown_level=e.get("markdown_level"),
                )
            )
        pages[page_dir.name] = els
    return pages


def bbox_center(bbox: List[int]) -> Tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def same_column(b1: List[int], b2: List[int], page_width: int | None) -> bool:
    if b1 is None or b2 is None:
        return False
    cx1, _ = bbox_center(b1)
    cx2, _ = bbox_center(b2)
    if page_width and page_width > 0:
        return abs(cx1 - cx2) / page_width < 0.18
    return abs(cx1 - cx2) < 100


def vertical_center(b: List[int]) -> float:
    _, y0, _, y1 = b
    return (y0 + y1) / 2.0


def nearest_title_seed(el: Element, title_seeds: List[Element], page_width: int | None) -> Element | None:
    if not title_seeds:
        return None
    best = None
    best_dy = None
    cx_el, cy_el = bbox_center(el.bbox)
    for s in title_seeds:
        if not s.bbox:
            continue
        # require roughly same column
        if not same_column(el.bbox, s.bbox, page_width):
            continue
        _, cy_s = bbox_center(s.bbox)
        dy = abs(cy_el - cy_s)
        if best is None or dy < best_dy:
            best = s
            best_dy = dy
    return best


def has_ad_cue(text: str) -> bool:
    t = text.lower()
    for pat in AD_STRONG_PATTERNS + AD_CONTACT_PATTERNS:
        try:
            if re.search(pat, t, re.IGNORECASE):
                return True
        except re.error:
            if pat in t:
                return True
    return False


def ad_signal_count(text: str) -> int:
    """Return an integer count of ad signals in the text.

    Strong ad patterns count as 2 (sufficient), contact/weak patterns count individually.
    """
    t = (text or "").lower()
    # if any strong pattern matches treat as 2 signals (sufficient)
    for pat in AD_STRONG_PATTERNS:
        try:
            if re.search(pat, t, re.IGNORECASE):
                return 2
        except re.error:
            if pat in t:
                return 2
    # count weak/contact matches
    cnt = 0
    for pat in AD_CONTACT_PATTERNS:
        try:
            if re.search(pat, t, re.IGNORECASE):
                cnt += 1
        except re.error:
            if pat in t:
                cnt += 1
    return cnt


def is_title_seed(el: Element) -> bool:
    # require explicit title/sub_title type or markdown-level 1
    if el.type in {"title", "sub_title"}:
        return True
    if el.markdown_level is not None and int(el.markdown_level) == 1:
        return True
    # be conservative: short all-caps headings may be noisy -> not a title by itself
    return False


def is_body_seed(el: Element) -> bool:
    txt = el.text or ""
    if len(txt) >= 200 and el.bbox is not None:
        return True
    return False


def is_ad_seed(el: Element) -> bool:
    # require stronger signals for ad: textual ad cues or explicit ad-like markers
    # require at least two independent signals (or one strong) to consider an element an ad seed
    signals = ad_signal_count(el.text)
    if signals >= 2:
        return True
    # image-only should be ambiguous unless other ad signals present
    return False


def load_article_plan(parse_root: Path, doc_id: str) -> dict | None:
    # Look for common plan locations
    candidates = [
        Path("output/article_split_plans_parse_only") / doc_id / "article_split_plan.json",
        Path("output/article_split_plans") / doc_id / "article_split_plan.json",
        Path(parse_root) / doc_id / "article_split_plan.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def assign_ownership_for_doc(parse_root: Path, doc_id: str, output_dir: Path) -> List[dict[str, Any]]:
    pages = load_elements_for_doc(parse_root, doc_id)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    article_counter = 0
    ad_counter = 0
    current_article: str | None = None

    # load page-level article split plan if available
    plan = load_article_plan(parse_root, doc_id)
    page_to_article_idx: Dict[str, int] = {}
    page_roles: Dict[str, str] = {}
    exported_article_segments: List[dict] = []
    if plan:
        exported_article_segments = [s for s in plan.get("subdocuments", []) if s.get("export")]
        # build mapping by logical_index
        pages_info = {p["page_name"]: p for p in plan.get("pages", [])}
        for p_name, p_info in pages_info.items():
            page_roles[p_name] = p_info.get("page_role") or "content"
            logical_index = int(p_info.get("logical_index", -1))
            # find which exported segment contains this logical index
            for idx, seg in enumerate(exported_article_segments, start=1):
                if logical_index >= int(seg["page_start"]) and logical_index <= int(seg["page_end"]):
                    page_to_article_idx[p_name] = idx
                    break

    results: List[dict[str, Any]] = []

    sorted_pages = sorted(pages.items(), key=lambda kv: int(kv[0].rsplit("_", 1)[-1]))

    for page_name, elements in sorted_pages:
        # try to obtain page image and dimensions
        page_dir = Path(parse_root) / doc_id / page_name
        page_image = None
        page_width = None
        page_height = None
        for ext in ["png", "jpg", "jpeg"]:
            p = page_dir / f"page.{ext}"
            if p.exists():
                page_image = p
                break
        # fallback to any page image file
        if page_image is None:
            for p in page_dir.glob("page.*"):
                if p.suffix.lower().lstrip('.') in {"png","jpg","jpeg"}:
                    page_image = p
                    break
        if page_image and page_image.exists():
            try:
                with Image.open(page_image) as im:
                    page_width, page_height = im.size
            except Exception:
                page_image = None

        page_result = {"page": int(page_name.rsplit("_", 1)[-1]), "regions": []}

        # detect seeds
        seeds: Dict[str, List[Element]] = {"article": [], "ad": []}
        for el in elements:
            if el.bbox is None:
                continue
            if is_title_seed(el) or is_body_seed(el):
                seeds["article"].append(el)
            elif is_ad_seed(el):
                seeds["ad"].append(el)
        # determine page-level article id if plan provides it (strong prior)
        page_article_ids: Dict[str, str] = {}
        page_article_idx = page_to_article_idx.get(page_name)
        if page_article_idx is not None:
            # assign current article id based on plan segment index
            current_article = f"article_{page_article_idx:02d}"
            # map any title seeds to this article id
            title_seeds = [e for e in elements if is_title_seed(e) and e.bbox]
            for seed in title_seeds:
                page_article_ids[seed.element_id] = current_article
        else:
            # fallback: each title seed starts a new sequential article id
            title_seeds = [e for e in elements if is_title_seed(e) and e.bbox]
            title_seeds = sorted(title_seeds, key=lambda x: x.order)
            for seed in title_seeds:
                article_counter += 1
                aid = f"article_{article_counter:02d}"
                page_article_ids[seed.element_id] = aid
                current_article = aid

        # assign elements
        last_owner: str | None = current_article
        for idx, el in enumerate(elements):
            owner = "ambiguous"
            confidence = 0.0
            reasons: List[str] = []
            if el.bbox is None:
                owner = "template"
                confidence = 0.5
                reasons.append("no_bbox")
            else:
                # seed exact matches
                if el.element_id in page_article_ids:
                    owner = page_article_ids[el.element_id]
                    confidence = 0.95
                    reasons.append("title_seed")
                    last_owner = owner
                elif is_ad_seed(el):
                    # only strong ad assignment when page-level role or multiple signals
                    page_role = page_roles.get(page_name)
                    if page_role == "advertisement" or page_role == "mixed_content_ad":
                        ad_counter += 1
                        owner = f"advertisement_{ad_counter:02d}"
                        confidence = 0.95
                        reasons.append("ad_seed_page_role")
                        last_owner = None
                    else:
                        # prefer ambiguous unless multiple ad seeds nearby; weak signal
                        owner = "ambiguous"
                        confidence = 0.4
                        reasons.append("ad_cue_weak")
                # propagate from last article seed if element is nearby/column aligned
                elif last_owner and el.bbox is not None:
                    # check proximity to previous element assigned to same article
                    prev = elements[idx - 1] if idx > 0 else None
                    if prev and prev.bbox and last_owner and same_column(prev.bbox, el.bbox, page_width):
                        # if there is a nearby title seed in the same column, prefer it when
                        # the element is vertically closer to the title seed than to the previous
                        # propagated element. This weakens blind same-column propagation.
                        seed = nearest_title_seed(el, title_seeds, page_width)
                        if seed:
                            aid = page_article_ids.get(seed.element_id) or current_article
                            if aid and aid != last_owner:
                                _, cy_el = bbox_center(el.bbox)
                                _, cy_seed = bbox_center(seed.bbox)
                                _, cy_prev = bbox_center(prev.bbox)
                                dy_seed = abs(cy_el - cy_seed)
                                dy_prev = abs(cy_el - cy_prev)
                                # prefer the seed if it's noticeably closer (allow small slack)
                                if dy_seed + 20 <= dy_prev:
                                    owner = aid
                                    confidence = 0.9
                                    reasons.append("title_proximity_override")
                                    last_owner = owner
                                else:
                                    owner = last_owner
                                    confidence = 0.85
                                    reasons.append("same_column")
                            else:
                                owner = last_owner
                                confidence = 0.85
                                reasons.append("same_column")
                        else:
                            owner = last_owner
                            confidence = 0.85
                            reasons.append("same_column")
                    else:
                        # body continuity heuristics
                        if is_body_seed(el):
                            owner = last_owner
                            confidence = 0.8
                            reasons.append("body_continuity")
                # neighbor to article seed in same column
                if owner == "ambiguous" and seeds["article"]:
                    for seed in seeds["article"]:
                        if seed.bbox and el.bbox and same_column(seed.bbox, el.bbox, page_width):
                            # map to the article id if we created one for seed, else current_article
                            aid = page_article_ids.get(seed.element_id) or current_article
                            if aid:
                                owner = aid
                                confidence = 0.75
                                reasons.append("near_article_seed")
                                break

            if owner == "ambiguous":
                confidence = 0.4
                reasons.append("insufficient_evidence")

            bbox = el.bbox or []
            page_result["regions"].append(
                {
                    "bbox": bbox,
                    "element_id": el.element_id,
                    "owner": owner,
                    "confidence": round(float(confidence), 2),
                    "reason": reasons,
                }
            )

        # write json and visualization
        out_json = output_dir / f"{doc_id}_{page_name}_ownership.json"
        out_img = output_dir / f"{doc_id}_{page_name}_ownership.png"
        out_json.write_text(json.dumps(page_result, ensure_ascii=False, indent=2), encoding="utf-8")

        # visualization
        try:
            if page_image and page_image.exists():
                with Image.open(page_image) as im:
                    draw = ImageDraw.Draw(im)
                    palette: Dict[str, Tuple[int, int, int]] = {}
                    colors = [(46, 204, 113), (52, 152, 219), (155, 89, 182), (241, 196, 15), (231, 76, 60)]
                    color_idx = 0
                    for r in page_result["regions"]:
                        owner = r["owner"]
                        if owner not in palette:
                            palette[owner] = colors[color_idx % len(colors)]
                            color_idx += 1
                        c = palette[owner]
                        if r["bbox"] and len(r["bbox"]) == 4:
                            x0, y0, x1, y1 = r["bbox"]
                            draw.rectangle([x0, y0, x1, y1], outline=c, width=3)
                            label = f"{r['owner']} ({r['confidence']})"
                            draw.text((x0 + 3, y0 + 3), label, fill=c)
                    im.save(out_img)
        except Exception:
            pass

        results.append(page_result)

    return results


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Assign region ownership for magazine pages")
    parser.add_argument("parse_root", help="root of parsed pages (output/deepseekocr2_split_render)")
    parser.add_argument("doc_id", help="document id directory under parse_root")
    parser.add_argument("--output-dir", default="output/region_ownership")
    args = parser.parse_args()

    assign_ownership_for_doc(Path(args.parse_root), args.doc_id, Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
