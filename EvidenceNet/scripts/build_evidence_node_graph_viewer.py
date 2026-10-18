#!/usr/bin/env python3
"""Build an interactive all-page EvidenceNode composition and link browser."""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import re

from PIL import Image
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from viewer_article_membership import attach


ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT / "EvidenceNet/output/hybrid_49page_stress_prepared_20261007"
SEGMENTATION_ROOT = ROOT / "EvidenceNet/output/evidence_graph"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def bbox_union(boxes):
    boxes = [b for b in boxes if isinstance(b, list) and len(b) == 4]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "item"


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def load_segmentation(document: str):
    directory = SEGMENTATION_ROOT / document
    nodes_path = directory / "evidence_nodes.jsonl"
    assignments_path = directory / "hybrid_content_unit_assignments.jsonl"
    if not nodes_path.exists() or not assignments_path.exists():
        return None
    nodes = jsonl(nodes_path)
    assignments = {row["node_id"]: row["content_unit_id"]
                   for row in jsonl(assignments_path)
                   if row.get("node_id") and row.get("content_unit_id")}
    return {"nodes": nodes, "assignments": assignments}


def map_segmentation(result, document, page):
    segmentation = load_segmentation(document)
    if not segmentation:
        return {"available": False, "method": "hybrid_content_unit_assignments_not_found",
                "mapped_nodes": 0, "unmapped_nodes": len(result), "units": []}
    # The legacy segmentation run and the HY viewer use different physical page
    # labels, so page filtering would discard valid matches. Text matching is
    # constrained to the same document and records its score for review.
    candidates = segmentation["nodes"]
    mapped = 0
    units = {}
    for node in result:
        text = normalize_text(node.get("text"))
        scored = []
        for candidate in candidates:
            candidate_text = normalize_text(candidate.get("plain_text"))
            if not text or not candidate_text:
                continue
            score = SequenceMatcher(None, text, candidate_text).ratio()
            if text in candidate_text or candidate_text in text:
                score = max(score, 0.9)
            scored.append((score, candidate))
        if not scored:
            continue
        score, candidate = max(scored, key=lambda item: item[0])
        unit_id = segmentation["assignments"].get(candidate["node_id"])
        if score < 0.35 or not unit_id:
            continue
        node["article_unit_id"] = unit_id
        node["article_mapping_score"] = round(score, 3)
        node["article_source_node_id"] = candidate["node_id"]
        mapped += 1
        units.setdefault(unit_id, {"id": unit_id, "node_ids": [], "scores": []})
        units[unit_id]["node_ids"].append(node["id"])
        units[unit_id]["scores"].append(score)
    unit_rows = []
    for unit in units.values():
        unit_rows.append({
            "id": unit["id"],
            "node_ids": unit["node_ids"],
            "node_count": len(unit["node_ids"]),
            "min_mapping_score": round(min(unit["scores"]), 3),
            "avg_mapping_score": round(sum(unit["scores"]) / len(unit["scores"]), 3),
        })
    unit_rows.sort(key=lambda item: item["id"])
    return {
        "available": True,
        "method": "hybrid_content_unit_assignments_document_text_match",
        "mapped_nodes": mapped,
        "unmapped_nodes": len(result) - mapped,
        "units": unit_rows,
    }


