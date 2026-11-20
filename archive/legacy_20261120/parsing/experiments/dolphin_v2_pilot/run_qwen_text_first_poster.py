#!/usr/bin/env python3
"""Text-first poster grounding pilot.

OCR text is treated as the anchor. Qwen only decides whether a nearby visual
object, leader line, or scale component is actually associated with that text;
segmentation is deferred until after this decision.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "EvidenceNet"))
from evidence_graph.llm_client import TransformersLLM, extract_json

SOURCE = PROJECT / "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg"
OCR = PROJECT / "parsing/experiments/dolphin_v2_pilot/output/poster_all_layers_v1/str_text.jsonl"
RECOVERED = PROJECT / "parsing/experiments/dolphin_v2_pilot/output/poster_text_recovery_v1/recovered_elements.jsonl"
CANDIDATES = PROJECT / "parsing/experiments/dolphin_v2_pilot/output/poster_all_layers_v1/sam_visual_candidates.jsonl"


def load_rows(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def geometry_ids(group, candidate_by_id):
    """Expand a semantic seed to the visual components it describes.

    Qwen selects a semantic seed, but diffuse illustrations (the solar corona
    is the motivating case) are split into several SAM regions.  We therefore
    keep the Qwen IDs as provenance and add nearby non-text candidates as the
    geometry set.  This prevents a small disk component from masquerading as
    the whole phenomenon while still avoiding OCR/text masks.
    """
    seeds = [candidate_by_id[c] for c in group.get("visual_candidate_ids", []) if c in candidate_by_id]
    if not seeds:
        return []
    desc = (group.get("object_description", "") + " " + group.get("claim", "")).lower()
    if not any(k in desc for k in ("corona", "sun-like", "sun", "rays", "radiating")):
        return [c["id"] for c in seeds]
    # Local visual components around the solar-corona seed.  The role and
    # text-overlap checks explicitly exclude OCR-shaped SAM proposals.
    sx = sum((c["bbox"][0] + c["bbox"][2]) / 2 for c in seeds) / len(seeds)
    sy = sum((c["bbox"][1] + c["bbox"][3]) / 2 for c in seeds) / len(seeds)
    out = []
    for c in candidate_by_id.values():
        if c.get("role") != "VISUAL_CANDIDATE" or c.get("text_overlap", 1.0) > 0.05:
            continue
        cx = (c["bbox"][0] + c["bbox"][2]) / 2; cy = (c["bbox"][1] + c["bbox"][3]) / 2
        if ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5 <= 1200:
            out.append(c["id"])
    return out or [c["id"] for c in seeds]


def merge_boxes(boxes, gap=80):
    """Merge overlapping or nearby boxes into connected geometry components."""
    comps = [[list(b)] for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(comps)):
            if changed: break
            ai = comps[i]
            ax1 = min(b[0] for b in ai); ay1 = min(b[1] for b in ai); ax2 = max(b[2] for b in ai); ay2 = max(b[3] for b in ai)
            for j in range(i + 1, len(comps)):
                bj = comps[j]
                bx1 = min(b[0] for b in bj); by1 = min(b[1] for b in bj); bx2 = max(b[2] for b in bj); by2 = max(b[3] for b in bj)
                # Test original members, not a growing enclosing rectangle
                # that could absorb unrelated objects in its empty corners.
                separated = not any(
                    max(a[0]-b[2], b[0]-a[2], 0) ** 2 +
                    max(a[1]-b[3], b[1]-a[3], 0) ** 2 <= gap ** 2
                    for a in ai for b in bj)
                if not separated:
                    comps[i].extend(comps.pop(j)); changed = True; break
    return [[min(b[0] for b in c), min(b[1] for b in c), max(b[2] for b in c), max(b[3] for b in c)] for c in comps]


def prompt(text_rows, recovered_rows, candidate_rows, size):
    return """You are grounding text labels in a scientific poster. The OCR text is the primary anchor. For each target text item, inspect the poster and decide whether it has a corresponding visual object, scale/axis, or leader line. Do not assume every text item has an object. Do not invent a mask or object when the image is ambiguous.

Return JSON only:
{"groups":[{"text_ids":["STR_048"],"claim":"...", "object_status":"MATCHED|PARTIAL|NONE|UNCERTAIN", "object_description":"...", "visual_candidate_ids":["SAM_0001"], "relation":"LABELS|VALUES|POINTS_TO|PART_OF|NONE", "related_text_ids":[], "segment_after_grounding":true, "reason":"...", "confidence":0.0}], "unresolved":[]}

