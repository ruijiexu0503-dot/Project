#!/usr/bin/env python3
"""Genuine text-only rerun of previously annotated real node pairs.

No new labels, graph mutations, candidate retrieval, or inferred gold E/N labels.
Historical model inputs/results and the synthetic suite stay immutable.
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
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha

ARMS = ("control", "text_scope", "text_readable", "swapped")
OUT = ROOT / "EvidenceNet/output/real_text_edges_v1_20261022"
OLD = ROOT / "EvidenceNet/output/routed_edge_context_v1_20261020"
FRESH = ROOT / "EvidenceNet/output/routed_edge_context_fresh_v1_20261021"
REVIEW = ROOT / "data/benchmarks/evidence_edges_fresh_v1_20261021_review/reference.jsonl"
CORPUS = routed.prior.CORPUS / "corpus_nodes.jsonl"


def strip_images(source):
    """Copy only model-facing content/anchors, dropping source crop pointers."""
    entry = {"task": copy.deepcopy(source["task"]), "lookups": copy.deepcopy(source["lookups"]),
             "images": [], "image_sha256": [], "contexts": {"A": [], "B": []},
             "routing": copy.deepcopy(source["routing"])}
    if entry["routing"] != {"A": "prose", "B": "prose", "group": "prose"}:
        raise ValueError("Only original prose-prose pairs can enter this experiment")
    for side in ("A", "B"):
        entry["task"][side].pop("node_source_image_number", None)
        for evidence in entry["task"][side]["evidence"]:
            if evidence["kind"] != "ORIGINAL_TEXT" or evidence.get("image_number") is not None:
                raise ValueError("Non-prose evidence/image dependency")
        if not entry["lookups"][side] or any(a["kind"] != "ORIGINAL_TEXT" for a in entry["lookups"][side].values()):
            raise ValueError("Both sides need original text anchors")
    return entry


def swap(entry):
    result = copy.deepcopy(entry)
    for new_side, old_side in (("A", "B"), ("B", "A")):
        endpoint = copy.deepcopy(entry["task"][old_side])
        renamed = {}
        for evidence in endpoint["evidence"]:
            old_id = evidence["evidence_id"]
            if not old_id.startswith(old_side + ":"):
                raise ValueError("Invalid evidence ownership")
            new_id = new_side + old_id[len(old_side):]
            renamed[new_id] = copy.deepcopy(entry["lookups"][old_side][old_id])
            evidence["evidence_id"] = new_id
        result["task"][new_side] = endpoint
        result["lookups"][new_side] = renamed
    return result


def reference(source_ref, source_suite):
    ref = copy.deepcopy(source_ref)
    ref["source_suite"] = source_suite
    prefix = "OLD_" if source_suite == "old_development" else "FRESH_"
    ref["original_suite_case_id"] = ref["suite_case_id"]
    ref["suite_case_id"] = prefix + ref["suite_case_id"]
    if source_suite == "old_development":
        # Historical levels describe broad relatedness, not strict evidence promotion.
        evaluable = ref["cutoff_evaluable"]
        positive = min(ref["allowed_levels"]) >= 2
        ref["annotation_label"] = "U" if not evaluable else "RELATED" if positive else "NO_LINK"
        ref["allowed_decisions"] = (["EVIDENCE_LINK", "NAVIGATION_LINK", "NO_LINK", "UNCERTAIN"] if not evaluable
            else ["EVIDENCE_LINK", "NAVIGATION_LINK"] if positive else ["NO_LINK"])
        ref["decision_evaluable"] = False
    ref["rationale"] = ref.get("rationale") or ref.get("note", "")
    return ref


def build(sources, nodes):
    planned, refs, selected, seen = {arm: [] for arm in ARMS}, [], {}, set()
    excluded, source_images = Counter(), Counter()
    for source_suite, originals, source_refs in sources:
        by_id = {r["task_id"]: r for r in source_refs}
        if len(by_id) != len(source_refs):
            raise ValueError("Duplicate reference task IDs")
        for original in originals:
            if original["routing"]["group"] != "prose":
                excluded[source_suite + "_non_prose"] += 1
                continue
            tid = original["task"]["task_id"]
            if tid not in by_id:
                excluded[source_suite + "_unlabelled"] += 1
                continue
            if any(not original["lookups"][side] for side in ("A", "B")):
                # E.g. old N13: author-biography endpoint was excluded by the
                # historical eligibility policy. Do not score an empty input as
                # a successful demonstration of text-text semantic judgment.
                excluded[source_suite + "_empty_original_text_" + by_id[tid]["suite_case_id"]] += 1
                continue
            if tid in seen:
                raise ValueError("Pair overlaps across source suites: " + tid)
            seen.add(tid)
            base = strip_images(original)
            ref = reference(by_id[tid], source_suite)
            ref["previous_image_count"] = len(original["images"])
            source_images[str(len(original["images"]))] += 1
            endpoints = [nodes[base["task"][side]["node_id"]] for side in ("A", "B")]
            ref["document_scope"] = "cross_document" if endpoints[0]["document"] != endpoints[1]["document"] else "same_document"
            for node in endpoints:
                selected[node["id"]] = node
            refs.append(ref)
            for arm in ARMS:
                entry = swap(base) if arm == "swapped" else copy.deepcopy(base)
                if arm == "text_readable":
                    entry = routed.readable_entry(entry, nodes)
                scope = routed.SCOPE if arm in {"text_scope", "text_readable"} else ""
                entry["prompt"] = routed.gate.prompt(entry["task"]) + routed.POLICY + json.dumps(entry["contexts"], ensure_ascii=False) + scope
                entry["inference_key"] = routed.inference_key(entry)
                planned[arm].append(entry)
    return list(selected.values()), refs, planned, dict(excluded), dict(source_images)


def check_inputs(out):
    nodes = {n["id"]: n for n in rows(out / "nodes.jsonl")}
    refs = rows(out / "reference.jsonl")
    planned = {arm: rows(out / arm / "inputs.jsonl") for arm in ARMS}
    assert len({r["task_id"] for r in refs}) == len(refs)
    assert len({r["suite_case_id"] for r in refs}) == len(refs)
    assert all(r["annotation_label"] != "UNLABELLED" for r in refs)
    for arm, entries in planned.items():
        assert [e["task"]["task_id"] for e in entries] == [r["task_id"] for r in refs]
        for ref, entry in zip(refs, entries):
            assert entry["images"] == entry["image_sha256"] == []
            assert entry["contexts"] == {"A": [], "B": []}
            assert entry["inference_key"] == routed.inference_key(entry)
            assert entry["routing"] == {"A": "prose", "B": "prose", "group": "prose"}
            for side in ("A", "B"):
                endpoint = entry["task"][side]
                assert "node_source_image_number" not in endpoint
                node = nodes[endpoint["node_id"]]
                assert len(endpoint["evidence"]) == len(entry["lookups"][side])
                for evidence in endpoint["evidence"]:
                    eid = evidence["evidence_id"]
                    assert eid.startswith(side + ":") and evidence.get("image_number") is None
                    anchor = entry["lookups"][side][eid]
                    assert anchor["node_id"] == node["id"] and anchor["kind"] == "ORIGINAL_TEXT"
                    member = next(m for m in node["members"] if m["id"] == anchor["member_id"] and m["kind"] == "atom")
                    raw = member["text"]
                    assert anchor["member_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
                    assert anchor["quote"] == raw[anchor["char_start"]:anchor["char_end"]]
                    assert evidence["text"] == (routed.render_readable(anchor["quote"]) if arm == "text_readable" else anchor["quote"])
                    assert not any(key in anchor for key in ("crop", "crop_sha256"))
            for hidden in (ref["suite_case_id"], "annotation_label", "allowed_decisions", "cutoff_evaluable"):
                assert hidden not in entry["prompt"]
    for control, scope, swapped in zip(planned["control"], planned["text_scope"], planned["swapped"]):
        assert control["task"] == scope["task"] and control["lookups"] == scope["lookups"]
        assert scope["prompt"] == control["prompt"] + routed.SCOPE
        for a, b in (("A", "B"), ("B", "A")):
            assert control["task"][a]["node_id"] == swapped["task"][b]["node_id"]
            assert list(control["lookups"][a].values()) == list(swapped["lookups"][b].values())
    return {"pairs": len(refs), "nodes": len(nodes), "source_suites": dict(Counter(r["source_suite"] for r in refs)),
        "broad_scored": sum(r["cutoff_evaluable"] for r in refs),
        "strict_decision_scored": sum(r["decision_evaluable"] for r in refs),
        "boundary_unscored": sum(not r["cutoff_evaluable"] for r in refs), "images": 0,
        "document_scopes": dict(Counter(r["document_scope"] for r in refs)),
        "unique_inferences": len({e["inference_key"] for entries in planned.values() for e in entries})}


def prepare(out, model):
    if out.exists():
        raise ValueError("Fresh output required; do not overwrite previous inputs or results")
    report_path = Path(__file__).with_name("report_real_text_edge_suite.py")
    extra_code = {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), report_path)}
    sources = [OLD / "control/inputs.jsonl", OLD / "reference.jsonl", FRESH / "control/inputs.jsonl", REVIEW, CORPUS]
    for directory in (OLD, FRESH):
        manifest = read(directory / "manifest.json")
        for relative in ("control/inputs.jsonl", "reference.jsonl"):
            if sha(directory / relative) != manifest["files"][relative]:
                raise ValueError("Historical frozen source changed: " + str(directory / relative))
    records = rows(CORPUS)
    nodes = {n["id"]: n for n in records}
    if len(nodes) != len(records):
        raise ValueError("Duplicate corpus node IDs")
    selected, refs, planned, excluded, images = build([
        ("old_development", rows(sources[0]), rows(sources[1])),
        ("fresh_reviewed", rows(sources[2]), rows(REVIEW)),
    ], nodes)
    jsonl(out / "nodes.jsonl", selected)
    jsonl(out / "reference.jsonl", refs)
    for arm, entries in planned.items():
        jsonl(out / arm / "inputs.jsonl", entries)
    audit = check_inputs(out)
    assert audit["pairs"] == 58 and audit["broad_scored"] == 56 and audit["boundary_unscored"] == 2
    assert next(r for r in refs if r["suite_case_id"] == "FRESH_F009")["annotation_label"] == "U"
    protocol = {"experiment": "real_text_edges_v1_20261022", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT), "model": str(model), "model_config_sha256": sha(model / "config.json"),
        "arms": list(ARMS), "system": routed.SYSTEM,
        "inference": {"max_new_tokens": 700, "attempts": 2, "thinking": False, "sampling": False},
        "audit": audit, "excluded": excluded, "previous_images_per_pair": images,
        "source_hashes": {str(p.relative_to(ROOT)): sha(p) for p in sources},
        "controls": ["Same four arms as synthetic suite, genuine text-only model calls, no source crops",
            "Previously annotated original prose-prose pairs only; unlabelled natural pairs excluded",
            "Old N13 has an endpoint removed by original eligibility filtering; excluded from semantic-capability denominator, original label unchanged",
            "Existing immutable node IDs, raw original text, offsets, hashes, pair IDs and source ownership retained",
            "No added neighboring context; text_readable is sentence-preserving repacking, not sentence retrieval",
            "Same model, system, prompts, validator, optional metadata repair, token budget, retries and cache logic",
            "A/B swapped uses unchanged control prompt; outputs evaluated as undirected relations",
            "No existing image-bearing cached predictions reused because these are different requests"],
        "evaluation": "Real previously annotated diagnostic fixed-pair rerun, NOT a new held-out test or retrieval evaluation. Report old and fresh source groups separately from synthetic. Broad relatedness primary; old broad labels cannot establish strict E/N gold. Fresh reviewed strict labels retained, including F009=U. Missing/invalid/abstention stay in full denominators. Relatedness is not support; no graph export.",
        "code": extra_code}
    write(out / "protocol.json", protocol)
    routed.freeze(out)
    manifest = read(out / "manifest.json")
    manifest["code"].update(extra_code)
    write(out / "manifest.json", manifest)
    routed.verify(out, model)
    from report_real_text_edge_suite import report
    report(out)
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)


def run(out, model, image_root, minutes):
    check_inputs(out)
    saved = routed.ARMS
    try:
        routed.ARMS = ARMS
        routed.run(out, model, image_root, minutes)
    finally:
        routed.ARMS = saved
    from report_real_text_edge_suite import report
    return report(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "verify", "run", "report"))
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--model", type=Path, default=routed.gate.MODEL)
    parser.add_argument("--image-root", type=Path, default=ROOT)
    parser.add_argument("--minutes", type=int, default=52)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == "prepare":
        prepare(out, args.model.resolve())
    elif args.stage == "verify":
        routed.verify(out, args.model.resolve())
        print(json.dumps(check_inputs(out)))
    elif args.stage == "run":
        run(out, args.model.resolve(), args.image_root.resolve(), args.minutes)
    else:
        routed.verify(out)
        from report_real_text_edge_suite import report
        print(json.dumps(report(out), ensure_ascii=False))
