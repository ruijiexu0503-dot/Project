#!/usr/bin/env python3
"""Florence-2 local-crop object/diagram pilot on four existing posters.

The prompts and crops are diagnostic examples, not automatic discovery or labels.
Each task is checkpointed so a short dev job can resume without repeating work.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import torch
from PIL import Image, ImageDraw
from transformers import AutoProcessor, Florence2ForConditionalGeneration


ROOT = Path(__file__).resolve().parents[3]
CASES = [
    {
        "id": "cosmic_xrism", "poster": "Cosmic Temperatures", "target": "XRISM spacecraft",
        "image": "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crop": [0, 5100, 1650, 6400], "phrase": "a blue illustrated spacecraft with two solar panels",
    },
    {
        "id": "cosmic_corona", "poster": "Cosmic Temperatures", "target": "Solar corona",
        "image": "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crop": [0, 3100, 2200, 4900], "phrase": "the Sun and its surrounding solar corona rays",
    },
    {
        "id": "cosmic_scale", "poster": "Cosmic Temperatures", "target": "temperature-scale curve",
        "image": "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crop": [1500, 2000, 4300, 4800], "phrase": "the thick curved white temperature scale line",
    },
    {
        "id": "euclid_spacecraft", "poster": "Euclid mission poster", "target": "Euclid spacecraft",
        "image": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/esa_euclid_mission_poster/Euclid_mission_poster_vertical.jpg",
        "crop": [1100, 2750, 5700, 7400], "phrase": "the large Euclid space telescope spacecraft",
    },
    {
        "id": "spherex_spacecraft", "poster": "SPHEREx mission poster", "target": "SPHEREx spacecraft",
        "image": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_spherex_poster/SPHEREx_Poster.jpg",
        "crop": [1450, 2250, 2200, 3100], "phrase": "the small white SPHEREx spacecraft",
    },
    {
        "id": "spherex_beams", "poster": "SPHEREx mission poster", "target": "spectral beams",
        "image": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_spherex_poster/SPHEREx_Poster.jpg",
        "crop": [1450, 400, 3600, 3100], "phrase": "the thin colored light beams extending from the spacecraft",
    },
    {
        "id": "milky_center", "poster": "Milky Way and Our Location", "target": "Galactic center",
        "image": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_milky_way_location/Milky_Way_and_Our_Location.png",
        "crop": [1700, 1400, 3900, 3600], "phrase": "the bright Galactic Bar and center of the Milky Way",
    },
    {
        "id": "milky_sun", "poster": "Milky Way and Our Location", "target": "Sun and Orion Spur",
        "image": "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_milky_way_location/Milky_Way_and_Our_Location.png",
        "crop": [2200, 3450, 3450, 4500], "phrase": "the Sun's location in the Orion Spur",
    },
]
TASKS = ["<OD>", "<OPEN_VOCABULARY_DETECTION>", "<REFERRING_EXPRESSION_SEGMENTATION>"]
COLORS = {"<OD>": "#ffb12b", "<OPEN_VOCABULARY_DETECTION>": "#16dac1", "<REFERRING_EXPRESSION_SEGMENTATION>": "#67e75a"}


def preview(image: Image.Image, max_side: int = 1400) -> Image.Image:
    output = image.copy()
    output.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return output


def each_polygon(value):
    if isinstance(value, (tuple, list)):
        if len(value) >= 6 and len(value) % 2 == 0 and all(isinstance(x, (float, int)) for x in value):
            yield value
        else:
            for child in value:
                yield from each_polygon(child)


def render(image: Image.Image, answer: dict, task: str, output: Path) -> None:
    canvas = preview(image).convert("RGBA")
    sx, sy = canvas.width / image.width, canvas.height / image.height
    cover = Image.new("RGBA", canvas.size)
    d = ImageDraw.Draw(cover, "RGBA")
    color = COLORS[task]
    rgb = tuple(bytes.fromhex(color[1:]))
    for poly in each_polygon(answer.get("polygons", [])):
        points = [(poly[i] * sx, poly[i + 1] * sy) for i in range(0, len(poly), 2)]
        if len(points) >= 3:
            d.polygon(points, fill=(*rgb, 75), outline=(*rgb, 255), width=3)
    canvas = Image.alpha_composite(canvas, cover)
    d = ImageDraw.Draw(canvas)
    boxes = answer.get("bboxes", [])
    labels = answer.get("labels", answer.get("bboxes_labels", []))
    for index, box in enumerate(boxes):
        if len(box) != 4:
            continue
        scaled = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
        d.rectangle(scaled, outline=color, width=4)
        label = str(labels[index]) if index < len(labels) else "object"
        d.text((scaled[0] + 4, max(0, scaled[1] - 24)), label[:45], fill=color, stroke_width=2, stroke_fill="black")
    canvas.convert("RGB").save(output, quality=91)


def run_one(model, processor, image: Image.Image, task: str, phrase: str, max_new_tokens: int) -> dict:
    prompt = task + (phrase if task != "<OD>" else "")
    inputs = processor(images=image, text=prompt, return_tensors="pt")
    inputs = {key: value.to("cuda", dtype=torch.float16) if value.is_floating_point() else value.to("cuda") for key, value in inputs.items()}
    with torch.inference_mode():
        ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, num_beams=3)
    raw = processor.batch_decode(ids, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(text=raw, task=task, image_size=image.size)[task]
    return {"task": task, "prompt": prompt, "raw_generation": raw, "answer": parsed, "generated_tokens": int(ids.shape[-1]), "max_new_tokens": max_new_tokens}


def build_report(output: Path, records: dict) -> None:
    posters = {}
    for case in CASES:
        posters.setdefault(case["poster"], case["id"].split("_", 1)[0])
    overview = "".join(
        f"<figure><img src='overview_{slug}.jpg'><figcaption>{html.escape(name)}</figcaption></figure>"
        for name, slug in posters.items()
    )
    cards = []
    for case in CASES:
        cid = case["id"]
        views = [f"<figure><img src='{cid}/source.jpg'><figcaption>Original local crop</figcaption></figure>"]
        for task, filename in [("<OD>", "od.jpg"), ("<OPEN_VOCABULARY_DETECTION>", "open_vocab.jpg"), ("<REFERRING_EXPRESSION_SEGMENTATION>", "segmentation.jpg")]:
            row = records.get((cid, task))
            status = "not run" if row is None else html.escape(str(row.get("error", ""))) if row.get("error") else html.escape(json.dumps(row.get("answer", {}), ensure_ascii=False))
            views.append(f"<figure><img src='{cid}/{filename}' onerror='this.style.display=\"none\"'><figcaption>{html.escape(task)}<br><small>{status}</small></figcaption></figure>")
        cards.append(f"<section><h2>{html.escape(case['poster'])}: {html.escape(case['target'])}</h2><p>Source crop {case['crop']} · Prompt: {html.escape(case['phrase'])}</p><div class='grid'>{''.join(views)}</div></section>")
    page = """<!doctype html><html><head><meta charset='utf-8'><title>Multi-poster Florence-2 pilot</title><style>
