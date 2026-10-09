#!/usr/bin/env python3
"""Diagnostic foreground/background prompts for difficult poster components.

Points are hand selected on saved local crops. This tests whether explicit
background guidance helps before attempting automatic prompt generation.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
CASES = [
    {
        "id": "cosmic_scale", "target": "Temperature-scale S curve",
        "path": "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crop": [1500, 2000, 4300, 4800],
        "positive": [(270, 50), (177, 340), (240, 665), (485, 875), (850, 1095), (1060, 1355)],
        "negative": [(470, 50), (550, 415), (670, 795), (1100, 760), (560, 1270), (1000, 300)],
    },
    {
        "id": "cosmic_xrism", "target": "XRISM spacecraft, excluding the label",
        "path": "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crop": [0, 5100, 1650, 6400], "box": [7.8, 118.3, 1562.6, 1264.7],
        "positive": [(180, 300), (430, 430), (725, 800), (1080, 350), (1020, 780)],
        "negative": [(650, 140), (1150, 900), (850, 1040), (1320, 600)],
    },
    {
        "id": "spherex_spacecraft", "target": "SPHEREx spacecraft, excluding the beams",
        "path": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_spherex_poster/SPHEREx_Poster.jpg",
        "crop": [1450, 2250, 2200, 3100], "box": [57.8, 76.0, 658.4, 756.9],
        "positive": [(230, 140), (360, 360), (150, 590), (400, 680)],
        "negative": [(550, 30), (690, 180), (660, 640), (90, 760)],
    },
    {
        "id": "euclid_spacecraft", "target": "Euclid spacecraft, with aperture as background",
        "path": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/esa_euclid_mission_poster/Euclid_mission_poster_vertical.jpg",
        "crop": [1100, 2750, 5700, 7400], "box": [90.4, 135.4, 4540.7, 4585.0],
        "positive": [(95, 150), (600, 180), (750, 650), (1200, 730), (680, 1210)],
        "negative": [(230, 1250), (1250, 180), (40, 880), (550, 250)],
    },
    {
        "id": "cosmic_corona", "target": "Diffuse solar corona (hard boundary test)",
        "path": "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crop": [0, 3100, 2200, 4900],
        "positive": [(170, 205), (220, 820), (850, 300), (680, 825)],
        "negative": [(680, 45), (1210, 750), (1230, 150), (760, 1050)],
    },
]
REVIEWS = {
    "cosmic_scale": "One misplaced foreground point makes the highest-scoring SAM candidate fill much of the background. The corrected-points cards below show that accurate foreground prompts recover the local curve; GrabCut still leaks widely. Prompt quality is critical.",
    "cosmic_xrism": "Background points remove the XRISM text from the highest-scoring SAM result. Seeded GrabCut gives an especially clean overall spacecraft silhouette, including both panels.",
    "spherex_spacecraft": "The spacecraft is already strong with SAM positive points. Adding background points excludes neighboring beams but brings little visible improvement. Seeded GrabCut also gives a complete mask.",
    "euclid_spacecraft": "Foreground/background masks still lose dark and reflective spacecraft parts. Earlier Florence polygon is more complete on this crop.",
    "cosmic_corona": "The hard masks pick broad ray wedges, text, or background. The rays fade gradually, so a soft alpha matte or layered representation is more appropriate than a binary silhouette.",
}


def preview(image: Image.Image) -> Image.Image:
    shown = image.copy()
    shown.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    return shown


def overlay(image: Image.Image, mask: np.ndarray, path: Path) -> None:
    small = Image.fromarray(mask.astype(np.uint8) * 255).resize(image.size, Image.Resampling.NEAREST)
    selected = np.asarray(small) > 0
    base = np.asarray(image, dtype=np.float32).copy()
    base[selected] = base[selected] * 0.48 + np.array([39, 228, 111]) * 0.52
    Image.fromarray(base.astype(np.uint8)).save(path, quality=91)


def draw_prompts(image: Image.Image, case: dict, path: Path) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    if "box" in case:
        sx = image.width / (case["crop"][2] - case["crop"][0])
        sy = image.height / (case["crop"][3] - case["crop"][1])
        x1, y1, x2, y2 = case["box"]
        draw.rectangle((x1 * sx, y1 * sy, x2 * sx, y2 * sy), outline="#ffc344", width=5)
    for label, color in [("positive", "#29e46f"), ("negative", "#ff4960")]:
        for x, y in case[label]:
            draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=color, outline="white", width=2)
    canvas.save(path, quality=93)


def point_arrays(case: dict, source: Image.Image, shown: Image.Image, use_negative: bool) -> tuple[np.ndarray, np.ndarray]:
    points = case["positive"] + (case["negative"] if use_negative else [])
    coords = np.array([[x * source.width / shown.width, y * source.height / shown.height] for x, y in points], dtype=np.float32)
    labels = np.array([1] * len(case["positive"]) + ([0] * len(case["negative"]) if use_negative else []), dtype=np.int32)
    return coords, labels


def run_sam(predictor, source: Image.Image, shown: Image.Image, case: dict, area: Path) -> dict:
    predictor.set_image(np.asarray(source))
    variants = [("positive_only", False, False), ("positive_negative", True, False)]
    if "box" in case:
        variants.append(("box_positive_negative", True, True))
    result = {}
    for name, use_negative, use_box in variants:
        coords, labels = point_arrays(case, source, shown, use_negative)
        box = np.array(case["box"], dtype=np.float32) if use_box else None
        masks, scores, _ = predictor.predict(point_coords=coords, point_labels=labels, box=box, multimask_output=True)
        candidates = []
        for i, (mask, score) in enumerate(zip(masks, scores)):
            Image.fromarray(mask.astype(np.uint8) * 255).save(area / f"sam_{name}_{i}.png")
            overlay(shown, mask, area / f"sam_{name}_{i}.jpg")
            px = np.clip(np.rint(coords[:, 0]).astype(int), 0, mask.shape[1] - 1)
            py = np.clip(np.rint(coords[:, 1]).astype(int), 0, mask.shape[0] - 1)
            included = mask[py, px]
            candidates.append({"index": i, "sam_predicted_score": round(float(score), 4),
                               "foreground_fraction": round(float(mask.mean()), 4),
                               "positive_included": int(included[labels == 1].sum()),
                               "negative_excluded": int((~included[labels == 0]).sum())})
        selected = int(np.argmax(scores))
        result[name] = {"selected": selected, "candidates": candidates}
    return result


def run_grabcut(shown: Image.Image, case: dict, area: Path) -> dict:
    rgb = np.asarray(shown)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.full((shown.height, shown.width), cv2.GC_PR_BGD, np.uint8)
    if "box" in case:
        sx = shown.width / (case["crop"][2] - case["crop"][0])
        sy = shown.height / (case["crop"][3] - case["crop"][1])
        x1, y1, x2, y2 = case["box"]
        mask[max(0, round(y1 * sy)):min(shown.height, round(y2 * sy)),
             max(0, round(x1 * sx)):min(shown.width, round(x2 * sx))] = cv2.GC_PR_FGD
    else:
        # Without a detector box, the interior remains uncertain. The border
        # and explicit background points keep the model from selecting it all.
        mask[12:-12, 12:-12] = cv2.GC_PR_FGD
    mask[:12, :] = cv2.GC_BGD
    mask[-12:, :] = cv2.GC_BGD
    mask[:, :12] = cv2.GC_BGD
    mask[:, -12:] = cv2.GC_BGD
    for label, code in [("positive", cv2.GC_FGD), ("negative", cv2.GC_BGD)]:
        for x, y in case[label]:
            cv2.circle(mask, (x, y), 8, int(code), -1)
    cv2.grabCut(bgr, mask, None, np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64), 5, cv2.GC_INIT_WITH_MASK)
    selected = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD))
    Image.fromarray(selected.astype(np.uint8) * 255).save(area / "grabcut_fgbg.png")
    overlay(shown, selected, area / "grabcut_fgbg.jpg")
    return {"foreground_fraction": round(float(selected.mean()), 4)}


def build_report(output: Path, rows: list[dict]) -> None:
    sections = []
    for row in rows:
        cid = row["case_id"]
        cards = [f"<figure><img src='{cid}/source.jpg'><figcaption>Original local crop</figcaption></figure>",
                 f"<figure><img src='{cid}/prompts.jpg'><figcaption>Prompts: green foreground, red background, yellow detector box</figcaption></figure>"]
        for name, label in [("positive_only", "SAM: foreground only"),
                            ("positive_negative", "SAM: foreground + background"),
                            ("box_positive_negative", "SAM: box + foreground + background")]:
            data = row.get("sam", {}).get(name)
            if data:
                for info in data["candidates"]:
                    index = info["index"]
                    captions = [f"{label}; candidate {index}",
                                f"mask {info['foreground_fraction']:.1%}; model score {info['sam_predicted_score']:.3f}",
                                f"FG included {info['positive_included']}/{len(row['positive_preview_xy'])}"]
                    if name != "positive_only":
                        captions.append(f"BG excluded {info['negative_excluded']}/{len(row['negative_preview_xy'])}")
                    cards.append(f"<figure><a href='{cid}/sam_{name}_{index}.png'><img src='{cid}/sam_{name}_{index}.jpg'></a><figcaption>{'; '.join(captions)}</figcaption></figure>")
        if row.get("grabcut"):
            cards.append(f"<figure><a href='{cid}/grabcut_fgbg.png'><img src='{cid}/grabcut_fgbg.jpg'></a><figcaption>GrabCut: explicit foreground/background; mask {row['grabcut']['foreground_fraction']:.1%}</figcaption></figure>")
        review = REVIEWS[row["case_id"]]
        if cid == "cosmic_scale":
            corrected = output.parent / "poster_fgbg_pilot_scale_v2" / cid
            if output.name != "poster_fgbg_pilot_scale_v2" and (corrected / "sam_positive_negative_2.jpg").is_file():
                for filename, label in [("prompts.jpg", "Corrected points on the same crop"),
                                        ("sam_positive_only_2.jpg", "Corrected foreground-only SAM: clean local curve"),
                                        ("sam_positive_negative_2.jpg", "Corrected foreground/background SAM: clean local curve")]:
                    href = os.path.relpath(corrected / filename, output)
                    cards.append(f"<figure><a href='{html.escape(href)}'><img src='{html.escape(href)}'></a><figcaption>{label}</figcaption></figure>")
            if output.name == "poster_fgbg_pilot_scale_v2":
                review = "With all six foreground points on the curve, SAM follows the entire visible local segment. Background points exclude the marked text and Sun disk, though they add a few small white-line fragments. This remains a hand-prompted local result."
        sections.append(f"<section><h2>{html.escape(row['target'])}</h2><p>Crop {row['crop']} · Manually placed diagnostic points. {html.escape(row.get('error', ''))}</p><p><strong>Visual review:</strong> {html.escape(review)}</p><div class='grid'>{''.join(cards)}</div></section>")
    page = """<!doctype html><html><head><meta charset='utf-8'><title>Poster foreground/background pilot</title><style>
