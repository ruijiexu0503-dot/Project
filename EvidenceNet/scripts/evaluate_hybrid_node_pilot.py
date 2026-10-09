#!/usr/bin/env python3
"""Frozen four-page hybrid gate; compare source roles, continuations, captions."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "EvidenceNet/config/reviews/node_generation/hybrid_node_review_20261007.json"
SOURCE = ROOT / "EvidenceNet/output/member_asset_evidence_pipeline_horeka2/Qwen3.5-35B-A3B"
BASELINE = ROOT / "EvidenceNet/output/matched_node_benchmark_20261006/embedding_geometry"
HYBRID = ROOT / "EvidenceNet/output/hybrid_node_pilot_20261007"


def read(path): return json.loads(path.read_text())


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def nodes(path): return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def assess(task, gold, arm, root):
    p = root/task; summary = read(p/"run_summary.json"); values = nodes(p/"evidence_nodes.jsonl")
    in_nodes = Counter(a for n in values for a in n["source_atom_ids"])
    body = set(gold["body_atom_ids"])
    required = {tuple(sorted(pair)) for pair in gold["required_continuation_pairs"]}
    grouped = {pair for n in values for pair in combinations(sorted(set(n["source_atom_ids"]) & body), 2)}
    captions = [[v, a] for v, a in gold["visual_caption_pairs"] if any(
        v in n["source_visual_bundle_ids"] and a in n["source_atom_ids"] for n in values)]
    source = SOURCE/task; rep = read(source/"input_representation.json")
    fragment_ids = {f["fragment_id"] for a in rep["atoms"] for f in a["text_fragments"]}
    in_node_frags = [f for n in values for f in n.get("source_fragment_ids", [])]
    if arm == "Qwen3.5-35B-A3B":
        source_coverage = summary["valid"]
    else:
        sidecar = read(p/"structural_and_unresolved.json")
        ids = set(sidecar["structural_atom_ids"]) | set(sidecar["unassigned_caption_atom_ids"])
        by_id = {a["atom_id"]: a for a in rep["atoms"]}
        all_frags = in_node_frags + [f["fragment_id"] for aid in ids for f in by_id[aid]["text_fragments"]]
        source_coverage = Counter(all_frags) == Counter(fragment_ids) and summary["valid_coverage"]
    return {"task": task, "arm": arm, "validation_passed": summary.get("valid", summary.get("valid_coverage")),
            "source_coverage": bool(source_coverage), "node_count": len(values),
            "structural_leaks": sorted(a for a in gold["structural_atom_ids"] if in_nodes[a]),
            "body_coverage_errors": {a: in_nodes[a] for a in body if in_nodes[a] != 1},
            "wrong_body_merges": sorted(grouped-required),
            "missed_continuations": sorted(required-grouped),
            "correct_caption_pairs": captions,
            "expected_caption_pairs": gold["visual_caption_pairs"],
            "native_component_loss": summary.get("native_component_loss")}


def evaluate():
    cfg = read(REVIEW)
    old = read(ROOT/cfg["development_review"])["pages"]
    review = {**old, **cfg["holdout_pages"]}
    arms = {"embedding_geometry": BASELINE, "hybrid": HYBRID, "Qwen3.5-35B-A3B": SOURCE}
    rows = []
    for task, gold in review.items():
        source = SOURCE/task
        if sha(source/"original.png") != gold["source_image_sha256"]:
            raise ValueError(f"Changed source image: {task}")
        for arm, root in arms.items(): rows.append(assess(task, gold, arm, root))
    paired = {(r["task"],r["arm"]):r for r in rows}
    decision_audit = []
    for task, gold in review.items():
        c = read(HYBRID/task/"candidates.json"); d = read(HYBRID/task/"decisions.json")
        expected = {tuple(sorted(pair)) for pair in gold["required_continuation_pairs"]}
        by_pair = {r["pair_id"]:r for r in c["pairs"]}
        false_positive = []; false_negative = []
        for item in d["pairs"]:
            candidate = by_pair[item["pair_id"]]
            pair = tuple(sorted([candidate["left_atom_id"],candidate["right_atom_id"]]))
            if item["decision"] == "CONTINUATION" and pair not in expected: false_positive.append(pair)
            if item["decision"] != "CONTINUATION" and pair in expected: false_negative.append(pair)
        decision_audit.append({"task":task,"decision_valid":d["valid"],
                               "false_positive_continuations":false_positive,
                               "false_negative_continuations":false_negative,
                               "role_decisions":d["roles"]})
    regressions = []; improvements = []
    for task in review:
        base = paired[task,"embedding_geometry"]; hybrid = paired[task,"hybrid"]
        for key in ("structural_leaks","body_coverage_errors","wrong_body_merges","missed_continuations"):
            before, after = len(base[key]),len(hybrid[key])
            if after > before: regressions.append({"task":task,"metric":key,"before":before,"after":after})
            elif after < before: improvements.append({"task":task,"metric":key,"before":before,"after":after})
        if len(hybrid["correct_caption_pairs"]) < len(base["correct_caption_pairs"]):
            regressions.append({"task":task,"metric":"caption_pairs"})
        if not hybrid["source_coverage"] or hybrid["native_component_loss"]:
            regressions.append({"task":task,"metric":"source_or_component_loss"})
    holdout = next(iter(cfg["holdout_pages"]))
    holdout_improved = len(paired[holdout,"hybrid"]["missed_continuations"]) < len(
        paired[holdout,"embedding_geometry"]["missed_continuations"])
    decisions_valid = all(r["decision_valid"] for r in decision_audit)
    gate = {"pass": not regressions and bool(improvements) and holdout_improved and decisions_valid,
            "regressions":regressions,"improvements":improvements,"holdout_continuation_improved":holdout_improved,
            "all_qwen_decisions_valid":decisions_valid,
            "meaning":"Pass licenses consideration of opt-in integration only; three development and one holdout page do not establish corpus quality."}
    report = {"review":str(REVIEW),"assistant_review_not_independent_ground_truth":True,
              "rows":rows,"decision_audit":decision_audit,"gate":gate,"production_modified":False}
    (HYBRID/"evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(gate,ensure_ascii=False,indent=2))
    for task in review:
        print(task,{arm:{"leaks":len(paired[task,arm]["structural_leaks"]),
                         "wrong_merges":len(paired[task,arm]["wrong_body_merges"]),
                         "missed":len(paired[task,arm]["missed_continuations"]),
                         "caption":len(paired[task,arm]["correct_caption_pairs"])} for arm in arms})


if __name__ == "__main__": evaluate()
