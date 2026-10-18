#!/usr/bin/env python3
"""Shadow retrieval ablation that adds Dolphin line-preserving claim views."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import numpy as np

import compare_node_dedup_edge_retrieval as dedup
import run_hierarchical_edge_retrieval as hierarchical
from compare_previous_edge_schemes import coverage
from run_node_context_edges import ROOT, jsonl, read, rows, sha, tokens, write
from run_traffic_relevance_cpu import cpu_embed


SOURCE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
OUT = ROOT / "EvidenceNet/output/line_aware_edge_retrieval_v1_20261017"
ENCODER = ROOT / "EvidenceNet/models/Qwen3-Embedding-0.6B"


def physical_lines(text: str) -> list[tuple[int, int, str]]:
    """Return non-empty Dolphin lines with exact source offsets."""
    result = []
    for match in re.finditer(r"[^\r\n]+", text):
        value = match.group(0).strip()
        if not value:
            continue
        left = len(match.group(0)) - len(match.group(0).lstrip())
        right = len(match.group(0).rstrip())
        result.append((match.start() + left, match.start() + right, value))
    return result


def retrieval_render(lines: list[str]) -> str:
    # Keep the exact line spelling.  A hyphen at a line boundary is ambiguous:
    # ``spa-\ntiotemporal`` is a broken word, while ``RNN-\nbased`` is a real
    # compound.  Destructive dehyphenation here would silently corrupt one of
    # them.  Existing normalized long views remain available in parallel.
    return "\n".join(lines).strip()


def make_line_views(nodes: list[dict], existing: list[dict]) -> list[dict]:
    seen = {(v["node_id"], v["member_id"], v["retrieval_text"]) for v in existing}
    result = []
    for node in sorted(nodes, key=lambda value: value["id"]):
        for member in node.get("members", []):
            text = str(member.get("text") or "")
            lines = physical_lines(text)
            if not lines:
                continue
            # One-line views expose concise method/property statements. Four-line overlapping
            # views retain enough predicate context when Dolphin wraps a sentence across lines.
            spans = []
            for index in range(len(lines)):
                spans.append((index, index + 1, "dolphin_line"))
                if index % 2 == 0 and index + 1 < len(lines):
                    spans.append((index, min(index + 4, len(lines)), "dolphin_line_window"))
            for start, end, kind in spans:
                lo, hi = lines[start][0], lines[end - 1][1]
                rendered = retrieval_render([line[2] for line in lines[start:end]])
                token_count = len(tokens(rendered))
                if token_count < 4 or token_count > 72:
                    continue
                signature = (node["id"], member["id"], rendered)
                if signature in seen:
                    continue
                seen.add(signature)
                result.append({
                    "view_id": f"LINE_{len(result):06d}",
                    "node_id": node["id"],
                    "article_id": node["article_id"],
                    "member_id": member["id"],
                    "member_kind": member["kind"],
                    "kind": kind,
                    "char_start": lo,
                    "char_end": hi,
                    "quote": text[lo:hi],
                    "retrieval_text": rendered,
                    "identifiers": hierarchical.identifiers(rendered),
                    "source_status": "ORIGINAL_TEXT_LINE_STRUCTURE",
                })
    return result


def verify(out: Path) -> None:
    for path, digest in read(out / "manifest.json")["files"].items():
        if sha(path) != digest:
            raise ValueError("Changed frozen input/code: " + path)


def prepare(out: Path) -> None:
    if out.exists():
        raise ValueError("fresh_output_required")
    out.mkdir(parents=True)
    old_views = rows(SOURCE / "views.jsonl")
    nodes = rows(SOURCE / "corpus_nodes.jsonl")
    line_views = make_line_views(nodes, old_views)
    # IDs must remain globally unique after concatenation.
    for index, view in enumerate(line_views, len(old_views)):
        view["view_id"] = f"VIEW_{index:06d}"
    jsonl(out / "line_views.jsonl", line_views)
    write(out / "protocol.json", {
        "experiment": "line_aware_edge_retrieval_v1",
        "control": str(SOURCE),
        "base_views": len(old_views),
        "added_line_views": len(line_views),
        "line_policy": "Every non-empty Dolphin line plus overlapping four-line windows starting every two lines; 4-72 tokens; exact source offsets retained.",
        "representation": "Literal newline and hyphen tokens retained. Existing normalized long views remain in parallel; ambiguous line-end hyphens are not destructively rewritten.",
        "retrieval": "Existing views plus line views; target-node dedup before dense/BM25 top-30; original selector budgets.",
        "labels_used_for_retrieval_or_selection": False,
        "scope": "Candidate retrieval only; no semantic edge export.",
        "encoder": str(ENCODER),
    })
    files = [Path(__file__), SOURCE / "views.jsonl", SOURCE / "view_vectors.npy",
             SOURCE / "corpus_nodes.jsonl", SOURCE / "evaluation/cases.jsonl",
             out / "line_views.jsonl", out / "protocol.json", ENCODER / "config.json"]
    write(out / "manifest.json", {"files": {str(path.resolve()): sha(path) for path in files}})
    print(json.dumps({"base_views": len(old_views), "line_views": len(line_views), "output": str(out)}))


def run(out: Path) -> None:
    verify(out)
    base_views = rows(SOURCE / "views.jsonl")
    line_views = rows(out / "line_views.jsonl")
    base_vectors = np.load(SOURCE / "view_vectors.npy")
    line_vectors = np.asarray(cpu_embed([v["retrieval_text"] for v in line_views], ENCODER), dtype=np.float32)
    np.save(out / "line_vectors.npy", line_vectors)
    views = base_views + line_views
    vectors = np.concatenate((base_vectors, line_vectors), axis=0)
    pool = dedup.retrieve(views, vectors)
    nodes = {node["id"]: node for node in rows(SOURCE / "corpus_nodes.jsonl")}
    article_rows, candidates = hierarchical.route_and_select(nodes, pool)
    jsonl(out / "initial_pool.jsonl", pool.values())
    jsonl(out / "article_candidates.jsonl", article_rows)
    jsonl(out / "node_candidates.jsonl", candidates)
    write(out / "selection.json", {
        "views": len(views), "base_views": len(base_views), "line_views": len(line_views),
        "initial_pairs": len(pool), "final_pairs": len(candidates),
        "line_vectors_sha256": sha(out / "line_vectors.npy"),
        "initial_sha256": sha(out / "initial_pool.jsonl"),
        "final_sha256": sha(out / "node_candidates.jsonl"),
    })
    report(out)


def report(out: Path) -> None:
    verify(out)
    selection = read(out / "selection.json")
    for name, key in (("line_vectors.npy", "line_vectors_sha256"),
                      ("initial_pool.jsonl", "initial_sha256"),
                      ("node_candidates.jsonl", "final_sha256")):
        if sha(out / name) != selection[key]:
            raise ValueError("Changed frozen result: " + name)
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    initial_counts, initial_cases = coverage(cases, rows(out / "initial_pool.jsonl"))
    final_counts, final_cases = coverage(cases, rows(out / "node_candidates.jsonl"))
    control = read(SOURCE / "retrieval_summary.json")["results"]["hierarchical_76411_replay"]
    summary = {
        "complete": True,
        "control_final": control,
        "line_aware_initial": initial_counts,
        "line_aware_final": final_counts,
        "selection": selection,
        "interpretation": "Labels were read only after candidate lists were frozen; fixed development suite, not held-out accuracy.",
    }
    write(out / "summary.json", summary)
    write(out / "case_coverage.json", {"initial": initial_cases, "final": final_cases})
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "run", "report"])
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.stage](args.output.resolve())