body{font:15px system-ui;background:#edf1f4;color:#18232c;margin:1.4rem}section{background:#fff;padding:1rem;margin:1rem 0;border-radius:.5rem}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem}figure{margin:0;min-width:0}img{width:100%;height:auto}figcaption{padding:.3rem 0}p{color:#45535e}a{color:#126f8b}
</style></head><body><h1>Foreground/background prompts on poster objects</h1><p>Green overlays are predicted masks. All points and boxes are diagnostic manual prompts on local crops; this does not measure automatic discovery or segmentation accuracy. SAM scores are model predictions. The GrabCut S-line and corona cases are expected to be challenging because other white marks or transparent rays share the background.</p>""" + "".join(sections) + "</body></html>"
    (output / "report.html").write_text(page, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--checkpoint", type=Path, default=ROOT / "parsing/experiments/dolphin_v2_pilot/models/sam_vit_b_01ec64.pth")
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--case-id", action="append", default=[])
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.report_only:
        build_report(args.output, json.loads((args.output / "results.json").read_text()))
        return
    predictor = None
    if not args.prepare_only:
        import torch
        from segment_anything import SamPredictor, sam_model_registry
        torch.set_num_threads(4)
        sam = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint)).to(device="cpu").eval()
        predictor = SamPredictor(sam)
    rows = []
    for case in CASES:
        if args.case_id and case["id"] not in args.case_id:
            continue
        area = args.output / case["id"]
        area.mkdir(exist_ok=True)
        source = Image.open(ROOT / case["path"]).convert("RGB").crop(tuple(case["crop"]))
        shown = preview(source)
        shown.save(area / "source.jpg", quality=92)
        draw_prompts(shown, case, area / "prompts.jpg")
        row = {"case_id": case["id"], "target": case["target"], "source": str(ROOT / case["path"]),
               "crop": case["crop"], "positive_preview_xy": case["positive"], "negative_preview_xy": case["negative"],
               "box_native_xyxy": case.get("box"), "manual_prompts": True, "production_modified": False}
        if predictor is not None:
            try:
                row["sam"] = run_sam(predictor, source, shown, case, area)
                row["grabcut"] = run_grabcut(shown, case, area)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            print(json.dumps({"case": case["id"], "sam": row.get("sam"), "grabcut": row.get("grabcut"), "error": row.get("error")}), flush=True)
        rows.append(row)
        build_report(args.output, rows)
    (args.output / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
