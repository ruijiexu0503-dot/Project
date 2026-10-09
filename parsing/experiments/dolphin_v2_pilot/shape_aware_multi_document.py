#!/usr/bin/env python3
"""Cross-document audit of bbox geometry versus existing PDF asset masks."""
from __future__ import annotations

import html
import json
import statistics
from pathlib import Path

import fitz

from shape_aware_asset_geometry import build_report, make_case, union_box, write_json


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "parsing/audits/shape_aware_multi_document_v1"

DOCUMENTS = [
    ("dlr_magazine", "magazine", ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2"),
    ("clad_magazine", "magazine", ROOT / "parsing/audits/gated_background_assets_shadow_v1/CLADmag_2025_H2_shape_sample_v1"),
    ("gw150914_paper", "scientific_paper", ROOT / "parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full"),
    ("nist_report", "government_report", ROOT / "parsing/audits/gated_background_assets_shadow_v1/NIST_AI_RMF_full_v2"),
    ("nvidia_report", "financial_report", ROOT / "parsing/audits/gated_background_assets_shadow_v1/NVIDIA_2026_Annual_Report_full_v1"),
]


def load_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def bbox_area(asset):
    width, height = asset["image_size"]
    box = union_box([m["rendered_bbox_pixels"] for m in asset["render_layer_members"]])
    x1, y1 = max(0, box[0]), max(0, box[1])
    x2, y2 = min(width, box[2]), min(height, box[3])
    return max(1.0, (x2 - x1) * (y2 - y1)), max(1.0, width * height)


def select_examples(assets, limit=5):
    candidates = []
    for asset in assets:
        if not asset.get("layer_mask") or not asset.get("visible_mask"):
            continue
        area, page_area = bbox_area(asset)
        area_fraction = area / page_area
        features = asset["features"]
        false_text = max(0, features["bbox_text_lines"] - features["supported_text_lines"])
        irregularity = max(features.get("support_missing_fraction", 0),
                            1 - asset.get("layer_pixels_ge24", area) / area)
        if area_fraction < .005 and false_text == 0:
            continue
        score = false_text * 20 + irregularity * 8 + area_fraction * 2
        score += 2 if features.get("source_soft_mask") else 0
        score += 2 if features.get("nonrect_clip") else 0
        candidates.append((score, asset))
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected, pages = [], set()
    for _, asset in candidates:
        if asset["source_page"] in pages and len(pages) < limit:
            continue
        selected.append(asset)
        pages.add(asset["source_page"])
        if len(selected) == limit:
            break
    if len(selected) < limit:
        for _, asset in candidates:
            if asset not in selected:
                selected.append(asset)
            if len(selected) == limit:
                break
    return selected


def audit_document(slug, kind, source):
    summary_path = source / "summary.json"
    assets_path = source / "visual_assets.jsonl"
    if not summary_path.exists() or not assets_path.exists():
        return {"document": slug, "document_type": kind, "status": "missing_complete_source"}
    source_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pdf = Path(source_summary["input_pdf"])
    assets = load_jsonl(assets_path)
    generated_masks = [a for a in assets if a.get("layer_mask") and a.get("visible_mask")]
    dual = [a for a in generated_masks if a.get("mask_placement_consistent") is not False]
    fractions = []
    for asset in dual:
        area, _ = bbox_area(asset)
        fractions.append(min(1.0, asset.get("layer_pixels_ge24", area) / area))
    bbox_lines = sum(a["features"]["bbox_text_lines"] for a in dual)
    supported_lines = sum(a["features"]["supported_text_lines"] for a in dual)
    selected = select_examples(dual)
    doc_out = OUT / slug
    doc_out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    examples = [make_case(doc, asset, source, doc_out) for asset in selected]
    build_report(examples, doc_out)
    result = {
        "document": slug,
        "document_type": kind,
        "status": "complete",
        "pdf": str(pdf),
        "pages_in_source_audit": source_summary["totals"]["pages"],
        "total_assets": len(assets),
        "generated_shape_masks": len(generated_masks),
        "assets_with_shape_masks": len(dual),
        "excluded_untrustworthy_masks": len(generated_masks) - len(dual),
        "source_unresolved_events": source_summary["totals"].get("unresolved", 0),
        "bbox_text_candidates": bbox_lines,
        "strong_shape_supported_text": supported_lines,
        "bbox_candidates_rejected_by_strong_shape_test": max(0, bbox_lines - supported_lines),
        "rejection_fraction": round(max(0, bbox_lines - supported_lines) / max(1, bbox_lines), 5),
        "median_shape_fraction_of_bbox": round(statistics.median(fractions), 5) if fractions else None,
        "assets_below_90pct_bbox_support": sum(x < .9 for x in fractions),
        "example_asset_ids": [a["asset_id"] for a in selected],
        "report": f"{slug}/shape_aware_report.html",
    }
    write_json(doc_out / "document_summary.json", result)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [audit_document(*item) for item in DOCUMENTS]
    complete = [r for r in rows if r["status"] == "complete"]
    totals = {
        "documents": len(complete),
        "assets_with_shape_masks": sum(r["assets_with_shape_masks"] for r in complete),
        "bbox_text_candidates": sum(r["bbox_text_candidates"] for r in complete),
        "strong_shape_supported_text": sum(r["strong_shape_supported_text"] for r in complete),
        "bbox_candidates_rejected_by_strong_shape_test": sum(r["bbox_candidates_rejected_by_strong_shape_test"] for r in complete),
    }
    totals["rejection_fraction"] = round(
        totals["bbox_candidates_rejected_by_strong_shape_test"] / max(1, totals["bbox_text_candidates"]), 5)
    payload = {"summary": totals, "documents": rows, "production_modified": False,
               "strong_shape_test": "asset mask covers at least 50% of the native text-line bbox (fixed existing gate policy)"}
    write_json(OUT / "multi_document_summary.json", payload)
    table_rows = "".join(
        f"<tr><td>{html.escape(r['document'])}</td><td>{html.escape(r['document_type'])}</td>"
        f"<td>{r.get('pages_in_source_audit','—')}</td><td>{r.get('assets_with_shape_masks','—')}</td>"
        f"<td>{r.get('excluded_untrustworthy_masks','—')}</td>"
        f"<td>{r.get('bbox_text_candidates','—')}</td><td>{r.get('strong_shape_supported_text','—')}</td>"
        f"<td>{r.get('bbox_candidates_rejected_by_strong_shape_test','—')}</td>"
        f"<td>{r.get('rejection_fraction',0):.1%}</td>"
        f"<td><a href='{r.get('report','#')}'>examples</a></td></tr>" for r in complete)
    css = """<style>body{font:15px/1.5 system-ui;background:#edf1f6;margin:20px;color:#17202a}header,section{max-width:1400px;margin:18px auto;background:white;padding:18px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd4df;padding:8px;text-align:left}th{background:#eef2f6}.num{font-size:28px;font-weight:700}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#f4f7fa;padding:12px}@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}</style>"""
    body = f"""<!doctype html><meta charset='utf-8'><title>Shape-aware cross-document audit</title>{css}
    <header><h1>Shape-aware geometry across document types</h1><p>The same fixed mask policy is used for every document. Detailed pages show bbox, complete asset shape, visible shape, and text-overlap decisions.</p>
    <div class='cards'><div class='card'><div class='num'>{totals['documents']}</div>documents</div><div class='card'><div class='num'>{totals['assets_with_shape_masks']}</div>masked assets</div><div class='card'><div class='num'>{totals['bbox_text_candidates']}</div>bbox text candidates</div><div class='card'><div class='num'>{totals['bbox_candidates_rejected_by_strong_shape_test']}</div>rejected by shape</div></div></header>
    <section><table><thead><tr><th>Document</th><th>Type</th><th>Pages audited</th><th>Trusted masks</th><th>Excluded masks</th><th>Bbox text</th><th>Shape-supported</th><th>Rejected</th><th>Rejected %</th><th>Visuals</th></tr></thead><tbody>{table_rows}</tbody></table></section>"""
    (OUT / "multi_document_report.html").write_text(body, encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
