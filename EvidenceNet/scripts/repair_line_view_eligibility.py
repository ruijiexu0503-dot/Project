#!/usr/bin/env python3
"""Replay cached line retrieval after restoring member eligibility and provenance.

This shadow experiment never edits old runs and never generates embeddings.  It
keeps the old node-pair retrieval and selector settings, with labels available
only to the report step after candidate files have been frozen.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time

# Set before importing NumPy or any transitive numerical dependency.  Batch jobs
# can raise this explicitly within their allocated CPU count.
THREADS = max(1, int(os.environ.get("EDGE_RETRIEVAL_THREADS", "4")))
for _thread_option in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                       "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_thread_option] = str(THREADS)

import numpy as np

import compare_node_dedup_edge_retrieval as dedup
import run_hierarchical_edge_retrieval as hierarchical
from compare_previous_edge_schemes import coverage
from run_node_context_edges import ROOT, jsonl, read, rows, sha, write


SOURCE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
LINE = ROOT / "EvidenceNet/output/line_aware_edge_retrieval_v1_20261017"
OUT = ROOT / "EvidenceNet/output/line_aware_eligibility_repair_20261017"
BUDGET = 1301
GENERATED = "GENERATED_DESCRIPTION_FOR_RETRIEVAL_ONLY"


def filter_cached_views(views, vectors, nodes, policies, origin):
    """Keep source IDs and vector-row alignment; fail closed on missing policy."""
    if vectors.ndim != 2 or len(views) != len(vectors):
        raise ValueError("Cached view/vector row mismatch: " + origin)
    if len({v["view_id"] for v in views}) != len(views):
        raise ValueError("Duplicate view IDs: " + origin)
    kept, indices, audit = [], [], []
    for row, original in enumerate(views):
        node_id = original["node_id"]
        node, policy = nodes[node_id], policies[node_id]
        member_key = (original["member_kind"], original["member_id"])
        members = [m for m in node["members"] if (m["kind"], m["id"]) == member_key]
        member_policies = [m for m in policy["members"]
                           if (m["kind"], m["member_id"]) == member_key]
        if len(members) != 1 or len(member_policies) != 1:
            raise ValueError("Missing/ambiguous member or eligibility: " + original["view_id"])
        member, member_policy = members[0], member_policies[0]
        if type(policy.get("eligible")) is not bool or type(member_policy.get("eligible")) is not bool:
            raise ValueError("Eligibility must be explicit boolean: " + original["view_id"])
        record = {
            "view_id": original["view_id"], "origin": origin, "original_vector_row": row,
            "node_id": node_id, "member_id": original["member_id"],
            "member_kind": original["member_kind"],
        }
        if not policy["eligible"] or not member_policy["eligible"]:
            record.update(kept=False, reason=member_policy.get("reason") or "node_ineligible")
            audit.append(record)
            continue
        text = member.get("text") or ""
        lo, hi = original["char_start"], original["char_end"]
        if not (0 <= lo < hi <= len(text)) or text[lo:hi] != original["quote"]:
            raise ValueError("Source offset/quote mismatch: " + original["view_id"])
        view = dict(original)
        if view["member_kind"] == "visual":
            view["source_status"] = GENERATED
        record.update(kept=True, filtered_vector_row=len(kept),
                      source_status_before=original.get("source_status"),
                      source_status_after=view.get("source_status"))
        kept.append(view)
        indices.append(row)
        audit.append(record)
    return kept, vectors[np.asarray(indices, dtype=np.int64)], audit


def verify(out):
    for name, digest in read(out / "manifest.json")["files"].items():
        if sha(name) != digest:
            raise ValueError("Changed frozen input/code: " + name)


def dependency_files():
    # Include selector/tokenization dependencies as well as the previous scripts,
    # which are imported but intentionally left unchanged.
    names = [
        "repair_line_view_eligibility.py", "compare_node_dedup_edge_retrieval.py",
        "run_hierarchical_edge_retrieval.py", "compare_previous_edge_schemes.py",
        "run_node_context_edges.py", "run_traffic_relevance_cpu.py",
        "run_traffic_relevance_graph.py", "run_own_corpus_edges.py",
        "run_split_taxonomy_suite.py", "run_typed_node_edges.py",
        "run_fact_grounded_edges.py", "run_line_aware_edge_retrieval.py",
    ]
    return [Path(__file__).with_name(name) for name in names]


def prepare(out):
    if (out / "manifest.json").exists():
        verify(out)
        return
    if out.exists():
        raise ValueError("fresh_output_required")
    # Validate the old view/vector pairing against its recorded input/result
    # hashes. Hashing the reference file is allowed here; labels are not parsed.
    old_manifest = read(LINE / "manifest.json")["files"]
    source_files = [SOURCE / name for name in (
        "views.jsonl", "view_vectors.npy", "corpus_nodes.jsonl", "corpus_policies.json",
        "evaluation/cases.jsonl", "hierarchical_candidates.jsonl",
    )] + [LINE / name for name in (
        "line_views.jsonl", "line_vectors.npy", "manifest.json", "selection.json",
        "node_candidates.jsonl",
    )]
    for path in [SOURCE / "views.jsonl", SOURCE / "view_vectors.npy",
                 SOURCE / "corpus_nodes.jsonl", LINE / "line_views.jsonl"]:
        if old_manifest[str(path.resolve())] != sha(path):
            raise ValueError("Original cached input changed: " + str(path))
    old_selection = read(LINE / "selection.json")
    for name, field in (("line_vectors.npy", "line_vectors_sha256"),
                        ("node_candidates.jsonl", "final_sha256")):
        if old_selection[field] != sha(LINE / name):
            raise ValueError("Original cached result changed: " + name)
    nodes = {node["id"]: node for node in rows(SOURCE / "corpus_nodes.jsonl")}
    policies = read(SOURCE / "corpus_policies.json")
    parts, matrices, audits = [], [], []
    for origin, view_path, vector_path in (
        ("base", SOURCE / "views.jsonl", SOURCE / "view_vectors.npy"),
        ("line", LINE / "line_views.jsonl", LINE / "line_vectors.npy"),
    ):
        views, matrix, audit = filter_cached_views(
            rows(view_path), np.load(vector_path, allow_pickle=False), nodes, policies, origin,
        )
        for item in audit:
            if item["kept"]:
                item["combined_vector_row"] = sum(len(part) for part in parts) + item["filtered_vector_row"]
        parts.append(views)
        matrices.append(matrix)
        audits.extend(audit)
    views = parts[0] + parts[1]
    if len({view["view_id"] for view in views}) != len(views):
        raise ValueError("Duplicate view IDs between base and line caches")
    vectors = np.concatenate(matrices, axis=0)
    if not np.isfinite(vectors).all():
        raise ValueError("Non-finite cached vectors")
    out.mkdir(parents=True)
    jsonl(out / "views.jsonl", views)
    np.save(out / "view_vectors.npy", vectors, allow_pickle=False)
    jsonl(out / "view_filter_audit.jsonl", audits)
    write(out / "protocol.json", {
        "experiment": "line_aware_eligibility_repair", "source": str(SOURCE), "line_source": str(LINE),
        "change": "Filter node/member eligibility before retrieval; generated visual descriptions retain generated provenance.",
        "inputs": "Existing view text, IDs, offsets and corresponding vector rows; no new embeddings.",
        "old_views": len(audits), "kept_views": len(views), "dropped_views": sum(not a["kept"] for a in audits),
        "dropped_by_reason": dict(Counter(a["reason"] for a in audits if not a["kept"])),
        "provenance_corrections": sum(a["kept"] and a["source_status_before"] != a["source_status_after"] for a in audits),
        "selection": "Unchanged target-node-deduplicated dense/BM25 top-30, identifiers, article-neighbor 2, pair quota 16, global 96, intra 8, original degree caps.",
        "comparison_budget": BUDGET, "budget_policy": "Frozen score-ordered prefix; no positive-case promotion or backfill.",
        "labels_used_for_selection": False, "semantic_edges_exported": False,
    })
    source_files += dependency_files()
    source_files += [out / name for name in ("views.jsonl", "view_vectors.npy", "view_filter_audit.jsonl", "protocol.json")]
    write(out / "manifest.json", {"files": {str(path.resolve()): sha(path) for path in source_files}})
    print(json.dumps(read(out / "protocol.json")), flush=True)


def run(out):
    verify(out)
    if (out / "selection.json").exists():
        raise ValueError("Selection already frozen; use report instead of overwriting")
    start = time.monotonic()
    views = rows(out / "views.jsonl")
    vectors = np.load(out / "view_vectors.npy", allow_pickle=False)
    nodes = {node["id"]: node for node in rows(SOURCE / "corpus_nodes.jsonl")}
    pool = dedup.retrieve(views, vectors)
    articles, candidates = hierarchical.route_and_select(nodes, pool)
    outputs = {
        "initial_pool.jsonl": list(pool.values()), "article_candidates.jsonl": articles,
        "node_candidates.jsonl": candidates, "matched_candidates.jsonl": candidates[:BUDGET],
    }
    for name, records in outputs.items():
        jsonl(out / name, records)
    write(out / "selection.json", {
        "complete": True, "initial_pairs": len(pool), "native_pairs": len(candidates),
        "matched_pairs": min(BUDGET, len(candidates)), "matched_budget_reached": len(candidates) >= BUDGET,
        "files": {name: sha(out / name) for name in outputs},
    })
    write(out / "execution.json", {
        "job_id": os.environ.get("SLURM_JOB_ID"), "host": os.uname().nodename,
        "threads": THREADS, "elapsed_seconds": time.monotonic() - start,
        "new_embedding_calls": 0, "qwen_calls": 0,
    })
    report(out)


def report(out):
    verify(out)
    selection = read(out / "selection.json")
    for name, digest in selection["files"].items():
        if sha(out / name) != digest:
            raise ValueError("Changed frozen candidate output: " + name)
    # The only reference-label read in this script is after selection is frozen.
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    sets = {
        "control_hierarchical_1301": rows(SOURCE / "hierarchical_candidates.jsonl")[:BUDGET],
        "old_line_native": rows(LINE / "node_candidates.jsonl"),
        "old_line_matched_1301": rows(LINE / "node_candidates.jsonl")[:BUDGET],
        "repaired_initial": rows(out / "initial_pool.jsonl"),
        "repaired_native": rows(out / "node_candidates.jsonl"),
        "repaired_matched_1301": rows(out / "matched_candidates.jsonl"),
    }
    counts, details = {}, {}
    for name, candidates in sets.items():
        counts[name], details[name] = coverage(cases, candidates)
    summary = {
        "complete": True, "protocol": read(out / "protocol.json"), "selection": selection,
        "results": counts,
        "interpretation": "Development candidate coverage only, not semantic precision or independent held-out performance. Labels read only after lists were frozen.",
    }
    write(out / "summary.json", summary)
    write(out / "case_coverage.json", details)
    table = ["# Line-view eligibility repair", "", summary["interpretation"], "",
             "| Arm | Candidates | Positive / 26 | Hard negative / 27 | Navigation / 2 |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for name, count in counts.items():
        table.append(f"| {name} | {count['candidate_pairs']} | {count['POSITIVE_retrieved']} | {count['NEGATIVE_retrieved']} | {count['NAVIGATION_POSITIVE_retrieved']} |")
    (out / "REPORT.md").write_text("\n".join(table) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run", "report"))
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.stage](args.output.resolve())
