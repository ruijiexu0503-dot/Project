#!/usr/bin/env python3
"""Shadow-only routing of intact spreads to split-page or intact-spread inference.

The source canvas and all geometry remain unchanged.  Crops are viewing/inference
assets with an explicit transform back to source-spread coordinates.
"""
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def accepted_cross_spread_visual(bundle: dict) -> tuple[bool, list[str]]:
    sides = {member.get("logical_page") for member in bundle.get("geometry_members") or []}
    if not {"left", "right"}.issubset(sides):
        return False, []
    evidence = []
    # One native PDF render layer placed on both physical pages is direct provenance.
    if len(bundle.get("render_layer_xrefs") or []) == 1:
        evidence.append("same_native_render_layer_on_both_sides")
    # Multiple layers are accepted only when the existing generic pixel audit merged them.
    if any(row.get("merge") is True for row in bundle.get("same_image_merge_evidence") or []):
        evidence.append("verified_render_layer_pixel_merge")
    return bool(evidence), evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--visual-bundles", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--pages", nargs="+", required=True)
    args = ap.parse_args()

    project = args.project_root.resolve()
    output = args.output.resolve()
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    manifest = read_json(args.manifest)
    selected = set(args.pages)

    mappings = defaultdict(dict)
    for row in manifest.get("pages") or []:
        if row.get("source_page") in selected and row.get("side") in {"left", "right"}:
            mappings[row["source_page"]][row["side"]] = row
    bundles = defaultdict(list)
    for row in read_jsonl(args.visual_bundles):
        if row.get("source_page") in selected:
            bundles[row["source_page"]].append(row)

    decisions = []
    cards = []
    for source_page in args.pages:
        sides = mappings.get(source_page, {})
        if set(sides) != {"left", "right"}:
            decisions.append({"source_page": source_page, "route": "UNRESOLVED", "reason": "missing_left_or_right_mapping"})
            continue
        source_file = Path(sides["left"]["source_file"])
        if not source_file.is_absolute():
            source_file = project / source_file
        with Image.open(source_file) as opened:
            image = opened.convert("RGB")
        split_x = int(round(float(sides["left"]["bbox"][2])))

        accepted = []
        for bundle in bundles.get(source_page, []):
            ok, evidence = accepted_cross_spread_visual(bundle)
            if ok:
                accepted.append({
                    "visual_id": bundle.get("visual_id"),
                    "evidence": evidence,
                    "render_layer_xrefs": bundle.get("render_layer_xrefs") or [],
                    "geometry_members": bundle.get("geometry_members") or [],
                })

        route = "INTACT_SPREAD" if accepted else "SPLIT_PHYSICAL_PAGES"
        reason = ("verified_cross_spread_visual_provenance" if accepted
                  else "no_verified_cross_spread_visual")
        left_asset = assets / f"{source_page}_left.png"
        right_asset = assets / f"{source_page}_right.png"
        image.crop((0, 0, split_x, image.height)).save(left_asset)
        image.crop((split_x, 0, image.width, image.height)).save(right_asset)

        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        draw.line((split_x, 0, split_x, image.height), fill=(255, 205, 0), width=5)
        for visual in accepted:
            for member in visual["geometry_members"]:
                box = [float(v) for v in member["bbox_envelope_pixels"]]
                draw.rectangle(tuple(round(v) for v in box), outline=(210, 25, 175), width=6)
                draw.text((round(box[0]) + 5, round(box[1]) + 5), visual["visual_id"],
                          fill=(210, 25, 175), stroke_width=2, stroke_fill="white")
        draw.rectangle((8, 8, min(image.width - 8, 620), 58), fill=(255, 255, 255), outline=(20, 30, 45), width=2)
        draw.text((18, 20), f"ROUTE: {route}", fill=(15, 25, 40))
        overlay_asset = assets / f"{source_page}_routing_overlay.png"
        overlay.save(overlay_asset)

        decision = {
            "source_page": source_page,
            "source_image": str(source_file),
            "route": route,
            "reason": reason,
            "split_x": split_x,
            "source_size": [image.width, image.height],
            "accepted_cross_spread_visuals": accepted,
            "inference_views": ([{"view": "intact", "path": str(source_file), "node_scope": "both_pages"},
                                 {"view": "left_context", "path": str(left_asset), "node_scope": "left"},
                                 {"view": "right_context", "path": str(right_asset), "node_scope": "right"}]
                                if accepted else
                                [{"view": "left", "path": str(left_asset), "node_scope": "left"},
                                 {"view": "right", "path": str(right_asset), "node_scope": "right"}]),
            "coordinate_transforms": {
                "left_to_spread": {"dx": 0, "dy": 0},
                "right_to_spread": {"dx": split_x, "dy": 0},
            },
            # Splitting inference scope never suppresses document-level linkage.
            "cross_page_link_stage_required": True,
            "cross_page_link_tasks": ["article_continuation", "recurring_editorial_lane_or_module"],
            "production_modified": False,
        }
        decisions.append(decision)
        visual_rows = "".join(
            f"<li><code>{html.escape(v['visual_id'])}</code>: {html.escape(', '.join(v['evidence']))}</li>"
            for v in accepted) or "<li>none</li>"
        cards.append(
            f"<section><h2>{html.escape(source_page)} — {route}</h2>"
            f"<p>{html.escape(reason)}. Cross-page article/module linking remains enabled.</p>"
            f"<img class='spread' src='assets/{overlay_asset.name}' alt='routing overlay'>"
            f"<div class='crops'><img src='assets/{left_asset.name}'><img src='assets/{right_asset.name}'></div>"
            f"<h3>Accepted cross-spread visuals</h3><ul>{visual_rows}</ul></section>"
        )

    jsonl = output / "routing_decisions.jsonl"
    jsonl.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in decisions) + "\n", encoding="utf-8")
    summary = {
        "experiment": "hybrid_spread_routing_shadow_v1",
        "document_id": manifest.get("document_id"),
        "pages_requested": len(args.pages),
        "resolved": sum(row.get("route") != "UNRESOLVED" for row in decisions),
        "intact_spread": sum(row.get("route") == "INTACT_SPREAD" for row in decisions),
        "split_physical_pages": sum(row.get("route") == "SPLIT_PHYSICAL_PAGES" for row in decisions),
        "unresolved": sum(row.get("route") == "UNRESOLVED" for row in decisions),
        "policy": {
            "intact": "native cross-side render layer or verified pixel-merged render layers",
            "split": "no verified cross-spread visual; create reversible viewports only",
            "link_after_split": ["article_continuation", "recurring_editorial_lane_or_module"],
        },
        "production_modified": False,
    }
    write_json(output / "summary.json", summary)
    report = """<!doctype html><html><head><meta charset='utf-8'><title>Hybrid spread routing</title>
<style>body{font:14px/1.5 system-ui;background:#eef2f7;color:#182234;margin:24px}header,section{max-width:1450px;margin:18px auto;background:white;padding:18px;border:1px solid #d5dce6;border-radius:10px}.spread{width:100%;height:auto}.crops{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.crops img{width:100%;height:auto;border:1px solid #b8c2d0}code{background:#eef1f5;padding:2px 5px}</style></head><body>"""
    report += (f"<header><h1>Hybrid logical-spread routing — {html.escape(str(manifest.get('document_id')))}</h1>"
               f"<p>{summary['intact_spread']} intact · {summary['split_physical_pages']} split · "
               "no source image, bbox, parsing output, or production routing was modified.</p>"
               "<p>Yellow: physical gutter. Magenta: exact members of an accepted cross-spread visual. "
               "Split pages still enter document-level continuation and recurring-lane linking.</p></header>")
    report += "".join(cards) + "</body></html>"
    (output / "hybrid_spread_routing_report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
