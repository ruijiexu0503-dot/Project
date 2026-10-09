#!/usr/bin/env python3
"""Build a small, lossless shadow EvidenceNode graph for one poster.

The pilot deliberately keeps semantic nodes separate from visual components:
OCR and source text ground the claim, while masks/polyline geometry only locate
the relevant pixels. It does not modify the production graph.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg"
LAYERS = ROOT / "parsing/experiments/dolphin_v2_pilot/output/poster_all_layers_v1"
STR = LAYERS / "str_text.jsonl"
RECOVERED = ROOT / "parsing/experiments/dolphin_v2_pilot/output/poster_text_recovery_v1/recovered_elements.jsonl"
STRUCTURE = ROOT / "parsing/experiments/dolphin_v2_pilot/output/poster_str_sam_v1/poster_structure.json"


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def member(source_id, role, bbox=None, text=None, geometry=None):
    block_id = source_id.split(":", 1)[-1]
    return {"source_id": source_id, "page": "page_0001", "block_id": block_id,
            "start_char": 0, "end_char": len(text or ""), "role": role,
            "bbox": bbox, "deepseek_bbox": bbox, "matched_region_id": None,
            "matched_region_label": None, "match_score": None,
            "text": text, "geometry_members": geometry or [],
            "bbox_source": "ocr_or_structural_candidate", "bbox_granularity": "component"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    text = {r["id"]: r for r in rows(STR)}
    recovered = {r["element_id"]: r for r in rows(RECOVERED)}
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    structure_nodes = {r["node_id"]: r for r in structure["nodes"]}
    sam = {r["id"]: r for r in rows(LAYERS / "sam_visual_candidates.jsonl")}

    curve = structure_nodes["SCALE_CURVE_001"]
    corona = structure_nodes["COMPOSITE_SOLAR_CORONA_001"]
    corona_visual = [sam[x] for x in corona["child_mask_nodes"] if x in sam]
    disk = sam.get("SAM_0001")
    text_claim = recovered["page_0001_el_0006"]
    claim_bbox = text_claim["bbox"]
    nodes = [
        {
            "node_id": "cosmic_temperatures_POSTER_EV_000001",
            "doc_id": "cosmic_temperatures_POSTER",
            "section_id": None, "section_path": [],
            "node_type": "evidence",
            "evidence_type": "measurement_system",
            "modalities": ["text", "image", "geometry"],
            "plain_text": "The poster presents a logarithmic Kelvin temperature scale with powers-of-ten markers and labelled examples.",
            "original_markdown": "The poster presents a logarithmic Kelvin temperature scale with powers-of-ten markers and labelled examples.",
            "base_summary": "Poster temperature-scale system.",
            "entities": ["Kelvin scale", "temperature scale"],
            "page_ids": ["page_0001"], "document_order": 1,
            "is_complete": True, "possible_continuation": False, "continuation_reason": None,
            "provisional": True,
            "source_members": [member("poster_structure:SCALE_CURVE_001", "curve", curve["bbox"], geometry=[
                {"kind": "polyline_skeleton", "path": "poster_str_sam_v1/scale_curve_skeleton.png", "skeleton_pixels": curve["geometry"]["skeleton_pixels"]},
                {"kind": "mask", "path": "poster_str_sam_v1/scale_curve_mask.png"}]),
                member("STR_016", "explanatory_text", text["STR_016"]["bbox"], text["STR_016"]["text"]),
                member("STR_032", "scale_label", text["STR_032"]["bbox"], text["STR_032"]["text"])],
            "geometry_members": [{"kind": "curve", "bbox": curve["bbox"], "representation": "polyline/skeleton"}],
            "status": "SHADOW_CANDIDATE", "provenance": {"source": "OCR + structural extraction", "production_modified": False},
        },
        {
            "node_id": "cosmic_temperatures_POSTER_EV_000002",
            "doc_id": "cosmic_temperatures_POSTER",
            "section_id": None, "section_path": [],
            "node_type": "evidence",
            "evidence_type": "labelled_visual_fact",
            "modalities": ["text", "image", "geometry"],
            "plain_text": "The poster labels the solar corona as 3 million K (5.4 million°F).",
            "original_markdown": "Solar corona 3 million K 5.4 million°F",
            "base_summary": "Solar-corona temperature label on the poster.",
            "entities": ["solar corona", "Sun", "3 million K"],
            "page_ids": ["page_0001"], "document_order": 2,
            "is_complete": True, "possible_continuation": False, "continuation_reason": None,
            "provisional": True,
            "source_members": [member("page_0001_el_0006", "claim_text", claim_bbox, text_claim["text"]),
                member("STR_048", "label", text["STR_048"]["bbox"], text["STR_048"]["text"]),
                member("STR_049", "value", text["STR_049"]["bbox"], text["STR_049"]["text"]),
                member("COMPOSITE_SOLAR_CORONA_001", "visual_composite", None, geometry=[
                    {"kind": "mask_component", "id": r["id"], "bbox": r["bbox"], "mask_path": r.get("mask_path"), "status": "candidate"}
                    for r in corona_visual])],
            "geometry_members": [{"kind": "visual_component", "id": "SAM_0001", "bbox": disk["bbox"], "mask_path": "poster_all_layers_v1/sam_masks/SAM_0001.png", "status": "stable_sun_disk"},
                                 {"kind": "soft_or_fragmented_corona", "ids": corona["child_mask_nodes"], "status": "partial_boundary"}],
            "status": "SHADOW_CANDIDATE", "provenance": {"source": "DeepSeek OCR + STR + SAM candidate ledger", "production_modified": False},
        },
    ]
    for node in nodes:
        node.setdefault("keywords", [])
        node.setdefault("key_points", [])
        node.setdefault("discourse_role", "evidence")
        node.setdefault("embedding", None)
        node.setdefault("metadata", {})
    components = [
        {"component_id": "poster_structure:SCALE_CURVE_001", "kind": "measurement_system", "bbox": curve["bbox"], "asset_paths": ["poster_str_sam_v1/scale_curve_mask.png", "poster_str_sam_v1/scale_curve_skeleton.png"]},
        {"component_id": "COMPOSITE_SOLAR_CORONA_001", "kind": "visual_composite", "label_source": "STR_048", "child_component_ids": corona["child_mask_nodes"], "status": "partial_boundary"},
        *[{"component_id": r["id"], "kind": "mask_candidate", "bbox": r["bbox"], "asset_path": "poster_all_layers_v1/" + str(r.get("mask_path", "")), "predicted_iou": r.get("predicted_iou"), "stability_score": r.get("stability_score")} for r in corona_visual],
    ]
    edges = [
        {"source": nodes[1]["node_id"], "target": "poster_structure:SCALE_CURVE_001", "edge_type": "LOCATED_ON_SCALE", "status": "SHADOW_CANDIDATE", "confidence": 0.84, "rationale": "The corona label and its 3 million K value are adjacent to the 10^6 scale region and its leader-line geometry; verify visually before promotion."},
        {"source": "STR_048", "target": nodes[1]["node_id"], "edge_type": "LABELS", "status": "STRUCTURAL", "confidence": 0.98},
        {"source": "STR_049", "target": nodes[1]["node_id"], "edge_type": "VALUES", "status": "STRUCTURAL", "confidence": 0.98},
        {"source": "SAM_0001", "target": "COMPOSITE_SOLAR_CORONA_001", "edge_type": "PART_OF", "status": "STRUCTURAL_CANDIDATE", "confidence": 0.99},
    ]
    payload = {"schema_version": "poster_evidence_node_pilot_v1", "document_id": "cosmic_temperatures_POSTER", "nodes": nodes, "components": components, "edges": edges,
               "policy": {"claim_boundary": "independently citable statement or labelled visual", "mask_role": "geometry/provenance only", "production_modified": False}}
    (args.output / "evidence_nodes.jsonl").write_text("".join(json.dumps(n, ensure_ascii=False) + "\n" for n in nodes), encoding="utf-8")
    (args.output / "visual_components.json").write_text(json.dumps(components, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "edges.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in edges), encoding="utf-8")
    (args.output / "graph.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    image = Image.open(SOURCE).convert("RGB"); image.thumbnail((1400, 1400), Image.Resampling.LANCZOS); draw = ImageDraw.Draw(image)
    sx, sy = image.width / 5530, image.height / 8192
    for box, color, label in [(claim_bbox, "#e33b3b", "EV2 claim"), (curve["bbox"], "#2f9eea", "EV1 scale")]:
        x1, y1, x2, y2 = box; xy = (x1*sx, y1*sy, x2*sx, y2*sy); draw.rectangle(xy, outline=color, width=4); draw.text((xy[0]+3, xy[1]+3), label, fill=color, stroke_width=2, stroke_fill="black")
    image.save(args.output / "poster_overlay.jpg", quality=90)
    cards = []
    for n in nodes:
        cards.append("<section><h2>" + html.escape(n["node_id"]) + "</h2><p><b>" + html.escape(n["base_summary"]) + "</b></p><pre>" + html.escape(json.dumps(n, ensure_ascii=False, indent=2)) + "</pre></section>")
    page = "<!doctype html><meta charset=utf-8><title>Poster EvidenceNode pilot</title><style>body{font:15px system-ui;max-width:1500px;margin:20px auto;background:#eef2f5}section{background:#fff;padding:16px;margin:16px 0;border-radius:8px}img{max-width:100%}pre{white-space:pre-wrap;background:#18232c;color:#eef;padding:12px;overflow-wrap:anywhere}</style><h1>Poster EvidenceNode shadow pilot</h1><p>Red: labelled visual claim; blue: measurement-system geometry. Masks remain components/provenance, not standalone facts.</p><img src='poster_overlay.jpg'>" + "".join(cards) + "<h2>Edges</h2><pre>" + html.escape(json.dumps(edges, ensure_ascii=False, indent=2)) + "</pre>"
    (args.output / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({"nodes": len(nodes), "components": len(components), "edges": len(edges), "output": str(args.output)}))


if __name__ == "__main__": main()