Rules:
- Account for every supplied OCR ID, including headings, credits and scales. If no correspondence is found, return NONE or UNCERTAIN; never omit the text.
- A mission title can name a distant central illustration. Inspect the main illustration as well as nearby objects.
- Report visible objects without a text label as groups with empty text_ids. Do not force a false text association.
- MATCHED requires at least one valid selected visual candidate. If the object is visible but absent from candidates, return PARTIAL and explain that geometry is missing.
- The claim must be grounded in the supplied OCR text.
- MATCHED means a distinct object is visibly associated with the text.
- PARTIAL is appropriate for diffuse rays, decorative illustrations, or an object whose boundary is incomplete.
- A number next to a named phenomenon is a value claim even if no object mask is reliable.
- `segment_after_grounding` is true only for a distinct object with a plausible boundary.
- You may only select IDs from VISUAL CANDIDATES below. Never invent a bbox or an ID.
- Candidate boxes may include imperfect masks; use PARTIAL when only a component is covered.

POSTER SIZE: %s
OCR ANCHORS:
%s
RECOVERED TEXT BLOCKS:
%s
VISUAL CANDIDATES (IDs and native pixel boxes; do not output boxes):
%s
""" % (size, json.dumps(text_rows, ensure_ascii=False), json.dumps(recovered_rows, ensure_ascii=False), json.dumps(candidate_rows, ensure_ascii=False))


def main():
    global SOURCE, OCR, RECOVERED, CANDIDATES
    ap = argparse.ArgumentParser(); ap.add_argument("--output", required=True); ap.add_argument("--model", default=str(PROJECT / "external/models/Qwen3.5-35B-A3B")); ap.add_argument("--max-new-tokens", type=int, default=1600); ap.add_argument("--report-only", action="store_true"); ap.add_argument("--all-page", action="store_true", help="ground all OCR rows and all non-text visual candidates"); ap.add_argument("--source", default=str(SOURCE)); ap.add_argument("--ocr", default=str(OCR)); ap.add_argument("--candidates", default=str(CANDIDATES)); ap.add_argument("--recovered", help="Optional same-source recovered text; never inherited from another poster")
    args = ap.parse_args(); output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    SOURCE, OCR, CANDIDATES = map(Path, (args.source, args.ocr, args.candidates))
    if args.report_only:
        result = json.loads((output / 'result.json').read_text())
        SOURCE = Path(result['source'])
    image = Image.open(SOURCE).convert("RGB"); size = image.size
    candidate_rows = result['candidate_catalog'] if args.report_only else load_rows(CANDIDATES)
    candidate_by_id = {r["id"]: r for r in candidate_rows}
    if args.report_only:
        result = json.loads((output / "result.json").read_text(encoding="utf-8")); prediction = result["prediction"]
    else:
        ocr = load_rows(OCR); recovered = load_rows(Path(args.recovered)) if args.recovered else []
        targets = ocr if args.all_page else [r for r in ocr if r["id"] in {"STR_041", "STR_042", "STR_048", "STR_049", "STR_050", "STR_056", "STR_065", "STR_075"}]
        # Give Qwen only candidates near the solar-corona/text region. This
        # turns geometry grounding into candidate selection, not free-form box generation.
        candidates = ([r for r in candidate_rows if r.get("role") == "VISUAL_CANDIDATE"] if args.all_page else [r for r in candidate_rows if r["bbox"][1] < 5100 and r["bbox"][3] > 2800 and r["bbox"][0] < 2500])
        llm = TransformersLLM(args.model, dtype="bfloat16", max_new_tokens=args.max_new_tokens, require_cuda=True, enable_thinking=False)
        # A single prompt containing every OCR row collapses to one salient
        # object.  Spatial batches preserve full-page coverage while keeping
        # each grounding decision local enough for Qwen to inspect.
        batches = [targets]
        if args.all_page:
            ordered = sorted(targets, key=lambda r: (r.get("bbox", [0, 0])[1], r.get("bbox", [0, 0])[0]))
            batches = [ordered[i:i + 24] for i in range(0, len(ordered), 24)]
        groups = []; unresolved = []
        for batch in batches:
            raw = llm.generate_raw_with_images("Return grounded JSON only.", prompt(batch, recovered, candidates, size), [str(SOURCE)], args.max_new_tokens).raw
            (output / f'batch_{len(list(output.glob("batch_*.txt"))):03d}.txt').write_text(raw)
            try:
                part = extract_json(raw); groups.extend(part.get("groups", [])); unresolved.extend(part.get("unresolved", []))
            except Exception as exc:
                unresolved.append({"batch_error": f"{type(exc).__name__}: {exc}"})
        # A bounded second pass checks missed text and the main illustration.
        # Keep unselected proposals available; do not assume they are clutter.
        used_text = {t for g in groups for t in g.get('text_ids', [])}
        used_visual = {c for g in groups for c in g.get('visual_candidate_ids', [])}
        missed = [r for r in targets if r['id'] not in used_text]
        pending_visual = [r['id'] for r in candidates if r['id'] not in used_visual]
        if missed or pending_visual:
            review_prompt = prompt(targets, recovered, candidates, size) + '\nCOVERAGE REVIEW: Existing groups: ' + json.dumps(groups, ensure_ascii=False) + '\nOmitted OCR IDs: ' + json.dumps([r['id'] for r in missed]) + '\nUnselected candidate IDs: ' + json.dumps(pending_visual) + '\nReturn only additional groups, not duplicates. Inspect the dominant illustration and informative diffuse regions, even without an adjacent label. Do not invent an association just to cover a candidate. If geometry is missing, say so explicitly.'
            raw = llm.generate_raw_with_images('Return grounded JSON only.', review_prompt, [str(SOURCE)], args.max_new_tokens).raw
            (output / 'coverage_review_raw.txt').write_text(raw)
            try:
                part = extract_json(raw); groups.extend(part.get('groups', [])); unresolved.extend(part.get('unresolved', []))
            except Exception as exc:
                unresolved.append({'coverage_review_error': str(exc)})
        prediction = {"groups": groups, "unresolved": unresolved}
        result = {"source": str(SOURCE.resolve()), "poster_size": size, "ocr_targets": ocr, "candidate_catalog": candidates, "prediction": prediction, "model": args.model, "production_modified": False, "input_paths": {"ocr": str(OCR.resolve()), "candidates": str(CANDIDATES.resolve()), "recovered": str(Path(args.recovered).resolve()) if args.recovered else None}, "geometry_policy": "selected_candidates_only; merged boxes are display envelopes, not segmentation"}
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shown = image.copy(); shown.thumbnail((1400, 1400), Image.Resampling.LANCZOS); draw = ImageDraw.Draw(shown)
    ocr_for_overlay = {r.get("id"): r for r in result.get("ocr_targets", [])} if 'result' in locals() else {}
    used = {t for g in prediction.get('groups', []) for t in g.get('text_ids', [])}
    missing = sorted(set(ocr_for_overlay) - used)
    selected_ids = {c for g in prediction.get('groups', []) for c in g.get('visual_candidate_ids', [])}
    result['coverage'] = {'ocr_total': len(ocr_for_overlay), 'grouped_ocr': len(set(ocr_for_overlay) & used), 'unassigned_text_ids': missing, 'unselected_candidate_ids': sorted(set(candidate_by_id)-selected_ids), 'invalid_text_ids': sorted(used-set(ocr_for_overlay)), 'invalid_candidate_ids': sorted(selected_ids-set(candidate_by_id))}
    prediction['unresolved'] = [u for u in prediction.get('unresolved', []) if not isinstance(u, dict) or u.get('origin') != 'coverage_validator']
    prediction['unresolved'].extend({'text_id': t, 'reason': 'not_returned_by_model', 'origin': 'coverage_validator'} for t in missing)
    sx, sy = shown.width / size[0], shown.height / size[1]
    # Every OCR region remains visible, even when the model omitted it.
    for row in ocr_for_overlay.values():
        b = row['bbox']; draw.rectangle([b[0]*sx,b[1]*sy,b[2]*sx,b[3]*sy], outline='#bcbcbc', width=2)
    seen_geometry = set()
    palette = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000", "#000075"]
    for i, g in enumerate(prediction.get("groups", []) if isinstance(prediction, dict) else []):
        # Preserve Qwen's semantic IDs, while using the expanded geometry set
        # for diffuse objects.  The original IDs remain in result.json.
        gids = [cid for cid in g.get('visual_candidate_ids', []) if cid in candidate_by_id]
        g['geometry_status'] = 'candidate_available' if gids else 'unresolved' if g.get('object_status') in ('MATCHED','PARTIAL') else 'no_geometry'
        g["geometry_candidate_ids"] = gids
        # The caption group and the value group may point to the same object;
        # draw that geometry once so the review image stays readable.
        all_selected = [candidate_by_id[cid] for cid in gids if cid in candidate_by_id]
        color = palette[i % len(palette)] if args.all_page else ("#e33b3b" if g.get("object_status") == "PARTIAL" else "#2fa8e8")
        # Draw OCR anchors as thin boxes in the same group color. Object
        # geometry below is thicker, so the two modalities remain distinct.
        sx, sy = shown.width / size[0], shown.height / size[1]
        for tid in g.get("text_ids", []):
            row = ocr_for_overlay.get(tid)
            if not row or not row.get("bbox"): continue
            tb = row["bbox"]; txy = [tb[0] * sx, tb[1] * sy, tb[2] * sx, tb[3] * sy]
            draw.rectangle(txy, outline=color, width=2)
            draw.text((txy[0] + 2, txy[1] + 2), f"T:{tid}", fill=color, stroke_width=2, stroke_fill="black")
        selected = [candidate_by_id[cid] for cid in gids if cid in candidate_by_id and cid not in seen_geometry]
        seen_geometry.update(gids)
        g["merged_geometry_bboxes"] = merge_boxes([c["bbox"] for c in all_selected], gap=0.01 * min(size))
        for box in merge_boxes([c['bbox'] for c in selected], gap=0.01 * min(size)):
            sx, sy = shown.width / size[0], shown.height / size[1]; xy = [box[0]*sx, box[1]*sy, box[2]*sx, box[3]*sy]
            draw.rectangle(xy, outline=color, width=5); draw.text((xy[0]+3,xy[1]+3), f"G{i+1} {g.get('object_status')}", fill=color, stroke_width=2, stroke_fill="black")
    shown.save(output / "grounding_overlay.jpg", quality=90)
    title = "Full-page text-first poster grounding" if args.all_page else "Text-first poster grounding v2"
    legend = "".join(f"<span style='color:{palette[i % len(palette)]};font-weight:bold;margin-right:12px'>G{i+1}</span>" for i, _ in enumerate(prediction.get("groups", []))) if args.all_page else ""
    ocr_by_id = {r.get("id"): r for r in result.get("ocr_targets", [])} if 'result' in locals() else {}
    rows = []
    for i, g in enumerate(prediction.get("groups", []) if isinstance(prediction, dict) else []):
        texts = "<br>".join(html.escape(ocr_by_id.get(t, {}).get("text", t)) for t in g.get("text_ids", []))
        obj = html.escape(g.get("object_description", "")); ids = html.escape(", ".join(g.get("visual_candidate_ids", [])))
        merged = html.escape(json.dumps(g.get("merged_geometry_bboxes", []), ensure_ascii=False))
        rows.append(f"<tr><td style='color:{palette[i % len(palette)]};font-weight:bold'>G{i+1}</td><td>{texts}</td><td>{obj}</td><td>{html.escape(g.get('object_status',''))}</td><td>{ids}</td><td><code>{merged}</code></td></tr>")
    table = "<table><tr><th>Group</th><th>OCR text</th><th>Object</th><th>Status</th><th>Semantic candidate</th><th>Merged bbox</th></tr>" + "".join(rows) + "</table>"
    table += '<h2>Coverage / unresolved</h2><p>Gray boxes retain unassigned OCR. Object boxes are display envelopes, not masks. Unselected candidates remain in result.json; absence of selection is not absence of an object.</p><pre>' + html.escape(json.dumps(result['coverage'], ensure_ascii=False, indent=2)) + '</pre><ul>' + ''.join('<li>'+html.escape(t+': '+ocr_for_overlay[t]['text'])+'</li>' for t in missing) + '</ul>'
    page = "<!doctype html><meta charset=utf-8><title>" + title + "</title><style>body{font:15px system-ui;max-width:1500px;margin:20px auto;background:#eef2f5}section{background:#fff;padding:16px;margin:16px 0}img{max-width:100%;border:1px solid #ccd5dc}figure{display:inline-block;vertical-align:top;width:48%;margin:0 1% 12px 0}figcaption{padding:5px 0}pre{white-space:pre-wrap;background:#18232c;color:#eef;padding:12px}table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #ccd5dc;padding:7px;vertical-align:top;text-align:left}code{font-size:12px}</style><h1>" + title + "</h1><p>Each row connects OCR text to its semantic object. Thin colored boxes marked T: are OCR text regions; thick colored boxes are object geometry. Overlapping or adjacent visual candidate boxes are merged into connected geometry components.</p><section>" + legend + "</section><figure><img src='grounding_overlay.jpg'><figcaption>Full poster with text and object boxes</figcaption></figure><section>" + table + "</section><section><pre>" + html.escape(json.dumps(prediction, ensure_ascii=False, indent=2)) + "</pre></section>"
    (output / "report.html").write_text(page, encoding="utf-8")
    # Persist the derived geometry IDs for downstream EvidenceNode builders.
    if isinstance(prediction, dict) and (output / "result.json").exists():
        saved = result; saved["prediction"] = prediction
        (output / "result.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"groups": len(prediction.get("groups", [])) if isinstance(prediction, dict) else 0, "output": str(output)}))


if __name__ == "__main__": main()
