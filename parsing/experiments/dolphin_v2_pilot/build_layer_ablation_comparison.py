#!/usr/bin/env python3
"""Build a human-reviewed comparison of the Dolphin layer-mask ablation."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / "parsing/audits/dolphin_layer_parsing_ablation_v1"
WORK = AUDIT / "work"


def markdown(case_id: str) -> str:
    path = WORK / case_id / "markdown" / f"{case_id}.md"
    return path.read_text(encoding="utf-8")


def embedded(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else "png"
    return f"data:image/{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def count_rows(text: str) -> int:
    return text.count("<tr")


def main() -> None:
    groups = [
        {
            "id": "DLR page 9 · ship/sea asset",
            "prefix": "dlr_page_0009_asset_01",
            "baseline": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0009/markdown/page_0009.md",
            "verdict": "ORIGINAL_CROP_BEST",
            "finding": "The crop reads the title and overlaid ship caption more faithfully than the full-page baseline. Visible-support OCR changes GNSS to GPRS and invents cellular/5G wording. The isolated layer contains no overlay text.",
        },
        {
            "id": "DLR page 9 · antenna/background asset",
            "prefix": "dlr_page_0009_asset_03",
            "baseline": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0009/markdown/page_0009.md",
            "verdict": "ORIGINAL_CROP_BEST",
            "finding": "The crop corrects several full-page OCR errors in ROBUST RECEIVERS and preserves the right-page reading sequence. Both mask-only views collapse to one figure because the article text is painted separately from the raster asset.",
        },
        {
            "id": "DLR page 17 · full-page visual",
            "prefix": "dlr_page_0017_asset_01",
            "baseline": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0017/markdown/page_0017.md",
            "verdict": "NO_DIFFERENCE",
            "finding": "All inputs are classified as a single figure. The layer views add no structure or text.",
        },
        {
            "id": "NVIDIA page 5 · full-page background",
            "prefix": "nvidia_page_0005_asset_01",
            "baseline": ROOT / "parsing/experiments/dolphin_v2_pilot/work/government_financial_v1/nvidia_2026_annual_report/pages/page_0005/markdown/page_0005.md",
            "verdict": "ORIGINAL_EQUALS_VISIBLE",
            "finding": "Original and visible-support outputs are identical and recover all visible overlay text. The isolated background layer removes that text and becomes one figure.",
        },
    ]
    table_cases = [
        {
            "id": "NIST page 28 table",
            "new": "nist_table_original_control",
            "old": ROOT / "parsing/experiments/dolphin_v2_pilot/work/government_financial_v1/nist_ai_rmf_1_0/pages/page_0028/markdown/page_0028.md",
            "verdict": "MIXED_RESOLUTION_EFFECT",
            "finding": "The 1600 px rerun recovers GOVERN 1.7, which the earlier run omitted, but merges the table from 9 HTML rows into 5. This is a resolution/decoding tradeoff, not a layer-mask gain.",
        },
        {
            "id": "NVIDIA page 128 tables",
            "new": "nvidia_table_original_control",
            "old": ROOT / "parsing/experiments/dolphin_v2_pilot/work/government_financial_v1/nvidia_2026_annual_report/pages/page_0128/markdown/page_0128.md",
            "verdict": "IDENTICAL",
            "finding": "The rerun exactly matches the existing Dolphin result: three tables and the same cell structure. Layer masks are irrelevant because these tables are text/vector content.",
        },
    ]
    reviewed = []
    sections = []
    variants = ["original_crop", "visible_support", "isolated_layer"]
    for group in groups:
        columns = []
        outputs = {}
        for variant in variants:
            case_id = f"{group['prefix']}_{variant}"
            text = markdown(case_id)
            outputs[variant] = {"characters": len(text), "output": text}
            image_path = AUDIT / f"{case_id}.png"
            columns.append(
                f"<article><h3>{variant}</h3><img src='{embedded(image_path)}'>"
                f"<pre>{html.escape(text)}</pre></article>"
            )
        baseline = group["baseline"].read_text(encoding="utf-8")
        reviewed.append({
            "case": group["id"], "verdict": group["verdict"], "finding": group["finding"],
            "baseline_path": str(group["baseline"]), "baseline_characters": len(baseline),
            "variants": outputs,
        })
        sections.append(
            f"<section><h2>{html.escape(group['id'])}</h2><p class='verdict'>{group['verdict']}</p>"
            f"<p>{html.escape(group['finding'])}</p><details><summary>Existing full-page Dolphin baseline</summary>"
            f"<pre>{html.escape(baseline)}</pre></details><div class='grid'>{''.join(columns)}</div></section>"
        )
    for case in table_cases:
        old = case["old"].read_text(encoding="utf-8")
        new = markdown(case["new"])
        reviewed.append({
            "case": case["id"], "verdict": case["verdict"], "finding": case["finding"],
            "old_path": str(case["old"]), "old_characters": len(old), "new_characters": len(new),
            "old_table_count": old.count("<table"), "new_table_count": new.count("<table"),
            "old_row_count": count_rows(old), "new_row_count": count_rows(new),
            "exact_match": old == new,
        })
        sections.append(
            f"<section><h2>{html.escape(case['id'])}</h2><p class='verdict'>{case['verdict']}</p>"
            f"<p>{html.escape(case['finding'])}</p><div class='grid two'>"
            f"<article><h3>Existing Dolphin</h3><pre>{html.escape(old)}</pre></article>"
            f"<article><h3>1600 px control rerun</h3><pre>{html.escape(new)}</pre></article></div></section>"
        )
    conclusion = {
        "layer_mask_improves_parsing": False,
        "local_crop_improves_some_dense_pages": True,
        "recommended_policy": "Keep full-page Dolphin as primary parsing. Use native asset geometry to propose local original-page crops for a gated retry when the full-page result is suspicious. Retain visible/layer masks as geometry and image-description inputs; do not substitute them for parsing input.",
        "evidence": {
            "isolated_layer_structured_text_recoveries": 0,
            "image_groups_tested": 4,
            "visible_support_clear_wins": 0,
            "original_crop_clear_wins": 2,
            "no_material_change_groups": 2,
        },
    }
    (AUDIT / "comparison_assessment.json").write_text(
        json.dumps({"conclusion": conclusion, "reviewed_cases": reviewed,
                    "accuracy_claim": "Human audit of selected cases; no complete gold benchmark."},
                   indent=2, ensure_ascii=False), encoding="utf-8"
    )
    style = """<style>body{font:15px/1.5 system-ui;margin:22px;background:#edf1f6;color:#17202a}header,section{max-width:1600px;margin:18px auto;padding:18px;background:white;border-radius:10px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.grid.two{grid-template-columns:repeat(2,1fr)}article{min-width:0;border:1px solid #ccd3dc;padding:10px}img{width:100%;max-height:700px;object-fit:contain;background:#eee}pre{white-space:pre-wrap;max-height:620px;overflow:auto;background:#f5f7fa;padding:10px}.verdict{font-weight:700;color:#8b3f00}@media(max-width:1000px){.grid,.grid.two{grid-template-columns:1fr}}</style>"""
    header = ("<header><h1>Dolphin layer-mask parsing comparison</h1>"
              "<p><b>Result:</b> layer masks did not improve parsing in this pilot. Local crops improved two dense DLR regions; the gain came from scale and reduced page complexity.</p>"
              f"<pre>{html.escape(json.dumps(conclusion, indent=2))}</pre></header>")
    (AUDIT / "comparison_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Dolphin layer parsing comparison</title>" +
        style + header + "".join(sections), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
