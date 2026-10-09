#!/usr/bin/env python3
"""Resolve visual-asset geometry without leaving operational UNRESOLVED rows.

This is a shadow-only experiment.  It combines existing PDF renderer masks and
existing Dolphin layout output; it does not rerun parsing or modify production.

Resolution order:
  1. NATIVE_SHAPE   - a renderer-derived mask passed placement validation.
  2. VISUAL_SHAPE   - invalid PDF fragments are absorbed by one Dolphin figure
                      region and a page-pixel foreground mask is derived there.
  3. BBOX_FALLBACK  - a conservative rectangular terminal representation.

Every source asset is represented by exactly one resolved record.  Several PDF
fragments may intentionally resolve to one visual record, while their IDs and
native bboxes remain in provenance.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "parsing/audits/automated_asset_geometry_fallback_v1"

CASES = [
    {
        "document": "CLADmag_2025_H2",
        "page": 9,
        "audit": ROOT / "parsing/audits/gated_background_assets_shadow_v1/CLADmag_2025_H2_shape_sample_v1",
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/cladmag_2025_h2/pages/page_0009",
    },
    {
        "document": "DLRmagazine_176_EN",
        "page": 9,
        "audit": ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2",
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0009",
    },
    {
        "document": "DLRmagazine_176_EN",
        "page": 12,
        "audit": ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2",
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0012",
    },
]

CONFIG = {
    "native_mask_threshold": 24,
    "fragment_to_figure_min_coverage": 0.50,
    "fragment_cluster_gap_fraction": 0.02,
    "visual_mask_min_component_area_fraction": 0.00002,
    "visual_foreground_min_distance": 14.0,
    "visual_foreground_mad_multiplier": 3.0,
}


def load_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise TypeError(f"Expected list in {path}")
        return value
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def union_box(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def center_inside(a: list[float], b: list[float]) -> bool:
    x, y = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def scale_box(box: list[float], source_size: list[int], target_size: tuple[int, int]) -> list[float]:
    sx, sy = target_size[0] / source_size[0], target_size[1] / source_size[1]
    return [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]


def clip_box(box: list[float], size: tuple[int, int]) -> list[int]:
    return [max(0, min(size[0], int(math.floor(box[0])))),
            max(0, min(size[1], int(math.floor(box[1])))),
            max(0, min(size[0], int(math.ceil(box[2])))),
            max(0, min(size[1], int(math.ceil(box[3]))))]


def connected_components(binary: np.ndarray, min_area: int) -> np.ndarray:
    """Small dependency-free 8-connected component filter."""
    h, w = binary.shape
    seen = np.zeros((h, w), dtype=bool)
    kept = np.zeros((h, w), dtype=np.uint8)
    for y, x in zip(*np.nonzero(binary)):
        if seen[y, x]:
            continue
        queue = deque([(int(y), int(x))])
        seen[y, x] = True
        component = []
        while queue:
            cy, cx = queue.popleft()
            component.append((cy, cx))
            for ny in range(max(0, cy - 1), min(h, cy + 2)):
                for nx in range(max(0, cx - 1), min(w, cx + 2)):
                    if binary[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        if len(component) >= min_area:
            yy, xx = zip(*component)
            kept[np.asarray(yy), np.asarray(xx)] = 255
    return kept


def visual_foreground_mask(original: Image.Image, box: list[float]) -> Image.Image:
    """Estimate disconnected foreground shapes from the local border colour."""
    clipped = clip_box(box, original.size)
    crop = np.asarray(original.crop(tuple(clipped)).convert("RGB"), dtype=np.float32)
    if crop.size == 0:
        return Image.new("L", original.size)
    border = np.concatenate((crop[0], crop[-1], crop[:, 0], crop[:, -1]), axis=0)
    background = np.median(border, axis=0)
    border_distance = np.linalg.norm(border - background, axis=1)
    median = float(np.median(border_distance))
    mad = float(np.median(np.abs(border_distance - median)))
    threshold = max(CONFIG["visual_foreground_min_distance"],
                    median + CONFIG["visual_foreground_mad_multiplier"] * max(1.0, mad))
    distance = np.linalg.norm(crop - background, axis=2)
    binary = distance >= threshold
    min_area = max(4, int(original.width * original.height * CONFIG["visual_mask_min_component_area_fraction"]))
    filtered = connected_components(binary, min_area)
    mask = Image.new("L", original.size)
    mask.paste(Image.fromarray(filtered), (clipped[0], clipped[1]))
    return mask.filter(ImageFilter.MaxFilter(3))


def native_bbox(asset: dict) -> list[float]:
    return union_box([m["rendered_bbox_pixels"] for m in asset["render_layer_members"]])


def native_is_trustworthy(asset: dict, audit: Path) -> bool:
    mask = asset.get("layer_mask")
    return bool(mask and (audit / mask).exists() and
                asset.get("mask_placement_consistent") is not False and
                (asset.get("layer_pixels_ge24") or 0) > 0)


def boxes_close(a: list[float], b: list[float], size: tuple[int, int]) -> bool:
    gx, gy = size[0] * CONFIG["fragment_cluster_gap_fraction"], size[1] * CONFIG["fragment_cluster_gap_fraction"]
    expanded = [a[0] - gx, a[1] - gy, a[2] + gx, a[3] + gy]
    return intersection(expanded, b) > 0


def cluster_assets(assets: list[dict], size: tuple[int, int]) -> list[list[dict]]:
    remaining = {a["asset_id"]: a for a in assets}
    groups = []
    while remaining:
        _, seed = remaining.popitem()
        group, queue = [seed], [seed]
        while queue:
            current = queue.pop()
            hits = [key for key, other in remaining.items()
                    if boxes_close(native_bbox(current), native_bbox(other), size)]
            for key in hits:
                other = remaining.pop(key)
                group.append(other)
                queue.append(other)
        groups.append(group)
    return groups


def resolve_case(case: dict, out: Path) -> dict:
    page = case["page"]
    original_path = case["audit"] / f"page_{page:04d}" / "original.jpg"
    original = Image.open(original_path).convert("RGB")
    all_assets = load_jsonl(case["audit"] / "visual_assets.jsonl")
    assets = [a for a in all_assets if a["source_page"] == page]
    run_summary = json.loads((case["dolphin"] / "run_summary.json").read_text(encoding="utf-8"))
    layout = load_jsonl(case["dolphin"] / "output_json" / f"page_{page:04d}.json")
    figures = []
    for row in layout:
        if row.get("label") != "fig" or not row.get("bbox"):
            continue
        figures.append({
            "layout_id": f"dolphin_fig_ro_{row.get('reading_order')}",
            "reading_order": row.get("reading_order"),
            "bbox": scale_box(row["bbox"], run_summary["image_size"], original.size),
        })

    resolved, represented = [], set()
    native = [a for a in assets if native_is_trustworthy(a, case["audit"])]
    for asset in native:
        represented.add(asset["asset_id"])
        resolved.append({
            "state": "NATIVE_SHAPE", "semantic_role_hint": "visual_asset",
            "source_asset_ids": [asset["asset_id"]], "bbox": native_bbox(asset),
            "mask_source": asset["layer_mask"], "matched_layout_figure": None,
            "reason": "renderer mask passed non-empty and placement-consistency checks",
        })

    invalid = [a for a in assets if a["asset_id"] not in represented and a.get("decision") != "FAST_BBOX"]
    rectangular = [a for a in assets if a["asset_id"] not in represented and a.get("decision") == "FAST_BBOX"]
    figure_members: dict[str, list[dict]] = defaultdict(list)
    unmatched = []
    for asset in invalid:
        box = native_bbox(asset)
        matches = []
        for fig in figures:
            coverage = intersection(box, fig["bbox"]) / max(1.0, area(box))
            if coverage >= CONFIG["fragment_to_figure_min_coverage"] or center_inside(box, fig["bbox"]):
                matches.append((coverage, fig))
        if matches:
            matches.sort(key=lambda item: item[0], reverse=True)
            figure_members[matches[0][1]["layout_id"]].append(asset)
        else:
            unmatched.append(asset)

    visual_masks = {}
    for fig in figures:
        members = figure_members.get(fig["layout_id"], [])
        if not members:
            continue
        for member in members:
            represented.add(member["asset_id"])
        mask = visual_foreground_mask(original, fig["bbox"])
        mask_name = f"{case['document']}_page_{page:04d}_{fig['layout_id']}_visual_mask.png"
        mask_path = out / "masks" / mask_name
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(mask_path)
        support = int(np.count_nonzero(np.asarray(mask) >= 24))
        if support:
            state, reason = "VISUAL_SHAPE", "invalid PDF fragments absorbed by a layout figure; foreground estimated from page pixels"
            visual_masks[fig["layout_id"]] = mask
        else:
            state, reason = "BBOX_FALLBACK", "layout figure matched but page-pixel shape extraction had no stable support"
        resolved.append({
            "state": state, "semantic_role_hint": "visual_asset",
            "source_asset_ids": [a["asset_id"] for a in members], "bbox": fig["bbox"],
            "source_fragment_bboxes": [native_bbox(a) for a in members],
            "mask_source": str(mask_path.relative_to(out)) if support else None,
            "matched_layout_figure": fig["layout_id"], "visual_support_pixels": support,
            "reason": reason,
        })

    for group in cluster_assets(unmatched, original.size):
        for member in group:
            represented.add(member["asset_id"])
        role = "structural_decoration" if all(area(native_bbox(a)) / (original.width * original.height) < .005 for a in group) else "visual_asset"
        resolved.append({
            "state": "BBOX_FALLBACK", "semantic_role_hint": role,
            "source_asset_ids": [a["asset_id"] for a in group],
            "bbox": union_box([native_bbox(a) for a in group]),
            "source_fragment_bboxes": [native_bbox(a) for a in group],
            "mask_source": None, "matched_layout_figure": None,
            "reason": "no trustworthy native or layout-supported shape; preserve conservative geometry and provenance",
        })

    for asset in rectangular:
        represented.add(asset["asset_id"])
        resolved.append({
            "state": "BBOX_FALLBACK", "semantic_role_hint": "visual_asset",
            "source_asset_ids": [asset["asset_id"]], "bbox": native_bbox(asset),
            "source_fragment_bboxes": [native_bbox(asset)], "mask_source": None,
            "matched_layout_figure": None,
            "reason": "source gate classified this as a simple rectangular asset",
        })

    if represented != {a["asset_id"] for a in assets}:
        raise RuntimeError("Not every source asset received a terminal representation")
    for index, row in enumerate(sorted(resolved, key=lambda r: (r["bbox"][1], r["bbox"][0])), 1):
        row.update({"resolved_asset_id": f"{case['document']}_p{page:04d}_R{index:03d}",
                    "document": case["document"], "page": page,
                    "image_size": list(original.size), "terminal": True})

    overlay = original.copy()
    colors = {"NATIVE_SHAPE": "#00b86b", "VISUAL_SHAPE": "#0077ff", "BBOX_FALLBACK": "#ff8a00"}
    for row in resolved:
        if row["state"] == "NATIVE_SHAPE":
            mask = Image.open(case["audit"] / row["mask_source"]).convert("L").point(lambda x: 255 if x >= 24 else 0)
            edge = mask.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
            overlay.paste(Image.new("RGB", overlay.size, colors[row["state"]]), (0, 0), edge)
        elif row["state"] == "VISUAL_SHAPE":
            mask = visual_masks[row["matched_layout_figure"]]
            edge = mask.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
            overlay.paste(Image.new("RGB", overlay.size, colors[row["state"]]), (0, 0), edge)
    draw = ImageDraw.Draw(overlay)
    for row in resolved:
        box = clip_box(row["bbox"], original.size)
        color = colors[row["state"]]
        draw.rectangle(box, outline=color, width=3)
        label = f"{row['resolved_asset_id'].split('_')[-1]} {row['state']} ({len(row['source_asset_ids'])})"
        draw.text((box[0] + 3, max(0, box[1] - 14)), label, fill=color, stroke_width=2, stroke_fill="white")
    page_slug = f"{case['document']}_page_{page:04d}"
    overlay_path = out / "overlays" / f"{page_slug}.jpg"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(overlay_path, quality=93)
    return {
        "document": case["document"], "page": page, "source_assets": len(assets),
        "resolved_assets": len(resolved), "fragments_collapsed": len(assets) - len(resolved),
        "state_counts": dict(Counter(r["state"] for r in resolved)),
        "semantic_role_counts": dict(Counter(r["semantic_role_hint"] for r in resolved)),
        "unresolved": 0, "overlay": str(overlay_path.relative_to(out)), "records": resolved,
    }


def build_html(cases: list[dict], out: Path) -> None:
    sections = []
    for case in cases:
        rows = "".join(
            f"<tr><td>{html.escape(r['resolved_asset_id'])}</td><td><b>{r['state']}</b></td>"
            f"<td>{html.escape(r['semantic_role_hint'])}</td><td>{len(r['source_asset_ids'])}</td>"
            f"<td><code>{html.escape(', '.join(r['source_asset_ids']))}</code></td>"
            f"<td>{html.escape(r['matched_layout_figure'] or '—')}</td><td>{html.escape(r['reason'])}</td></tr>"
            for r in sorted(case["records"], key=lambda x: x["resolved_asset_id"]))
        sections.append(f"""<section><h2>{html.escape(case['document'])} · page {case['page']:04d}</h2>
        <p><b>{case['source_assets']}</b> PDF assets → <b>{case['resolved_assets']}</b> resolved assets;
        {case['fragments_collapsed']} fragments collapsed; unresolved = <b>0</b>. States: {html.escape(str(case['state_counts']))}</p>
        <a href="{case['overlay']}"><img src="{case['overlay']}" alt="overlay"></a>
        <table><thead><tr><th>Resolved ID</th><th>Geometry state</th><th>Role hint</th><th>Members</th><th>Source IDs</th><th>Layout match</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></section>""")
    css = """<style>body{font:14px/1.45 system-ui;margin:20px;background:#eef2f6;color:#17202a}header,section{max-width:1450px;margin:18px auto;background:white;padding:18px;border-radius:8px}img{max-width:100%;border:1px solid #aab4c0}table{width:100%;border-collapse:collapse;margin-top:12px}th,td{border:1px solid #cbd3dc;padding:7px;vertical-align:top}th{background:#edf2f7}code{font-size:11px;word-break:break-all}.legend span{margin-right:18px;font-weight:700}.native{color:#00a25e}.visual{color:#0673e8}.bbox{color:#e87800}</style>"""
    body = f"""<!doctype html><meta charset="utf-8"><title>Automated asset geometry fallback</title>{css}
    <header><h1>Automated asset geometry fallback · shadow audit</h1>
    <p>Every source asset reaches one terminal geometry state. Multiple invalid PDF fragments may collapse into one layout-supported visual asset; no content is deleted.</p>
    <p class="legend"><span class="native">Green: NATIVE_SHAPE</span><span class="visual">Blue: VISUAL_SHAPE</span><span class="bbox">Orange: BBOX_FALLBACK</span></p></header>{''.join(sections)}"""
    (out / "automated_asset_geometry_report.html").write_text(body, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [resolve_case(case, args.output) for case in CASES]
    records = [row for case in cases for row in case["records"]]
    with (args.output / "resolved_assets.jsonl").open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "experiment": "automated-asset-geometry-fallback-v1", "production_modified": False,
        "config": CONFIG, "source_assets": sum(c["source_assets"] for c in cases),
        "resolved_assets": len(records), "source_fragments_collapsed": sum(c["fragments_collapsed"] for c in cases),
        "terminal_state_counts": dict(Counter(r["state"] for r in records)),
        "unresolved": 0,
        "invariant": "every source asset ID appears in exactly one terminal resolved record",
        "cases": [{k: v for k, v in c.items() if k != "records"} for c in cases],
    }
    write_json(args.output / "summary.json", summary)
    build_html(cases, args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
