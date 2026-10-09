#!/usr/bin/env python3
"""Training-free EvidenceNode assembly from frozen atoms, embedding, and geometry."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))
from evidence_graph.llm_client import create_llm
from bounded_geometry import boxes, pair_hint
from run_node_embedding_geometry_pilot import SYSTEM, PROMPT, embed
from run_matched_qwen_node_benchmark import SOURCE, TASKS

BASELINE_TASKS = TASKS + ("gw150914_detection/page_0002",)
REVISION = False
GEOMETRY_ONLY = False


def read(path: Path): return json.loads(path.read_text())


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()


def structural(atom):
    role = atom.get("layout_role", "")
    text = atom.get("text_preview", "").strip()
    return (atom["atom_type"] in {"heading", "foot", "header", "furniture"}
            or role in {"overlay_heading", "visual_internal_label", "header", "foot", "footer", "page_furniture"}
            or text.lower().startswith("by ") and len(text) < 100
            or role == "overlay_prose_or_caption" and "DLRmaGazine" in text and len(text) < 110)


def text_of(atom): return "\n".join(f["text"] for f in atom["text_fragments"])


def make_crops(out: Path, tasks):
    result = []
    for task in tasks:
        source = SOURCE / task; rep = read(source / "input_representation.json")
        with Image.open(source / "original.png") as page:
            for visual in rep["visual_bundles"]:
                b = visual["bbox"]; target = out / task / "crops" / (visual["visual_bundle_id"] + ".png")
                target.parent.mkdir(parents=True, exist_ok=True)
                page.crop(tuple(map(int, b))).save(target)
                result.append((task, visual["visual_bundle_id"], target))
    return result


def describe(out: Path, model: Path, tasks):
    crops = make_crops(out, tasks); path = out / "visual_descriptions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    existing = {}
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line); existing[(row["task"], row["visual_id"])] = row
    pending = [(task, vid, crop) for task, vid, crop in crops
               if (task, vid) not in existing or existing[(task, vid)]["crop_sha256"] != sha(crop)
               or existing[(task, vid)].get("model") != str(model.resolve())]
    if not pending: return
    llm = create_llm({"provider": "transformers", "model": str(model.resolve()),
                      "dtype": "bfloat16", "device_map": "auto", "require_cuda": True,
                      "enable_thinking": False})
    for task, vid, crop in pending:
        response = llm.generate_raw_with_images(SYSTEM, PROMPT, [str(crop)], 180)
        row = {"task": task, "visual_id": vid, "crop": str(crop), "crop_sha256": sha(crop),
               "description": response.raw.strip(), "model": str(model.resolve()),
               "prompt": PROMPT, "system": SYSTEM, "timestamp": response.timestamp}
        if not row["description"]: raise ValueError(f"Empty crop description: {task}/{vid}")
        with path.open("a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("described", task, vid, row["description"][:100].replace("\n", " "), flush=True)


def assemble(out: Path, embedding_model: Path, tasks):
    import numpy as np
    descriptions = {}
    for line in (out / "visual_descriptions.jsonl").read_text().splitlines():
        row = json.loads(line); descriptions[(row["task"], row["visual_id"])] = row
    for task in tasks:
        source = SOURCE / task; rep = read(source / "input_representation.json")
        atoms = rep["atoms"]; captions = [a for a in atoms if a["atom_type"] == "caption"]
        body = [a for a in atoms if a["atom_type"] == "text" and not structural(a)]
        visuals = rep["visual_bundles"]
        for v in visuals:
            d = descriptions[(task, v["visual_bundle_id"])]
            if d["crop_sha256"] != sha(Path(d["crop"])): raise ValueError("stale crop")
        query_texts = ["Instruct: Find the caption or text describing this visual.\nQuery: " +
                       descriptions[(task, v["visual_bundle_id"])]["description"] for v in visuals]
        atom_texts = [text_of(a) for a in body + captions]
        vectors = (np.zeros((len(query_texts + atom_texts), 1)) if GEOMETRY_ONLY
                   else embed(query_texts + atom_texts, embedding_model))
        nv = len(visuals); nb = len(body)
        atom_vectors = {a["atom_id"]: vectors[nv+i] for i, a in enumerate(body+captions)}
        with Image.open(source / "original.png") as page: size = page.size
        assignments = {}; candidates = []
        for vi, visual in enumerate(visuals):
            for cap in captions:
                if REVISION and any(a['atom_type'] == 'table' for a in atoms) and re.match(r'^\s*table\b', text_of(cap), re.I):
                    continue
                obstacles = [b for a in atoms if a["atom_id"] != cap["atom_id"] for b in boxes(a)]
                geo = min(pair_hint(vb, cb, obstacles, size)["score"]
                          for vb in boxes(visual) for cb in boxes(cap))
                dense = float(np.dot(vectors[vi], atom_vectors[cap["atom_id"]]))
                candidates.append({"visual_id": visual["visual_bundle_id"], "caption_id": cap["atom_id"],
                                   "geometry_score": geo, "embedding_cosine": dense})
        # Rank sums are fixed ahead of review; only parser-typed captions are eligible.
        for visual in visuals:
            rows = [r for r in candidates if r["visual_id"] == visual["visual_bundle_id"]]
            if not rows: continue
            gr = {r["caption_id"]: i for i, r in enumerate(sorted(rows, key=lambda x: (x["geometry_score"], x["caption_id"])))}
            dr = {r["caption_id"]: i for i, r in enumerate(sorted(rows, key=lambda x: (-x["embedding_cosine"], x["caption_id"])))}
            rows.sort(key=lambda x: (gr[x["caption_id"]] + (0 if GEOMETRY_ONLY else dr[x["caption_id"]]),
                                     gr[x["caption_id"]], x["caption_id"]))
            chosen = next((r for r in rows if r["caption_id"] not in assignments.values()
                           and r["geometry_score"] <= 0.35), None)
            if chosen: assignments[visual["visual_bundle_id"]] = chosen["caption_id"]
        # Text nodes start from parser atoms. Merge only an adjacent same-sentence
        # continuation with close geometry and strong embedding agreement.
        body.sort(key=lambda a: a["deepseek_order"])
        groups = [[a] for a in body]
        merged = []
        for group in groups:
            if merged and not REVISION:
                left = merged[-1][-1]; right = group[0]
                lt = text_of(left).strip(); rt = text_of(right).strip()
                if boxes(left) and boxes(right):
                    hint = min(pair_hint(x, y, [], size)["score"] for x in boxes(left) for y in boxes(right))
                    cosine = float(np.dot(atom_vectors[left["atom_id"]], atom_vectors[right["atom_id"]]))
                    if (hint <= 0.045 and cosine >= 0.78 and lt and lt[-1] not in ".!?;:"
                            and rt and rt[0].islower()):
                        merged[-1].extend(group); continue
            merged.append(group)
        output_nodes = []
        def node(group, visual=None):
            atoms_for_node = group
            component = [dict(c, semantic_parent_visual_id=visual["visual_bundle_id"])
                         for c in visual.get("native_components", [])] if visual else []
            return {"node_id": f"{rep['document_id']}_{rep['page']}_EG_{len(output_nodes)+1:03d}",
                    "node_type": "evidence", "status": "SHADOW_CANDIDATE", "unit_type":
                    "COMPOSITE" if visual and group else "VISUAL" if visual else "TEXT",
                    "source_atom_ids": [a["atom_id"] for a in atoms_for_node],
                    "source_fragment_ids": [f["fragment_id"] for a in atoms_for_node for f in a["text_fragments"]],
                    "source_visual_bundle_ids": [visual["visual_bundle_id"]] if visual else [],
                    "plain_text": "\n".join(text_of(a) for a in atoms_for_node),
                    "visual_description": descriptions[(task, visual["visual_bundle_id"])]["description"] if visual else None,
                    "geometry_members": [dict(g, source_atom_id=a["atom_id"])
                                         for a in atoms_for_node for g in a.get("geometry_members", [])]
                    + ([dict(g, source_visual_bundle_id=visual["visual_bundle_id"])
                        for g in visual.get("geometry_members", [])] if visual else []),
                    "native_visual_components": component, "production_modified": False}
        for group in merged: output_nodes.append(node(group))
        for visual in visuals:
            cap = next((a for a in captions if a["atom_id"] == assignments.get(visual["visual_bundle_id"])), None)
            output_nodes.append(node([cap] if cap else [], visual))
        tables = [a for a in atoms if a['atom_type'] == 'table'] if REVISION else []
        for table in tables:
            table_node = node([table])
            table_node['unit_type'] = 'TABLE'
            output_nodes.append(table_node)
        # Preserve unmatched captions as addressable evidence; do not guess attachment.
        if REVISION:
            for cap in captions:
                if cap['atom_id'] not in assignments.values():
                    caption_node = node([cap])
                    caption_node.update(unit_type='CAPTION', attachment_status='UNRESOLVED')
                    output_nodes.append(caption_node)
            for item in output_nodes:
                item['visual_description_status'] = 'UNVERIFIED_RETRIEVAL_HINT'
                item['node_policy'] = 'bounded-v2'
                item['scoring_mode'] = 'geometry' if GEOMETRY_ONLY else 'embedding_geometry'
        structural_atoms = [a for a in atoms if a not in body and a not in captions and a not in tables]
        unassigned_captions = [a for a in captions if a["atom_id"] not in assignments.values()]
        if REVISION: unassigned_captions = []
        target = out / task; target.mkdir(parents=True, exist_ok=True)
        (target / "evidence_nodes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in output_nodes))
        write(target / "structural_and_unresolved.json", {
            "structural_atom_ids": [a["atom_id"] for a in structural_atoms],
            "unassigned_caption_atom_ids": [a["atom_id"] for a in unassigned_captions]})
        write(target / "caption_candidate_scores.json", candidates)
        all_fragments = {f["fragment_id"] for a in atoms for f in a["text_fragments"]}
        covered = [f for n in output_nodes for f in n["source_fragment_ids"]]
        covered += [f["fragment_id"] for a in structural_atoms + unassigned_captions for f in a["text_fragments"]]
        components = {c["member_id"] for v in visuals for c in v.get("native_components", [])}
        node_components = {c["member_id"] for n in output_nodes for c in n["native_visual_components"]}
        summary = {"task": task, "status": "complete", "valid_coverage": set(covered)==all_fragments
                   and len(covered)==len(all_fragments) and components==node_components,
                   "evidence_nodes": len(output_nodes), "visual_nodes": len(visuals),
                   "caption_assignments": assignments, "text_fragments": len(all_fragments),
                   "scoring_mode": "geometry" if GEOMETRY_ONLY else "embedding_geometry",
                   "node_policy": "bounded-v2" if REVISION else "legacy",
                   "native_component_loss": len(components-node_components),
                   "input_hashes": {"input_representation": sha(source/"input_representation.json"),
                                    "source_image": sha(source/"original.png")},
                   "production_modified": False}
        write(target / "run_summary.json", summary)
        print(json.dumps({k: summary[k] for k in ("task", "valid_coverage", "evidence_nodes", "caption_assignments")}), flush=True)
    write(out / "summary.json", {"method": "frozen parser atoms + Qwen crop-only descriptions + text embedding + geometry; no Qwen node assembly",
                                  "embedding_model": str(embedding_model.resolve()),
                                  "pages": [read(out/task/"run_summary.json") for task in tasks
                                            if (out/task/"run_summary.json").exists()],
                                  "production_modified": False})


def main():
    global SOURCE
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("describe", "assemble"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--source-root", type=Path, default=SOURCE)
    p.add_argument("--tasks", nargs="+", default=list(TASKS))
    args = p.parse_args()
    SOURCE = args.source_root.resolve()
    for task in args.tasks:
        if not (SOURCE/task/"input_representation.json").exists():
            raise FileNotFoundError(SOURCE/task/"input_representation.json")
    (describe if args.stage == "describe" else assemble)(args.output, args.model, tuple(args.tasks))


if __name__ == "__main__": main()
