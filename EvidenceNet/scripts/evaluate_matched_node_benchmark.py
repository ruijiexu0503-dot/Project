#!/usr/bin/env python3
"""Evaluate source-addressed node roles and bindings on a small frozen review."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "EvidenceNet/output/member_asset_evidence_pipeline_horeka2"
NEW = ROOT / "EvidenceNet/output/matched_node_benchmark_20261006"
REVIEW = ROOT / "EvidenceNet/config/reviews/node_generation/matched_node_benchmark_review_20261006.json"
ARMS = {"Qwen3.5-9B": NEW / "Qwen3.5-9B",
        "Qwen3.5-35B-A3B": BASE / "Qwen3.5-35B-A3B",
        "Qwen3.5-122B-A10B": BASE / "Qwen3.5-122B-A10B",
        "Qwen3.6-35B-A3B": NEW / "Qwen3.6-35B-A3B",
        "embedding_geometry": NEW / "embedding_geometry"}


def read(path): return json.loads(path.read_text())


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate():
    review = read(REVIEW); rows = []
    for task, gold in review["pages"].items():
        source = BASE / "Qwen3.5-35B-A3B" / task
        if sha(source / "original.png") != gold["source_image_sha256"]:
            raise ValueError(f"Reviewed source image changed: {task}")
        rep = read(source / "input_representation.json")
        known_atoms = {a["atom_id"] for a in rep["atoms"]}
        known_visuals = {v["visual_bundle_id"] for v in rep["visual_bundles"]}
        if (set(gold["structural_atom_ids"]) | set(gold["body_atom_ids"])
                | {a for _, a in gold["visual_caption_pairs"]}) != known_atoms:
            raise ValueError(f"Review does not cover every atom: {task}")
        if {v for v, _ in gold["visual_caption_pairs"]} - known_visuals:
            raise ValueError(f"Unknown reviewed visual: {task}")
        for arm, root in ARMS.items():
            target = root / task
            summary_path = target / "run_summary.json"
            if not summary_path.exists():
                rows.append({"task": task, "arm": arm, "status": "NOT_RUN"}); continue
            summary = read(summary_path)
            nodes_path = target / "evidence_nodes.jsonl"
            if not nodes_path.exists():
                rows.append({"task": task, "arm": arm, "status": summary.get("status", "NO_NODES"),
                             "validation_passed": False}); continue
            nodes = [json.loads(line) for line in nodes_path.read_text().splitlines()]
            occurrences = Counter(a for n in nodes for a in n.get("source_atom_ids", []))
            visual_occurrences = Counter(v for n in nodes for v in n.get("source_visual_bundle_ids", []))
            structural_leaks = sorted(a for a in gold["structural_atom_ids"] if occurrences[a])
            body_coverage_errors = {a: occurrences[a] for a in gold["body_atom_ids"] if occurrences[a] != 1}
            visual_coverage_errors = {v: visual_occurrences[v] for v in known_visuals if visual_occurrences[v] != 1}
            required = {tuple(sorted(pair)) for pair in gold["required_continuation_pairs"]}
            grouped = {pair for n in nodes for pair in combinations(sorted(
                set(n.get("source_atom_ids", [])) & set(gold["body_atom_ids"])), 2)}
            overmerged = sorted(grouped - required)
            missed_continuations = sorted(required - grouped)
            correct_pairs = []
            for vid, aid in gold["visual_caption_pairs"]:
                if any(vid in n.get("source_visual_bundle_ids", []) and
                       aid in n.get("source_atom_ids", []) for n in nodes):
                    correct_pairs.append([vid, aid])
            wrong_caption_pairs = []
            caption_ids = {a for _, a in gold["visual_caption_pairs"]}
            for n in nodes:
                for vid in n.get("source_visual_bundle_ids", []):
                    for aid in set(n.get("source_atom_ids", [])) & caption_ids:
                        if [vid, aid] not in gold["visual_caption_pairs"]:
                            wrong_caption_pairs.append([vid, aid])
            result = {"task": task, "arm": arm, "status": summary.get("status", "complete"),
                      "validation_passed": summary.get("valid", summary.get("valid_coverage")),
                      "validation_kind": "source_coverage_only" if arm == "embedding_geometry" else "Qwen_assembly_schema",
                      "node_count": len(nodes), "reviewed_structural_leaks": structural_leaks,
                      "reviewed_body_coverage_errors": body_coverage_errors,
                      "reviewed_visual_coverage_errors": visual_coverage_errors,
                      "reviewed_body_overmerge_pairs": overmerged,
                      "reviewed_missed_continuations": missed_continuations,
                      "caption_pairs_correct": correct_pairs,
                      "caption_pairs_expected": gold["visual_caption_pairs"],
                      "wrong_caption_pairs": wrong_caption_pairs,
                      "input_source_image_sha256": gold["source_image_sha256"]}
            rows.append(result)
    aggregate = {}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        complete = [r for r in subset if r["status"] == "complete"]
        aggregate[arm] = {"pages_with_nodes": len(complete),
                          "validation_passed_pages": sum(bool(r["validation_passed"]) for r in complete),
                          "reviewed_structural_leaks": sum(len(r["reviewed_structural_leaks"]) for r in complete),
                          "reviewed_body_coverage_errors": sum(len(r["reviewed_body_coverage_errors"]) for r in complete),
                          "reviewed_body_overmerge_pairs": sum(len(r["reviewed_body_overmerge_pairs"]) for r in complete),
                          "reviewed_missed_continuations": sum(len(r["reviewed_missed_continuations"]) for r in complete),
                          "caption_pairs_correct": sum(len(r["caption_pairs_correct"]) for r in complete),
                          "caption_pairs_available": sum(len(r["caption_pairs_expected"]) for r in complete)}
    result = {"review": str(REVIEW), "independent_human_ground_truth": False,
              "method": "same reviewed source atoms and visuals; only listed source roles, caption pairs, continuations and paragraph overmerges scored; Qwen assembly schema validity and embedding source coverage validity are different checks",
              "production_modified": False, "aggregate": aggregate, "pages": rows}
    output = NEW / "evaluation.json"; output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__": evaluate()
