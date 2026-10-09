#!/usr/bin/env python3
"""Compare mixed-material baseline and hybrid outputs against frozen source review."""
from __future__ import annotations

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "EvidenceNet/config/reviews/node_generation/hybrid_mixed_material_review_20261007.json"
DEFAULT_RUN = ROOT / "EvidenceNet/output/hybrid_mixed_material_run_20261007"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def nodes(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score(task: str, label: dict, root: Path, prepared: Path):
    rep = read(prepared / task / "input_representation.json")
    atom_types = {a["atom_id"]: a["atom_type"] for a in rep["atoms"]}
    rows = nodes(root / task / "evidence_nodes.jsonl")
    ownership = {aid: n["node_id"] for n in rows for aid in n["source_atom_ids"]}
    visual_ownership = {vid: n for n in rows for vid in n["source_visual_bundle_ids"]}
    positive = {frozenset(pair) for pair in label["required_continuation_pairs"]}
    # An exact continuation chain also licenses its transitive within-sentence pairs.
    parent = {aid: aid for aid, kind in atom_types.items() if kind == "text"}
    def find(a):
        while parent[a] != a:
            a = parent[a]
        return a
    for a, b in label["required_continuation_pairs"]:
        parent[find(b)] = find(a)
    observed = {frozenset((a, b)) for n in rows
                for a, b in combinations([a for a in n["source_atom_ids"] if a in parent], 2)}
    wrong = sorted([sorted(pair) for pair in observed if len({find(a) for a in pair}) != 1])
    required = [{"pair": pair, "joined": ownership.get(pair[0]) is not None
                 and ownership.get(pair[0]) == ownership.get(pair[1])}
                for pair in label["required_continuation_pairs"]]
    caption = [{"pair": pair, "attached": pair[0] in visual_ownership
                and pair[1] in visual_ownership[pair[0]]["source_atom_ids"]}
               for pair in label["clear_visual_caption_pairs"]]
    context = [{"pair": pair, "attached": pair[0] in visual_ownership
                and pair[1] in visual_ownership[pair[0]]["source_atom_ids"]}
               for pair in label.get("visual_context_pairs", [])]
    table = [{"atom_id": aid, "evidence_node": ownership.get(aid)}
             for aid in label.get("table_atom_ids", [])]
    table_caption = [{"atom_id": aid, "evidence_node": ownership.get(aid)}
                     for aid in label.get("table_caption_atom_ids", [])]
    structural_leaks = sorted(set(label["structural_atom_ids"]) & set(ownership))
    missing_visuals = sorted(set(label.get("required_visual_ids", [])) - set(visual_ownership))
    summary = read(root / task / "run_summary.json")
    return {"task": task, "material": label["material"], "valid_coverage": summary["valid_coverage"],
            "nodes": len(rows), "structural_leaks": structural_leaks,
            "wrong_text_merges": wrong, "required_continuations": required,
            "clear_captions": caption, "visual_context": context,
            "table_atoms": table, "table_captions": table_caption,
            "missing_required_visuals": missing_visuals,
            "caption_assignments": summary["caption_assignments"]}


def totals(pages):
    return {"pages": len(pages), "source_coverage_passed": sum(p["valid_coverage"] for p in pages),
            "structural_leaks": sum(len(p["structural_leaks"]) for p in pages),
            "wrong_text_merges": sum(len(p["wrong_text_merges"]) for p in pages),
            "required_continuations_joined": sum(x["joined"] for p in pages for x in p["required_continuations"]),
            "required_continuations": sum(len(p["required_continuations"]) for p in pages),
            "clear_captions_attached": sum(x["attached"] for p in pages for x in p["clear_captions"]),
            "clear_captions": sum(len(p["clear_captions"]) for p in pages),
            "slide_visual_context_attached": sum(x["attached"] for p in pages for x in p["visual_context"]),
            "slide_visual_context": sum(len(p["visual_context"]) for p in pages),
            "tables_in_evidence": sum(bool(x["evidence_node"]) for p in pages for x in p["table_atoms"]),
            "table_atoms": sum(len(p["table_atoms"]) for p in pages),
            "required_visuals_present": sum(len(p.get("missing_required_visuals", [])) == 0 for p in pages
                                            if p["material"] == "image_only_poster")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--stress-run", type=Path,
                        help="Evaluate the frozen seven pages inside the 49-page v7 stress run")
    args = parser.parse_args()
    labels = read(args.labels)
    prepared = (ROOT / labels["prepared_manifest"]).parent
    stress_prepared = ROOT / "EvidenceNet/output/hybrid_49page_stress_prepared_20261007"
    batch_by_task = {}
    if args.stress_run:
        manifest = read(stress_prepared / "manifest.json")
        batch_by_task = {task: i for i, batch in enumerate(manifest["batches"]) for task in batch}
        for task in labels["pages"]:
            old = read(prepared / task / "input_representation.json")
            new = read(stress_prepared / "shard_1" / task / "input_representation.json")
            def core(rep):
                return ([(a["atom_id"], a["atom_type"], a["text_fragments"])
                         for a in rep["atoms"]],
                        [(v["visual_bundle_id"], v["bbox"]) for v in rep["visual_bundles"]])
            if core(old) != core(new):
                raise ValueError(f"Frozen label input changed: {task}")
            old_image = prepared / task / "original.png"
            new_image = stress_prepared / "shard_1" / task / "original.png"
            if hashlib.sha256(old_image.read_bytes()).digest() != hashlib.sha256(new_image.read_bytes()).digest():
                raise ValueError(f"Frozen source image changed: {task}")
        prepared = stress_prepared / "shard_1"
    output = {}
    for arm in ("embedding_geometry", "hybrid"):
        if args.stress_run:
            pages = [score("shard_1/" + task, label,
                           args.stress_run / f"batch_{batch_by_task['shard_1/' + task]}" / arm,
                           stress_prepared)
                     for task, label in labels["pages"].items()]
        else:
            pages = [score(task, label, args.run / arm, prepared)
                     for task, label in labels["pages"].items()]
        output[arm] = {"totals": totals(pages), "pages": pages}
    output["review_file"] = str(args.labels.resolve())
    output["independent_human_ground_truth"] = labels["independent_human_ground_truth"]
    output["production_modified"] = False
    output["frozen_input_matches_original"] = bool(args.stress_run)
    path = ((args.stress_run / "frozen7_evaluation.json") if args.stress_run
            else (args.run / "mixed_material_evaluation.json"))
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({arm: output[arm]["totals"] for arm in ("embedding_geometry", "hybrid")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
