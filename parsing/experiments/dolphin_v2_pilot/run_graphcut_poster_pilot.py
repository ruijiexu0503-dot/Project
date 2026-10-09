#!/usr/bin/env python3
"""Test classical foreground extraction on varied poster illustrations.

Each rectangle is a hand supplied coarse object prompt. This pilot isolates
whether local color/texture separation can recover a useful object boundary.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
CASES = [
    ("cosmic_sun", "Cosmic Temperatures", "Sun disk", "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg", (400, 3200, 1450, 4400), (235, 300, 570, 590)),
    ("cosmic_xrism", "Cosmic Temperatures", "XRISM spacecraft", "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg", (0, 5100, 1650, 6400), (1, 80, 1580, 1220)),
    ("euclid_spacecraft", "Euclid mission poster", "Euclid spacecraft", "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/esa_euclid_mission_poster/Euclid_mission_poster_vertical.jpg", (1100, 2750, 5700, 7400), (70, 180, 4430, 4270)),
    ("spherex_spacecraft", "SPHEREx mission poster", "SPHEREx spacecraft", "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_spherex_poster/SPHEREx_Poster.jpg", (1400, 2200, 2300, 3200), (90, 100, 730, 850)),
    ("milky_center", "Milky Way and Our Location", "Galactic center (negative control)", "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_milky_way_location/Milky_Way_and_Our_Location.png", (1700, 1400, 3900, 3600), (200, 200, 1800, 1800)),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid, poster, target, path, crop, rect in CASES:
        area = args.output / cid
        area.mkdir(exist_ok=True)
        original = Image.open(ROOT / path).convert("RGB").crop(crop)
        work = original.copy()
        work.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        sx, sy = work.width / original.width, work.height / original.height
        x, y, width, height = rect
        prompt = (round(x * sx), round(y * sy), round(width * sx), round(height * sy))
        rgb = np.asarray(work)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        mask = np.zeros((work.height, work.width), np.uint8)
        bgd = np.zeros((1, 65), np.float64)
        fgd = np.zeros((1, 65), np.float64)
        result = {"id": cid, "poster": poster, "target": target, "source": str((ROOT / path).resolve()), "crop_source_xyxy": crop, "coarse_prompt_xywh_in_crop": rect, "algorithm": "OpenCV GrabCut with manual rectangle", "production_modified": False}
        try:
            cv2.grabCut(bgr, mask, prompt, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
            selected = np.logical_or(mask == cv2.GC_FGD, mask == cv2.GC_PR_FGD)
            overlay = rgb.astype(np.float32)
            overlay[selected] = overlay[selected] * 0.47 + np.array([40, 230, 110]) * 0.53
            Image.fromarray(overlay.astype(np.uint8)).save(area / "graphcut_overlay.jpg", quality=92)
            Image.fromarray((selected * 255).astype(np.uint8)).save(area / "graphcut_mask.png")
            result["foreground_fraction"] = round(float(selected.mean()), 4)
            result["selected_pixels"] = int(selected.sum())
        except cv2.error as exc:
            result["error"] = str(exc)
        shown = work.copy()
        d = ImageDraw.Draw(shown)
        px, py, pw, ph = prompt
        d.rectangle((px, py, px + pw, py + ph), outline="#ffb12b", width=5)
        shown.save(area / "prompt.jpg", quality=92)
        work.save(area / "source.jpg", quality=92)
        rows.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    (args.output / "results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    cards = []
    for row in rows:
        cid = row["id"]
        cards.append(f"<section><h2>{html.escape(row['poster'])}: {html.escape(row['target'])}</h2><p>Crop: {row['crop_source_xyxy']} · Manually supplied coarse prompt: {row['coarse_prompt_xywh_in_crop']} · Foreground fraction: {row.get('foreground_fraction', 'error')}</p><div><figure><img src='{cid}/source.jpg'><figcaption>Original crop</figcaption></figure><figure><img src='{cid}/prompt.jpg'><figcaption>Coarse rectangle prompt</figcaption></figure><figure><img src='{cid}/graphcut_overlay.jpg'><figcaption>GraphCut mask on original</figcaption></figure></div></section>")
    page = "<!doctype html><meta charset='utf-8'><title>Poster GraphCut pilot</title><style>body{font:15px system-ui;margin:2rem;background:#f1f4f7}section{background:white;padding:1rem;margin:1rem 0}section div{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}figure{margin:0}img{width:100%}</style><h1>Color/texture foreground extraction across poster styles</h1><p>Green pixels are OpenCV GrabCut predictions from a hand supplied rectangle. This is a prompted pixel-boundary test, not automatic object discovery or measured accuracy.</p>" + "".join(cards)
    (args.output / "report.html").write_text(page)


if __name__ == "__main__":
    main()
