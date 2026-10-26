#!/usr/bin/env python3
"""Frozen, text-only synthetic stress test of the existing relation verifier.

Reuses the production-development model/prompt/validator unchanged; does not
retrieve candidates, add graph edges, or mix authored labels into real corpora.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import run_routed_edge_context as routed
import run_relatedness_pilot as broad
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
from synthetic_edge_specs_20261021 import SPECS

ARMS = ("control", "text_scope", "text_readable", "swapped")
SUITE = ROOT / "data/benchmarks/evidence_edges_synthetic_v1_20261022"
OUT = ROOT / "EvidenceNet/output/synthetic_text_edges_v1_20261022"


def make_node(raw, side):
    # Distinct synthetic document per authored endpoint; identical same-side
    # text is reused in minimal pairs. Neither names nor IDs encode gold labels.
    key = hashlib.sha256((side + "\0" + raw).encode()).hexdigest()
    return {"id": "SN_" + key[:24], "document": "SD_" + key[:24],
            "article_id": "SA_" + key[:24], "page": 1,
            "source_collection": "synthetic_text_only",
            "members": [{"id": "M_" + key[:24], "kind": "atom", "type": "text", "text": raw}],
            "eligible_members": [{"member_id": "M_" + key[:24], "kind": "atom", "eligible": True}]}


def base_entry(a, b):
    task = {"task_id": broad.task_id(tuple(sorted((a["id"], b["id"]))))}
    entry = {"task": task, "images": [], "image_sha256": [], "lookups": {},
             "contexts": {"A": [], "B": []},
             "routing": {"A": "prose", "B": "prose", "group": "prose"}}
    for side, node in (("A", a), ("B", b)):
        task[side], entry["lookups"][side] = broad.catalog(node, side, OUT, entry["images"])
    assert not entry["images"]
    return entry


def build(specs=SPECS):
    nodes, references, planned, task_ids = {}, [], {arm: [] for arm in ARMS}, set()
    for spec in specs:
        a, b = make_node(spec["a"], "a"), make_node(spec["b"], "b")
        nodes.update({a["id"]: a, b["id"]: b})
        original = base_entry(a, b)
        tid = original["task"]["task_id"]
        if tid in task_ids:
            raise ValueError("Duplicate authored pair: " + spec["id"])
        task_ids.add(tid)
        positive, ambiguous = spec["expected"] == "RELATED", spec["expected"] == "U"
        references.append({"suite_case_id": spec["id"], "task_id": tid,
            "allowed_levels": [0, 1, 2, 3] if ambiguous else [2, 3] if positive else [0, 1],
            "allowed_decisions": ["EVIDENCE_LINK", "NAVIGATION_LINK", "NO_LINK", "UNCERTAIN"] if ambiguous
                else ["EVIDENCE_LINK", "NAVIGATION_LINK"] if positive else ["NO_LINK"],
            "cutoff_evaluable": not ambiguous, "decision_evaluable": not ambiguous,
            "annotation_label": spec["expected"], "direction": "UNDIRECTED",
            "reviewer": "assistant_authored_provisional_not_independent_expert"})
        for arm in ARMS:
            entry = base_entry(b, a) if arm == "swapped" else copy.deepcopy(original)
            assert entry["task"]["task_id"] == tid
            if arm == "text_readable":
                entry = routed.readable_entry(entry, nodes)
            scope = routed.SCOPE if arm in {"text_scope", "text_readable"} else ""
            entry["prompt"] = (routed.gate.prompt(entry["task"]) + routed.POLICY
                               + json.dumps(entry["contexts"], ensure_ascii=False) + scope)
            entry["inference_key"] = routed.inference_key(entry)
            planned[arm].append(entry)
    return list(nodes.values()), references, planned


def check_inputs(out):
    """Audit zero images, exact authored anchors, and isolated arm changes."""
    nodes = {n["id"]: n for n in rows(out / "nodes.jsonl")}
    specs = read(out / "specs.json")
    refs = rows(out / "reference.jsonl")
    planned = {arm: rows(out / arm / "inputs.jsonl") for arm in ARMS}
    assert len({s["id"] for s in specs}) == len(specs) == len(refs)
    assert len({r["task_id"] for r in refs}) == len(refs)
    assert [r["suite_case_id"] for r in refs] == [s["id"] for s in specs]
    for arm, entries in planned.items():
        assert [e["task"]["task_id"] for e in entries] == [r["task_id"] for r in refs]
        for spec, entry in zip(specs, entries):
            assert entry["images"] == entry["image_sha256"] == []
            assert entry["contexts"] == {"A": [], "B": []}
            assert entry["inference_key"] == routed.inference_key(entry)
            for side in ("A", "B"):
                node = nodes[entry["task"][side]["node_id"]]
                member = node["members"][0]
                raw = member["text"]
                original_side = {"A": "b", "B": "a"} if arm == "swapped" else {"A": "a", "B": "b"}
                assert raw == spec[original_side[side]]
                covered = set()
                for evidence in entry["task"][side]["evidence"]:
                    eid = evidence["evidence_id"]
                    anchor = entry["lookups"][side][eid]
                    assert eid.startswith(side + ":") and anchor["node_id"] == node["id"]
                    assert anchor["member_id"] == member["id"]
                    assert anchor["member_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
                    assert anchor["quote"] == raw[anchor["char_start"]:anchor["char_end"]]
                    assert anchor["kind"] == "ORIGINAL_TEXT" and evidence["image_number"] is None
                    assert evidence["text"] == (routed.render_readable(anchor["quote"]) if arm == "text_readable" else anchor["quote"])
                    covered.update(range(anchor["char_start"], anchor["char_end"]))
                assert all(i in covered or char.isspace() for i, char in enumerate(raw))
            for forbidden in (spec["id"], spec["reason"], "annotation_label", "cutoff_evaluable", "allowed_decisions"):
                assert forbidden not in entry["prompt"]
    for control, scope, swapped in zip(planned["control"], planned["text_scope"], planned["swapped"]):
        assert scope["task"] == control["task"] and scope["lookups"] == control["lookups"]
        assert scope["prompt"] == control["prompt"] + routed.SCOPE
        assert swapped["task"]["A"]["node_id"] == control["task"]["B"]["node_id"]
        assert swapped["task"]["B"]["node_id"] == control["task"]["A"]["node_id"]
    return {"pairs": len(specs), "unique_nodes": len(nodes), "arms": list(ARMS),
            "labels": dict(Counter(s["expected"] for s in specs)),
            "images": 0, "exact_raw_anchors": True, "labels_absent_from_prompts": True,
            "unique_inferences": len({e["inference_key"] for entries in planned.values() for e in entries})}


def prepare(suite, out, model):
    if suite.exists() or out.exists():
        raise ValueError("Fresh suite and output required; never overwrite or refreeze an evaluated suite")
    code = [Path(__file__), Path(__file__).with_name("synthetic_edge_specs_20261021.py"),
            Path(__file__).with_name("report_synthetic_edge_suite.py")]
    code_hashes = {str(p.relative_to(ROOT)): sha(p) for p in code}
    nodes, refs, planned = build()
    for directory in (suite, out):
        write(directory / "specs.json", SPECS)
        jsonl(directory / "nodes.jsonl", nodes)
        jsonl(directory / "reference.jsonl", refs)
    for arm, entries in planned.items():
        jsonl(out / arm / "inputs.jsonl", entries)
    audit = check_inputs(out)
    protocol = {"experiment": "synthetic_text_edges_v1_20261022", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT), "source_suite": str(suite), "model": str(model),
        "model_config_sha256": sha(model / "config.json"), "arms": list(ARMS), "system": routed.SYSTEM,
        "inference": {"max_new_tokens": 700, "attempts": 2, "thinking": False, "sampling": False},
        "audit": audit, "code": code_hashes,
        "controls": ["English authored fictional text; genuine text-only inference: no images or source crops",
            "Reuse existing frozen prompt, validator, metadata repair, deterministic model settings and token budget",
            "control vs text_scope changes scope policy only; text_readable additionally repacks/normalizes evidence views",
            "swapped changes only A/B ownership/order relative to control; relation evaluation remains undirected",
            "Exact inference duplicates reuse the same recorded response, reported as reused",
            "Raw text including CRLF remains unchanged in nodes and offset/hash anchors",
            "Gold rationale, family, case ID and labels are never shown to model"],
        "evaluation": "Synthetic diagnostic stress test, not representative accuracy, retrieval recall, or unseen real-paper performance. Matched cases are correlated. Assistant labels frozen before inference, not independent expert gold. RELATED accepts E/N; U excluded; missing/invalid retained in full score denominators. No production graph mutation.",
        "non_support_warning": "RELATED is not entailment or corroboration. Opposite conclusions remain related; inspect polarity-conflict notes and model reasoning separately.",
        "reference_scope": "Citation-number cases probe semantic verifier only; independent CITES builder is neither run nor changed."}
    write(out / "protocol.json", protocol)
    write(suite / "protocol.json", protocol)
    write(suite / "manifest.json", {"code": code_hashes, "files": {
        str(p.relative_to(suite)): sha(p) for p in sorted(suite.rglob("*")) if p.is_file()}})
    routed.freeze(out)
    manifest = read(out / "manifest.json")
    manifest["code"].update(code_hashes)
    write(out / "manifest.json", manifest)
    routed.verify(out, model)
    from report_synthetic_edge_suite import report
    report(out)
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)


def run(out, model, image_root, minutes):
    check_inputs(out)
    previous = routed.ARMS
    try:
        routed.ARMS = ARMS
        routed.run(out, model, image_root, minutes)
    finally:
        routed.ARMS = previous
    from report_synthetic_edge_suite import report
    return report(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "verify", "run", "report"))
    parser.add_argument("--suite", type=Path, default=SUITE)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--model", type=Path, default=routed.gate.MODEL)
    parser.add_argument("--image-root", type=Path, default=ROOT)
    parser.add_argument("--minutes", type=int, default=52)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == "prepare":
        prepare(args.suite.resolve(), out, args.model.resolve())
    elif args.stage == "verify":
        routed.verify(out, args.model.resolve())
        print(json.dumps(check_inputs(out)))
    elif args.stage == "run":
        run(out, args.model.resolve(), args.image_root.resolve(), args.minutes)
    else:
        routed.verify(out)
        from report_synthetic_edge_suite import report
        print(json.dumps(report(out), ensure_ascii=False))