body{font:15px system-ui;background:#edf1f4;margin:1.4rem;color:#18232c}section{background:white;padding:1rem;margin:1.2rem 0;border-radius:.5rem}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem}figure{margin:0;min-width:0}img{width:100%;height:auto}figcaption{overflow-wrap:anywhere;padding:.35rem 0}small{font-size:11px}p{color:#42515d}
</style></head><body><h1>Florence-2 on four poster styles</h1><p>Hand-selected diagnostic crops and phrases. Boxes/polygons are model predictions on each crop, not verified object boundaries. The processor resizes each crop to 768×768 internally.</p><h2>Full-poster overview and tested regions</h2><div class='grid'>""" + overview + "</div>" + "".join(cards) + "</body></html>"
    (output / "report.html").write_text(page, encoding="utf-8")


def prepare_overviews(output: Path) -> None:
    posters = {}
    for case in CASES:
        posters.setdefault(case["poster"], []).append(case)
    for cases in posters.values():
        image = Image.open(ROOT / cases[0]["image"]).convert("RGB")
        shown = preview(image, max_side=1200)
        scale_x, scale_y = shown.width / image.width, shown.height / image.height
        draw = ImageDraw.Draw(shown)
        for case in cases:
            x1, y1, x2, y2 = case["crop"]
            x1, x2 = x1 * scale_x, x2 * scale_x
            y1, y2 = y1 * scale_y, y2 * scale_y
            draw.rectangle((x1, y1, x2, y2), outline="#ffb12b", width=5)
            draw.text((x1 + 3, y1 + 4), case["target"], fill="#ffb12b", stroke_width=2, stroke_fill="black")
        shown.save(output / f"overview_{cases[0]['id'].split('_', 1)[0]}.jpg", quality=88)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ROOT / "external/models/Florence-2-large-ft-native")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-new-tokens", type=int, default=768)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    prepare_overviews(args.output)
    path = args.output / "predictions.jsonl"
    records = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            records[(row["case_id"], row["task"])] = row
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = Florence2ForConditionalGeneration.from_pretrained(args.model, dtype=torch.float16, local_files_only=True).to("cuda").eval()
    print(json.dumps({"model": str(args.model), "cases": len(CASES), "tasks": TASKS}), flush=True)
    for case in CASES:
        cid = case["id"]
        target = args.output / cid
        target.mkdir(exist_ok=True)
        image = Image.open(ROOT / case["image"]).convert("RGB").crop(tuple(case["crop"]))
        preview(image).save(target / "source.jpg", quality=92)
        for task, filename in [("<OD>", "od.jpg"), ("<OPEN_VOCABULARY_DETECTION>", "open_vocab.jpg"), ("<REFERRING_EXPRESSION_SEGMENTATION>", "segmentation.jpg")]:
            key = (cid, task)
            if key in records and "error" not in records[key]:
                continue
            try:
                result = run_one(model, processor, image, task, case["phrase"], args.max_new_tokens)
                render(image, result["answer"], task, target / filename)
                row = {"case_id": cid, "poster": case["poster"], "target": case["target"], "crop_source_xyxy": case["crop"], "source": str((ROOT / case["image"]).resolve()), **result}
            except Exception as exc:
                row = {"case_id": cid, "task": task, "error": f"{type(exc).__name__}: {exc}"}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            records[key] = row
            build_report(args.output, records)
            print(json.dumps({"case": cid, "task": task, "error": row.get("error"), "answer": row.get("answer")}, ensure_ascii=False), flush=True)
    (args.output / "summary.json").write_text(json.dumps({"model": str(args.model), "cases": len(CASES), "tasks_per_case": len(TASKS), "completed_tasks": len(records), "error_count": sum("error" in r for r in records.values()), "production_modified": False}, indent=2) + "\n")
    build_report(args.output, records)


if __name__ == "__main__":
    main()