def build_page(node_path: Path, output: Path):
    marker = "/hybrid/"
    task = str(node_path.parent).split(marker, 1)[1]
    rep = read(PREPARED / task / "input_representation.json")
    atoms = {a["atom_id"]: a for a in rep["atoms"]}
    visuals = {v["visual_bundle_id"]: v for v in rep["visual_bundles"]}
    nodes = jsonl(node_path)
    sidecar = read(node_path.parent / "structural_and_unresolved.json")
    summary = read(node_path.parent / "run_summary.json")
    page_image = Image.open(PREPARED / task / "original.png").convert("RGB")
    page_rel = "assets/pages/" + safe_name(task) + ".jpg"
    page_asset = output / page_rel
    page_asset.parent.mkdir(parents=True, exist_ok=True)
    page_image.save(page_asset, quality=90)
    result = []
    for node in nodes:
        members = []
        member_boxes = []
        orders = []
        for atom_id in node.get("source_atom_ids", []):
            atom = atoms[atom_id]
            boxes = [g.get("bbox") for g in atom.get("geometry_members", []) if g.get("bbox")]
            member_boxes += boxes
            orders.append(atom.get("deepseek_order", 999999))
            members.append({"kind": "atom", "id": atom_id, "type": atom.get("atom_type"),
                            "role": atom.get("layout_role"), "order": atom.get("deepseek_order"),
                            "text": "\n".join(f.get("text", "") for f in atom.get("text_fragments", [])),
                            "semantic_text": "\n".join(f.get("semantic_text", f.get("text", ""))
                                                       for f in atom.get("text_fragments", [])),
                            "boxes": boxes})
        visual_rows = []
        for visual_id in node.get("source_visual_bundle_ids", []):
            visual = visuals[visual_id]
            boxes = [g.get("bbox") for g in visual.get("geometry_members", []) if g.get("bbox")]
            if visual.get("bbox"): boxes.append(visual["bbox"])
            member_boxes += boxes
            crop_rel = None
            crop_box = bbox_union(boxes)
            if crop_box:
                x1, y1, x2, y2 = crop_box
                x1, y1 = max(0, int(x1)), max(0, int(y1))
                x2, y2 = min(page_image.width, int(x2 + 0.999)), min(page_image.height, int(y2 + 0.999))
                if x2 > x1 and y2 > y1:
                    crop_rel = "assets/" + safe_name(task) + "/" + safe_name(visual_id) + ".jpg"
                    crop_path = output / crop_rel
                    crop_path.parent.mkdir(parents=True, exist_ok=True)
                    page_image.crop((x1, y1, x2, y2)).save(crop_path, quality=92)
            visual_rows.append({"kind": "visual", "id": visual_id, "type": "visual",
                                "role": visual.get("visual_role"), "text": node.get("visual_description") or "",
                                "description_status": node.get("visual_description_status"), "boxes": boxes,
                                "crop": crop_rel, "crop_source": "original_page_bbox",
                                "native_components": [c.get("member_id") for c in visual.get("native_components", [])]})
        members += visual_rows
        result.append({"id": node["node_id"], "short": node["node_id"].rsplit("_", 1)[-1],
                       "unit_type": node.get("unit_type"), "status": node.get("status"),
                       "text": node.get("plain_text") or "", "members": members,
                       "semantic_text": node.get("semantic_text", node.get("plain_text") or ""),
                       "bbox": bbox_union(member_boxes), "min_order": min(orders) if orders else None,
                       "merged": len(node.get("source_atom_ids", [])) > 1,
                       "atom_count": len(node.get("source_atom_ids", [])),
                       "visual_count": len(node.get("source_visual_bundle_ids", []))})
        result[-1]['source_fragment_ids'] = node.get('source_fragment_ids', [])
        result[-1]['source_visual_bundle_ids'] = node.get('source_visual_bundle_ids', [])
    titles = []
    for atom in rep['atoms']:
        if atom['atom_type'] != 'heading' and atom.get('layout_role') not in {'overlay_heading', 'title', 'section_heading'}:
            continue
        boxes = [g['bbox'] for g in atom.get('geometry_members', []) if g.get('bbox')]
        text = '\n'.join(f['text'] for f in atom['text_fragments'])
        semantic_text = '\n'.join(f.get('semantic_text', f['text']) for f in atom['text_fragments'])
        titles.append({'id': 'TITLE::'+atom['atom_id'], 'short': atom['atom_id'],
                       'unit_type': 'STRUCTURAL_TITLE', 'text': text, 'semantic_text': semantic_text,
                       'bbox': bbox_union(boxes),
                       'min_order': atom.get('deepseek_order'), 'atom_count': 1, 'visual_count': 0,
                       'source_fragment_ids': [f['fragment_id'] for f in atom['text_fragments']],
                       'members': [{'id':atom['atom_id'], 'kind':'atom', 'type':'heading',
                                    'text':text, 'semantic_text':semantic_text,
                                    'role':atom.get('layout_role'), 'boxes':boxes}]})
    text_nodes = sorted((n for n in result if n["min_order"] is not None), key=lambda n: (n["min_order"], n["id"]))
    candidate_edges = [{"source": a["id"], "target": b["id"], "type": "PROVISIONAL_READING_ORDER",
                        "status": "DERIVED_FOR_VISUALIZATION_NOT_PERSISTED"}
                       for a, b in zip(text_nodes, text_nodes[1:])]
    segmentation = attach(rep, result, titles, task)
    candidate_edges = [e for e in candidate_edges if any(
        e['source'] in g['node_ids'] and e['target'] in g['node_ids']
        for g in segmentation.get('units', []))]
    return {"task": task, "document": rep.get("document_id"), "page": rep.get("page"),
            "image": page_rel,
            "nodes": result, "candidate_edges": candidate_edges,
            "segmentation": segmentation,
            "titles": titles,
            "actual_node_edges": [], "summary": summary,
            "excluded": {"structural": sidecar.get("structural_atom_ids", []),
                         "unresolved_captions": sidecar.get("unassigned_caption_atom_ids", [])},
            "edge_contract": {"composition": "ACTUAL", "candidate_reading": "NOT_PERSISTED",
                              "cross_page": "NOT_INTEGRATED", "semantic": "NOT_INTEGRATED"}}


def main():
    global SEGMENTATION_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segmentation-root", type=Path, default=SEGMENTATION_ROOT)
    args = parser.parse_args()
    SEGMENTATION_ROOT = args.segmentation_root
    paths = sorted(args.source.glob("batch_*/hybrid/**/evidence_nodes.jsonl"))
    pages = [build_page(path, args.output) for path in paths]
    pages.sort(key=lambda p: (p["document"], p["page"], p["task"]))
    payload = {"generated_from": str(args.source), "pages": pages,
               "totals": {"pages": len(pages), "nodes": sum(len(p["nodes"]) for p in pages),
                          "actual_node_edges": 0,
                          "provisional_reading_edges": sum(len(p["candidate_edges"]) for p in pages)}}
    template = (Path(__file__).with_name("evidence_node_graph_viewer_template.html").read_text(encoding="utf-8"))
    html = template.replace("/*__GRAPH_DATA__*/null", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "index.html").write_text(html, encoding="utf-8")
    (args.output / "graph_data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
