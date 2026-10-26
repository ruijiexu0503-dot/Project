#!/usr/bin/env python3
"""Frozen window/physical-line/sentence matching on real and synthetic text.

Representation-only experiment: identical dense encoder, ranking budgets,
matched-span limit, context rule, and baseline verifier in all three arms.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path

import numpy as np

from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
import run_routed_edge_context as routed
import compare_edge_embedding_models as encoders
import run_hierarchical_edge_retrieval as retrieval
import edge_granularity_views as granular

OUT = ROOT / "EvidenceNet/output/edge_granularity_v1_20261022"
ENCODER = ROOT / "EvidenceNet/models/Qwen3-Embedding-8B"
SOURCES = {d: ROOT / "EvidenceNet/output" / (d + "_text_edges_v1_20261022") for d in ("real", "synthetic")}
ARMS = ("window96", "physical_line", "sentence")
VERIFIER_ARMS = ("control", "physical_line", "sentence")
ARM_MAP = dict(zip(ARMS, VERIFIER_ARMS))
BUDGETS = {"real": 200, "synthetic": 100}
TOP_MATCHES = 2
MATCH_POLICY = '''\nMATCHED ORIGINAL SPANS:
The candidate_matches field only identifies retrieval-selected portions of the supplied original
evidence. Selection is NOT proof of a relation. Evaluate the complete supplied original context,
including negation, subject identity, definitions and qualifications, before deciding.
The focus strings are copied/normalized excerpts, not summaries or additional evidence.
Evidence IDs point to exact original windows containing those focus spans and adjacent sentences.
Do not infer a shared entity or ignore contradictions merely because spans were retrieved together.
Return the same JSON schema and source-grounded evidence IDs required above.
'''


def encoder_identity(path):
    path = Path(path)
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json"):
        if not (path / name).is_file():
            raise ValueError("Required encoder file missing: " + str(path / name))
    weights = sorted(set(read(path / "model.safetensors.index.json")["weight_map"].values()))
    return {"files_sha256": {p.name: sha(p) for p in sorted(path.glob("*.json"))},
            "weight_files_bytes": {name: (path / name).stat().st_size for name in weights}}


def code_paths():
    here = Path(__file__).parent
    return [Path(__file__), Path(granular.__file__), here / "report_edge_granularity.py",
        Path(encoders.__file__), Path(retrieval.__file__), Path(routed.__file__),
        Path(routed.prior.__file__), Path(routed.gate.__file__),
        here / "run_relatedness_pilot.py", here / "run_node_context_edges.py",
        here / "dolphin_text.py", here / "edge_text_views.py", here / "postprocess_named_identity_gate.py",
        ROOT / "EvidenceNet/evidence_graph/llm_client.py"]


def manifest_check(root, name="manifest.json"):
    manifest = read(root / name)
    for relative, digest in manifest.get("code", {}).items():
        if sha(ROOT / relative) != digest:
            raise ValueError("Changed frozen code: " + relative)
    for relative, digest in manifest["files"].items():
        if sha(root / relative) != digest:
            raise ValueError("Changed frozen artifact: " + str(root / relative))


def verify(out, model=None, encoder=None):
    manifest_check(out)
    protocol = read(out / "protocol.json")
    if model is not None and sha(Path(model) / "config.json") != protocol["model_config_sha256"]:
        raise ValueError("Verifier model config mismatch")
    if encoder is not None and encoder_identity(encoder) != protocol["encoder"]["identity"]:
        raise ValueError("Embedding model/config/tokenizer mismatch; no fallback allowed")
    if (out / "embedding_manifest.json").exists():
        manifest_check(out, "embedding_manifest.json")
    if (out / "matching_manifest.json").exists():
        manifest_check(out, "matching_manifest.json")
        routed.verify(out / "verifier", model)


def snapshot_data(sources):
    nodes, pairs, refs, allowed = {}, [], [], defaultdict(set)
    source_hashes, seen = {}, set()
    for dataset, directory in sources.items():
        old_manifest = read(directory / "manifest.json")
        for relative in ("nodes.jsonl", "reference.jsonl", "control/inputs.jsonl"):
            path = directory / relative
            if sha(path) != old_manifest["files"][relative]:
                raise ValueError("Source snapshot changed: " + str(path))
            source_hashes[str(path.relative_to(ROOT))] = sha(path)
        ns = {n["id"]: n for n in rows(directory / "nodes.jsonl")}
        source_refs = {r["task_id"]: r for r in rows(directory / "reference.jsonl")}
        for entry in rows(directory / "control/inputs.jsonl"):
            tid = entry["task"]["task_id"]
            if tid in seen or entry["images"] or entry["image_sha256"]:
                raise ValueError("Duplicate pair or non-text source")
            seen.add(tid)
            ref = copy.deepcopy(source_refs[tid])
            ref["dataset"] = dataset
            ref.setdefault("source_suite", "synthetic_authored")
            a, b = (ns[entry["task"][side]["node_id"]] for side in ("A", "B"))
            ref["document_scope"] = "cross_document" if a["document"] != b["document"] else "same_document"
            refs.append(ref)
            pairs.append({"dataset": dataset, "task": copy.deepcopy(entry["task"])})
            for side in ("A", "B"):
                node = ns[entry["task"][side]["node_id"]]
                if node["id"] in nodes and nodes[node["id"]] != node:
                    raise ValueError("Node identity collision")
                nodes[node["id"]] = copy.deepcopy(node)
                anchors = entry["lookups"][side]
                if not anchors or any(a["kind"] != "ORIGINAL_TEXT" for a in anchors.values()):
                    raise ValueError("Every endpoint needs eligible original text")
                for anchor in anchors.values():
                    member = next(m for m in node["members"] if m["id"] == anchor["member_id"] and m["kind"] == "atom")
                    raw = member["text"]
                    if (hashlib.sha256(raw.encode()).hexdigest() != anchor["member_sha256"] or
                            raw[anchor["char_start"]:anchor["char_end"]] != anchor["quote"]):
                        raise ValueError("Original source anchor mismatch")
                    # Check that the frozen eligible evidence actually covers this
                    # member before deriving new views from its complete text.
                    spans = [x for x in anchors.values() if x["member_id"] == member["id"]]
                    covered = {i for x in spans for i in range(x["char_start"], x["char_end"])}
                    if any(i not in covered and not c.isspace() for i, c in enumerate(raw)):
                        raise ValueError("Source evidence does not cover eligible member")
                    allowed[dataset].add((node["id"], member["id"]))
    return nodes, pairs, refs, allowed, source_hashes


def prepare(out, encoder, model):
    if out.exists():
        raise ValueError("Fresh output directory required; never refreeze after viewing results")
    codes = {str(p.relative_to(ROOT)): sha(p) for p in code_paths()}
    identity = encoder_identity(encoder)
    nodes, pairs, refs, allowed, sources = snapshot_data(SOURCES)
    jsonl(out / "nodes.jsonl", list(nodes.values()))
    jsonl(out / "pairs.jsonl", pairs)
    jsonl(out / "references.jsonl", refs)
    view_stats, texts = {}, {}
    for dataset, keys in allowed.items():
        view_stats[dataset] = {}
        for arm in ARMS:
            views = granular.make_views(nodes, keys, arm)
            if {v["node_id"] for v in views} != {n for n, _ in keys}:
                raise ValueError("A representation lost an eligible node")
            for view in views:
                text_id = hashlib.sha256(view["retrieval_text"].encode()).hexdigest()
                view["text_id"] = text_id
                texts[text_id] = view["retrieval_text"]
                context = granular.context_for_view(view, nodes)
                if not context["quote"] or context["char_start"] > view["char_start"] or context["char_end"] < view["char_end"]:
                    raise ValueError("Context dropped part of matched span")
            jsonl(out / dataset / arm / "views.jsonl", views)
            counts = Counter(v["node_id"] for v in views)
            view_stats[dataset][arm] = {"views": len(views), "nodes": len(counts),
                "views_per_node": dict(counts), "short_views_under_four_words": sum(v["word_count"] < 4 for v in views),
                "max_view_words": max(v["word_count"] for v in views),
                "max_context_words": max(len(granular.context_for_view(v, nodes)["quote"].split()) for v in views)}
    jsonl(out / "embedding_texts.jsonl", [{"text_id": k, "text": v} for k, v in sorted(texts.items())])
    protocol = {"experiment": "edge_granularity_v1_20261022", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT), "source_hashes": sources, "model": str(model),
        "model_config_sha256": sha(model / "config.json"), "encoder": {"name": "Qwen3-Embedding-8B",
            "path": str(encoder), "identity": identity, "pooling": "last_token", "padding_side": "left",
            "max_length": 512, "batch_size": 6, "query_instruction": None, "normalize": "L2",
            "truncation_policy": "reject overlength input; never silently truncate"},
        "arms": list(ARMS), "verifier_arm_map": ARM_MAP,
        "selection": {"budgets": BUDGETS, "top_span_pairs": TOP_MATCHES,
            "node_pair_score": "maximum view-to-view cosine", "pair_scope": "all distinct nodes within each dataset, same-document pairs included",
            "tie_break": "node IDs / view IDs, no labels", "span_dedup": "reject only if BOTH sides overlap at least half of shorter span"},
        "context": "Complete sentences intersecting matched span plus one preceding and following sentence, same member only; no word truncation; actual lengths recorded",
        "representation": "96 raw-whitespace-word windows stride72; raw LF/CRLF/CR nonempty lines; individual complete source sentences (max_chars=1 prevents packing). Uniform existing retrieval.clean renderer, no min-word filter in ANY arm. This preserves short negation lines, and is not a byte-identical full production retrieval baseline.",
        "verifier_policy": MATCH_POLICY, "system": routed.SYSTEM,
        "inference": {"max_new_tokens": 700, "attempts": 2, "thinking": False, "sampling": False},
        "datasets": {d: {"pairs": sum(p["dataset"] == d for p in pairs),
                          "nodes": len({n for n, _ in keys}), "eligible_members": len(keys)} for d, keys in allowed.items()},
        "view_stats": view_stats, "embedding_unique_texts": len(texts),
        "controls": ["Same fixed original nodes and reviewed references as prior text-only experiment; no label revisions",
            "Source members restricted to frozen eligible original anchors; no additional document context or images",
            "All three arms use same encoder, dense aggregation, candidate budget, top2 matching, context policy and verifier prompt",
            "No text_scope policy; retrieval similarities, arm names, and reference labels never shown to verifier",
            "Only selected focus/context windows sent to verifier, no automatic whole-node fallback",
            "All 90 annotated fixed pairs are verified in each arm regardless of retrieval rank; do not confuse forced-pair scores with candidate coverage",
            "Ranking covers restricted 82-node real and 54-node synthetic pools, NOT the full corpus; unlabelled candidates are not negatives",
            "More views create more maximum-score opportunities; report views per node and budget/rank, not threshold-based precision claims",
            "Freeze views/code/protocol before embedding, then vectors/matches/prompts before LLM; refuse stale caches",
            "No production graph mutation; broad relation does not imply support or evidence propagation"],
        "evaluation": "Previously inspected correlated diagnostic sets, real and synthetic separated; U excluded, missing/invalid/abstention retain full denominators. No held-out/generalization or full-corpus-recall claim."}
    write(out / "protocol.json", protocol)
    write(out / "manifest.json", {"code": codes, "files": {
        str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    verify(out, model, encoder)
    from report_edge_granularity import report
    report(out)
    print(json.dumps({"datasets": protocol["datasets"], "embedding_texts": len(texts),
                      "views": {d: {a: x["views"] for a, x in arms.items()} for d, arms in view_stats.items()}}, indent=2), flush=True)


def validate_vectors(vectors, count):
    if vectors.ndim != 2 or vectors.shape[0] != count or not vectors.shape[1]:
        raise ValueError("Embedding row/dimension mismatch")
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-3):
        raise ValueError("Expected finite normalized embeddings")


def embed(out, encoder):
    verify(out, encoder=encoder)
    vector_path = out / "embedding_vectors.npy"
    texts = rows(out / "embedding_texts.jsonl")
    if (out / "embedding_manifest.json").exists():
        validate_vectors(np.load(vector_path, allow_pickle=False), len(texts))
        print("Verified existing embeddings; no model reload", flush=True)
        return
    if vector_path.exists():
        raise ValueError("Uncommitted vector artifact exists; inspect instead of overwriting")
    tokenizer = encoders.load_tokenizer(encoder, "left")
    lengths = [len(tokenizer(t["text"], add_special_tokens=True, truncation=False)["input_ids"]) for t in texts]
    if max(lengths) > 512:
        raise ValueError("Frozen representation exceeds 512 tokens; do not truncate or silently change this experiment")
    vectors, execution = encoders.embed([t["text"] for t in texts], encoder, 6, 512, "cuda", "last_token", "left")
    validate_vectors(vectors, len(texts))
    temporary = out / "embedding_vectors.pending.npy"
    np.save(temporary, vectors)
    temporary.replace(vector_path)
    write(out / "embedding_execution.json", {**execution, "job_id": os.environ.get("SLURM_JOB_ID"),
        "input_rows": len(texts), "max_input_tokens": max(lengths), "truncated_inputs": 0,
        "encoder_identity": encoder_identity(encoder)})
    write(out / "embedding_manifest.json", {"files": {
        name: sha(out / name) for name in ("embedding_vectors.npy", "embedding_texts.jsonl", "embedding_execution.json", "manifest.json")}})
    print("Embeddings completed and frozen", flush=True)


def rank_pairs(views, vectors, budget):
    by_node = defaultdict(list)
    for view in views:
        by_node[view["node_id"]].append(view)
    ranked = []
    for a, b in itertools.combinations(sorted(by_node), 2):
        av = np.stack([vectors[v["view_id"]] for v in by_node[a]])
        bv = np.stack([vectors[v["view_id"]] for v in by_node[b]])
        score = float((av @ bv.T).max())
        ranked.append({"source": a, "target": b, "score": score})
    ranked.sort(key=lambda x: (-x["score"], x["source"], x["target"]))
    for index, item in enumerate(ranked, 1):
        item.update(rank=index, selected=index <= budget)
    return ranked


def matched_entry(pair, matches, view_by_id, nodes):
    # Deliberately build a new prompt task instead of carrying original full text.
    task = {"task_id": pair["task"]["task_id"], "candidate_matches": []}
    entry = {"task": task, "images": [], "image_sha256": [], "lookups": {},
             "contexts": {"A": [], "B": []}, "routing": {"A": "prose", "B": "prose", "group": "prose"}}
    assigned = {"A": {}, "B": {}}
    for side in ("A", "B"):
        task[side] = {"node_id": pair["task"][side]["node_id"], "evidence": []}
        entry["lookups"][side] = {}
    for match in matches:
        shown = {}
        for side in ("A", "B"):
            view = view_by_id[match[side + "_view_id"]]
            if view["node_id"] != task[side]["node_id"]:
                raise ValueError("Matched source ownership mismatch")
            context = granular.context_for_view(view, nodes)
            key = (context["member_id"], context["char_start"], context["char_end"])
            if key not in assigned[side]:
                eid = side + ":E%03d" % len(assigned[side])
                assigned[side][key] = eid
                entry["lookups"][side][eid] = context
                task[side]["evidence"].append({"evidence_id": eid, "kind": "ORIGINAL_TEXT",
                    "text": routed.render_readable(context["quote"]), "image_number": None})
            shown[side + "_evidence_id"] = assigned[side][key]
            shown[side + "_focus"] = routed.render_readable(view["quote"])
        task["candidate_matches"].append(shown)
    if not matches or len(matches) > TOP_MATCHES:
        raise ValueError("Expected one or two source matches per task")
    entry["prompt"] = routed.gate.prompt(task) + routed.POLICY + json.dumps(entry["contexts"]) + MATCH_POLICY
    entry["inference_key"] = routed.inference_key(entry)
    entry["matching_audit"] = {"dataset": pair["dataset"], "matches": matches,
        "context_words": {s: sum(len(a["quote"].split()) for a in entry["lookups"][s].values()) for s in ("A", "B")}}
    return entry


def match(out, model):
    verify(out, model)
    if not (out / "embedding_manifest.json").exists():
        raise ValueError("Embedding stage must finish first")
    if (out / "matching_manifest.json").exists():
        print("Verified existing matches and verifier prompts", flush=True)
        return
    if (out / "verifier/cache.jsonl").exists() or (out / "verifier/manifest.json").exists():
        raise ValueError("Uncommitted/already-frozen verifier state; do not silently rebuild")
    texts = rows(out / "embedding_texts.jsonl")
    matrix = np.load(out / "embedding_vectors.npy", allow_pickle=False)
    validate_vectors(matrix, len(texts))
    encoded = {row["text_id"]: matrix[i] for i, row in enumerate(texts)}
    nodes = {n["id"]: n for n in rows(out / "nodes.jsonl")}
    pairs = rows(out / "pairs.jsonl")
    planned = {a: [] for a in VERIFIER_ARMS}
    all_matching = []
    for dataset in SOURCES:
        for arm in ARMS:
            views = rows(out / dataset / arm / "views.jsonl")
            by_id = {v["view_id"]: v for v in views}
            vectors = {v["view_id"]: encoded[v["text_id"]] for v in views}
            ranked = rank_pairs(views, vectors, BUDGETS[dataset])
            ranks = {(x["source"], x["target"]): x for x in ranked}
            by_node = defaultdict(list)
            for v in views:
                by_node[v["node_id"]].append(v)
            matching = []
            for pair in (p for p in pairs if p["dataset"] == dataset):
                a, b = (pair["task"][s]["node_id"] for s in ("A", "B"))
                best = granular.top_matches(by_node[a], by_node[b], vectors, limit=TOP_MATCHES)
                record = {"task_id": pair["task"]["task_id"], "matches": best, **ranks[tuple(sorted((a, b)))]}
                matching.append(record)
                planned[ARM_MAP[arm]].append(matched_entry(pair, best, by_id, nodes))
            folder = out / "matching" / dataset / arm
            jsonl(folder / "rankings.jsonl", ranked)
            jsonl(folder / "pairs.jsonl", matching)
            all_matching.extend([folder / "rankings.jsonl", folder / "pairs.jsonl"])
    # Iteration orders must align for interleaved resumable inference.
    task_order = [p["task"]["task_id"] for p in pairs]
    for arm, entries in planned.items():
        by_task = {e["task"]["task_id"]: e for e in entries}
        planned[arm] = [by_task[t] for t in task_order]
        jsonl(out / "verifier" / arm / "inputs.jsonl", planned[arm])
    jsonl(out / "verifier/reference.jsonl", rows(out / "references.jsonl"))
    protocol = read(out / "protocol.json")
    write(out / "verifier/protocol.json", {"experiment": protocol["experiment"], "source_root": str(ROOT),
        "model": str(model), "model_config_sha256": protocol["model_config_sha256"],
        "system": routed.SYSTEM, "arms": list(VERIFIER_ARMS), "parent_manifest_sha256": sha(out / "manifest.json"),
        "embedding_manifest_sha256": sha(out / "embedding_manifest.json"),
        "matching_files_sha256": {str(p.relative_to(out)): sha(p) for p in all_matching},
        "inference": protocol["inference"], "pairs_per_arm": len(pairs),
        "unique_inferences": len({e["inference_key"] for entries in planned.values() for e in entries})})
    routed.freeze(out / "verifier")
    vm = read(out / "verifier/manifest.json")
    vm["code"].update(read(out / "manifest.json")["code"])
    write(out / "verifier/manifest.json", vm)
    write(out / "matching_manifest.json", {"files": {
        str(p.relative_to(out)): sha(p) for p in [*all_matching, out / "verifier/manifest.json", out / "embedding_manifest.json"]}})
    verify(out, model)
    from report_edge_granularity import report
    report(out)
    print(json.dumps(read(out / "verifier/protocol.json")), flush=True)


def run(out, model, minutes):
    verify(out, model)
    if not (out / "matching_manifest.json").exists():
        raise ValueError("Frozen matched prompts required before inference")
    old = routed.ARMS
    try:
        routed.ARMS = VERIFIER_ARMS
        routed.run(out / "verifier", model, ROOT, minutes)
    finally:
        routed.ARMS = old
    from report_edge_granularity import report
    return report(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "verify", "embed", "match", "run", "report"))
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--encoder", type=Path, default=ENCODER)
    parser.add_argument("--model", type=Path, default=routed.gate.MODEL)
    parser.add_argument("--minutes", type=int, default=52)
    args = parser.parse_args()
    out, encoder, model = args.output.resolve(), args.encoder.resolve(), args.model.resolve()
    if args.stage == "prepare":
        prepare(out, encoder, model)
    elif args.stage == "verify":
        verify(out, model, encoder)
        print("Frozen code, sources, models and any completed stage artifacts verified")
    elif args.stage == "embed":
        embed(out, encoder)
    elif args.stage == "match":
        match(out, model)
    elif args.stage == "run":
        run(out, model, args.minutes)
    else:
        verify(out)
        from report_edge_granularity import report
        report(out)
