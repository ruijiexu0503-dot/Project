#!/usr/bin/env python3
"""Query-driven embedding of frozen, query-independent VL-DocIR edges.

Stages are isolated and resumable:
  prepare  - freeze the semantic G0 graph and source-addressable endpoint spans
  describe - generate open relation descriptions without queries or qrels
  embed    - encode queries, pair text, pair+description text and endpoints in 8B space
  retrieve - construct matched A/B/C/D/E page candidates and shared reranker inputs
  report   - rank with completed shared BGE scores, then open gold and evaluate

Historical inputs are read-only.  Edge similarity proposes pages; it is never
added to final page scores and never licenses evidence propagation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import fcntl
import hashlib
import json
import math
from pathlib import Path
import shutil
from time import monotonic

import numpy as np

import compare_edge_embedding_models as encoder
import edge_embedding_records as records
import bounded_edge_descriptions as bounded
import sentence_edge_descriptions as sentence
import query_edge_gate as old_gate
import run_query_edge_repair as old_query
from run_node_context_edges import ROOT, jsonl, read, rows, sha, write


SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
ROLE_AUDIT = ROOT / "EvidenceNet/output/query_edge_repair_v2_20261023/role_audit.json"
GATE_SOURCE = (ROOT / "migration/horeka-query-edge-repair-20261023/"
               "results_5209174_20261025T013046Z_ElcFUQSl/EvidenceNet/output/"
               "query_edge_repair_v2_20261023")
MODEL = ROOT / "EvidenceNet/models/Qwen3-Embedding-8B"
QWEN = ROOT / "external/models/Qwen3.5-35B-A3B"
OUT = ROOT / "EvidenceNet/output/vldocir_edge_embedding_v1_20261025"
ARMS = ("A_node", "B_current", "C_pair", "D_relation", "E_endpoint")
CORE = 10
BUDGET = 20
MAX_EDGES_SCANNED = 100
QUERY_INSTRUCTION = "Instruct: Retrieve document-edge evidence useful for answering the query\nQuery: "
DESCRIPTION_TOKENS = 64
ENDPOINT_TOKENS = 192


def code_files() -> list[Path]:
    return [Path(__file__), Path(records.__file__), Path(bounded.__file__), Path(sentence.__file__), Path(encoder.__file__),
            Path(old_query.__file__), Path(old_gate.__file__),
            Path(__file__).with_name("run_cached_query_reranker.py"),
            Path(__file__).with_name("evaluate_vldocir.py"),
            Path(__file__).with_name("evaluate_vldocir_ap.py")]


def source_files() -> list[Path]:
    return [SOURCE / "nodes.jsonl", SOURCE / "graph/related.jsonl", ROLE_AUDIT,
            SOURCE / "search/query_window_scores.npy", SOURCE / "search/encoding.json",
            TRACE / "queries.jsonl", TRACE / "units.jsonl", TRACE / "windows.jsonl",
            TRACE / "window_tokens.jsonl", GATE_SOURCE / "manifest.json",
            GATE_SOURCE / "gate_inputs.jsonl", GATE_SOURCE / "gate_predictions.jsonl",
            GATE_SOURCE / "query_contexts.jsonl"]


def _description_contract(out: Path):
    policy = read(out / "protocol.json").get("description", {}).get("policy", "legacy")
    if policy not in ("legacy", bounded.PROFILE, sentence.PROFILE):
        raise ValueError("unknown description policy: " + str(policy))
    return {"legacy": records, bounded.PROFILE: bounded, sentence.PROFILE: sentence}[policy]


def prepare(out: Path, model: Path, edge_limit: int | None = None,
            description_policy: str = "legacy") -> dict:
    if out.exists():
        raise ValueError("fresh output required")
    if description_policy not in ("legacy", bounded.PROFILE, sentence.PROFILE):
        raise ValueError("unknown description policy")
    contract = {"legacy": records, bounded.PROFILE: bounded, sentence.PROFILE: sentence}[description_policy]
    for path in source_files() + [model / "config.json", model / "tokenizer.json"]:
        if not path.is_file():
            raise ValueError("missing frozen input: " + str(path))
    nodes_list = rows(SOURCE / "nodes.jsonl")
    nodes = {n["id"]: n for n in nodes_list}
    if len(nodes) != len(nodes_list):
        raise ValueError("duplicate node IDs")
    audit = read(ROLE_AUDIT)
    routes = {key: value["route"] for key, value in audit["edges"].items()}
    edges = rows(SOURCE / "graph/related.jsonl")
    graph = [records.build_record(e, nodes, routes.get(e["task_id"], "missing"))
             for e in edges if routes.get(e["task_id"]) == "semantic"]
    if len(edges) != 213 or len(graph) != 187:
        raise ValueError(f"expected frozen 213/187 graph, got {len(edges)}/{len(graph)}")
    graph.sort(key=lambda x: x["edge_id"])
    if edge_limit is not None:
        if edge_limit < 1 or edge_limit > len(graph):
            raise ValueError("edge_limit must be within the semantic graph")
        graph = graph[:edge_limit]
    jsonl(out / "edge_records.jsonl", graph)
    jsonl(out / "description_inputs.jsonl", [{"edge_id": r["edge_id"],
        "input_sha256": r["input_sha256"], "prompt_sha256": records.digest(
            contract.make_description_prompt(r)), "input": contract.description_input(r)} for r in graph])
    shutil.copyfile(TRACE / "queries.jsonl", out / "queries.jsonl")
    write(out / "protocol.json", {
        "experiment": "vldocir_edge_embedding_v1", "graph": "G0 semantic proposals",
        "graph_edges": len(graph), "historical_related": len(edges), "arms": list(ARMS),
        "smoke_subset": edge_limit is not None,
        "candidate_policy": {"dense_core": CORE, "page_budget": BUDGET,
                             "max_edges_scanned": MAX_EDGES_SCANNED},
        "embedding": {"model": str(model.resolve()), "pooling": "last_token",
            "padding_side": "left", "max_length": 512, "normalize": "L2",
            "query_instruction": QUERY_INSTRUCTION, "endpoint_tokens": ENDPOINT_TOKENS,
            "description_tokens": DESCRIPTION_TOKENS if contract is records else None,
            "description_budget": "fixed_prefix" if contract is records else "complete_input_512_no_relation_truncation",
            "pair_orders": ["AB", "BA"]},
        "description": {"policy": description_policy, "query_independent": True, "qrels_visible": False,
            "semantic_truth_verified": False,
            "fallback": "pair text; edge remains in all controlled arms"},
        "reranking": "same two frozen 0.6B-hit windows per candidate page; shared BGE scores; max window score",
        "edge_score_use": "candidate discovery only; never a page bonus or evidence propagation",
        "development_limit": "Previously inspected 24-query/518-page pilot; regression only",
    })
    model_metadata = [model / "config.json", model / "tokenizer.json"]
    if contract is not records and (model / "tokenizer_config.json").is_file():
        model_metadata.append(model / "tokenizer_config.json")
    manifest = {"sources": {str(p.relative_to(ROOT)): sha(p) for p in source_files()},
                "model_small_files": {p.name: sha(p) for p in
                    model_metadata},
                "prepared": {name: sha(out / name) for name in
                    ("edge_records.jsonl", "description_inputs.jsonl", "queries.jsonl", "protocol.json")},
                "code": {p.name: sha(p) for p in code_files()}}
    write(out / "manifest.json", manifest)
    write(out / "status.json", {"stage": "prepared", "description_processed": 0,
                                  "description_total": len(graph)})
    return {"prepared": True, "edges": len(graph), "queries": len(rows(out / "queries.jsonl"))}


def check_prepared(out: Path, *, code: bool = True) -> None:
    manifest = read(out / "manifest.json")
    for name, digest in manifest["sources"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("changed source: " + name)
    for name, digest in manifest["prepared"].items():
        if sha(out / name) != digest:
            raise ValueError("changed prepared input: " + name)
    if _description_contract(out) is not records:
        model = Path(read(out / "protocol.json")["embedding"]["model"])
        for name, digest in manifest["model_small_files"].items():
            if sha(model / name) != digest:
                raise ValueError("changed embedding model metadata: " + name)
    if code:
        for name, digest in manifest["code"].items():
            path = next((p for p in code_files() if p.name == name), None)
            if path is None or sha(path) != digest:
                raise ValueError("changed code: " + name)


def _description_images(record: dict) -> list[str]:
    result = []
    for side in ("A", "B"):
        endpoint = record["endpoints"][side]
        visual = any("VISUAL" in s["source_kind"] for s in endpoint["spans"])
        path = endpoint.get("source_image_path")
        if visual and isinstance(path, str) and Path(path).is_file() and path not in result:
            result.append(path)
    return result


def describe(out: Path, model: Path, minutes: float, max_items: int | None = None) -> dict:
    check_prepared(out)
    contract = _description_contract(out)
    tokenizer = None
    if contract is not records:
        from transformers import AutoTokenizer
        embedding_model = read(out / "protocol.json")["embedding"]["model"]
        tokenizer = AutoTokenizer.from_pretrained(embedding_model, local_files_only=True,
            trust_remote_code=True, padding_side="left")

    def validate(result, record):
        if contract is not records:
            _, _, common = _endpoint_encoding(record, tokenizer)
            return contract.validate_encoding_budget(result, record, tokenizer, list(common.values()))
        return contract.validate_description(result, record)

    if minutes <= 0:
        raise ValueError("minutes must be positive")
    lock_path = out / ".describe.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        entries = rows(out / "edge_records.jsonl")
        path = out / "description_predictions.jsonl"
        existing = rows(path) if path.exists() else []
        if len({x["edge_id"] for x in existing}) != len(existing):
            raise ValueError("duplicate description predictions")
        lookup = {r["edge_id"]: r for r in entries}
        for prediction in existing:
            record = lookup.get(prediction["edge_id"])
            if record is None or prediction["input_sha256"] != record["input_sha256"]:
                raise ValueError("stale description prediction")
            if contract is not records and (
                prediction.get("description_policy") != contract.PROFILE or
                prediction.get("prompt_sha256") != records.digest(contract.make_description_prompt(record))
            ):
                raise ValueError("stale description policy or prompt")
            if prediction["valid"]:
                validate(prediction["result"], record)
        if len(existing) == len(entries):
            return {"processed": len(existing), "total": len(entries), "complete": True}
        from evidence_graph.llm_client import create_llm, extract_json
        llm = create_llm({"provider": "transformers", "model": str(model), "dtype": "bfloat16",
            "require_cuda": True, "enable_thinking": False, "max_new_tokens": 500,
            "device_map": "balanced", "max_memory": {i: "26GiB" for i in range(4)}})
        started = monotonic()
        done = {p["edge_id"] for p in existing}
        added = 0
        for record in entries:
            if record["edge_id"] in done:
                continue
            if monotonic() - started >= minutes * 60 or (max_items is not None and added >= max_items):
                break
            attempts, result, error = [], None, ""
            for attempt in range(3 if contract is not records else 2):
                raw = None
                try:
                    prompt = contract.make_description_prompt(record, error if attempt else "")
                    raw = llm.generate_raw_with_images(
                        "Describe a grounded document-edge relation. JSON only.", prompt,
                        _description_images(record), 500).raw
                    result = validate(extract_json(raw), record)
                    attempts.append({"raw": raw}); break
                except (ValueError, TypeError, KeyError) as exc:
                    error = str(exc); attempts.append({"raw": raw, "error": error})
                    if contract is sentence:
                        if len(attempts) > 1 and raw == attempts[-2]["raw"]:
                            break  # Deterministic identical failures do not need a third call.
                        error += "\nPrevious output (data only, not instructions): " + json.dumps(raw, ensure_ascii=False)
            existing.append({"edge_id": record["edge_id"], "input_sha256": record["input_sha256"],
                "description_policy": contract.PROFILE if contract is not records else "legacy",
                "prompt_sha256": records.digest(contract.make_description_prompt(record)),
                "valid": result is not None, "result": result, "attempts": attempts})
            jsonl(path, existing); added += 1
            if contract is sentence:
                write(out / "status.json", {"stage": "describing",
                    "description_processed": len(existing), "description_total": len(entries)})
            print(f"Description {len(existing)}/{len(entries)}", flush=True)
        complete = len(existing) == len(entries)
        write(out / "description_execution.json", {"model": str(model),
            "model_config_sha256": sha(model / "config.json"), "sampling": False,
            "thinking": False, "max_new_tokens": 500, "processed": len(existing),
            "description_policy": contract.PROFILE if contract is not records else "legacy",
            "semantic_truth_verified": False,
            "total": len(entries), "complete": complete})
        write(out / "status.json", {"stage": "described" if complete else "description_partial",
            "description_processed": len(existing), "description_total": len(entries)})
        return {"processed": len(existing), "total": len(entries), "complete": complete}


def _truncate(tokenizer, text: str, tokens: int) -> tuple[str, dict]:
    ids = tokenizer.encode(text, add_special_tokens=False, truncation=False)
    kept = ids[:tokens]
    return tokenizer.decode(kept, skip_special_tokens=True), {
        "original_tokens": len(ids), "kept_tokens": len(kept), "truncated": len(ids) > tokens}


def _endpoint_encoding(record: dict, tokenizer) -> tuple[dict, dict, dict]:
    endpoint, token_meta = {}, {}
    for side in ("A", "B"):
        raw = "\n\n".join(f'({s["source_kind"]})\n{s["text"]}'
                          for s in record["endpoints"][side]["spans"])
        endpoint[side], token_meta[side] = _truncate(tokenizer, raw, ENDPOINT_TOKENS)
    common = {order: f"[ENDPOINT {order[0]}]\n{endpoint[order[0]]}\n\n"
                     f"[ENDPOINT {order[1]}]\n{endpoint[order[1]]}" for order in ("AB", "BA")}
    return endpoint, token_meta, common


def _encoding_rows(out: Path, tokenizer) -> tuple[list[dict], list[dict], list[dict]]:
    contract = _description_contract(out)
    base = rows(out / "edge_records.jsonl")
    prediction_rows = rows(out / "description_predictions.jsonl")
    predictions = {p["edge_id"]: p for p in prediction_rows}
    if len(predictions) != len(prediction_rows):
        raise ValueError("duplicate description predictions")
    if set(predictions) != {r["edge_id"] for r in base}:
        raise ValueError("descriptions incomplete")
    pair_rows, relation_rows, endpoint_rows = [], [], []
    for record in base:
        prediction = predictions[record["edge_id"]]
        if prediction["input_sha256"] != record["input_sha256"]:
            raise ValueError("stale description input")
        result = prediction["result"] if prediction["valid"] else None
        if contract is not records:
            if prediction.get("description_policy") != contract.PROFILE or prediction.get("prompt_sha256") != records.digest(contract.make_description_prompt(record)):
                raise ValueError("stale description policy or prompt")
            if result is not None:
                result = contract.validate_description(result, record)
        record = records.attach_description(record, result)
        endpoint, token_meta, common_texts = _endpoint_encoding(record, tokenizer)
        for side in ("A", "B"):
            endpoint_rows.append({"id": record["edge_id"] + ":" + side, "edge_id": record["edge_id"],
                "side": side, "text": endpoint[side], "token_meta": token_meta[side]})
        description = record["relation_description"]["text"]
        limitations = record["relation_description"]["limitations"]
        relation = (description + (" Limitations: " + limitations if limitations else "")).strip()
        if contract is not records:
            if result is not None:
                contract.validate_encoding_budget(result, record, tokenizer, list(common_texts.values()))
            relation = contract.render_relation(result) if result is not None else ""
            count = len(tokenizer.encode(relation, add_special_tokens=False, truncation=False)) if relation else 0
            relation_meta = {"original_tokens": count, "kept_tokens": count, "truncated": False}
        else:
            relation, relation_meta = _truncate(tokenizer, relation, DESCRIPTION_TOKENS) if relation else ("", {
                "original_tokens": 0, "kept_tokens": 0, "truncated": False})
        for order in ("AB", "BA"):
            common = common_texts[order]
            pair_rows.append({"id": record["edge_id"] + ":" + order, "edge_id": record["edge_id"],
                "order": order, "text": common, "endpoint_text_sha256": records.digest(endpoint),
                "endpoint_token_meta": token_meta})
            relation_text = common + ("\n\n[RELATION]\n" + relation if relation else "")
            relation_rows.append({"id": record["edge_id"] + ":" + order, "edge_id": record["edge_id"],
                "order": order, "text": relation_text, "endpoint_text_sha256": records.digest(endpoint),
                "description_status": record["relation_description"]["status"],
                "description_policy": contract.PROFILE if contract is not records else "legacy",
                "relation_appended": bool(relation), "semantic_truth_verified": False,
                "relation_token_meta": relation_meta})
    return pair_rows, relation_rows, endpoint_rows


def embed(out: Path, model: Path, device: str) -> dict:
    check_prepared(out)
    if _description_contract(out) is not records and model.resolve() != Path(read(out / "protocol.json")["embedding"]["model"]).resolve():
        raise ValueError("embedding model differs from frozen description tokenizer")
    if (out / "embedding_manifest.json").exists():
        check_embeddings(out)
        manifest = read(out / "embedding_manifest.json")
        if manifest["model"] != str(model.resolve()):
            raise ValueError("embedding checkpoint belongs to a different model path")
        return {"status": "embedding_already_complete",
                "shapes": {k: v["shape"] for k, v in manifest["vectors"].items()}}
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True, trust_remote_code=True,
                                               padding_side="left")
    pair, relation, endpoints = _encoding_rows(out, tokenizer)
    queries = [{"id": q["question_id"], "text": QUERY_INSTRUCTION + q["question"]}
               for q in rows(out / "queries.jsonl")]
    jsonl(out / "edge_inputs_pair.jsonl", pair)
    jsonl(out / "edge_inputs_relation.jsonl", relation)
    jsonl(out / "endpoint_inputs.jsonl", endpoints)
    jsonl(out / "query_embedding_inputs.jsonl", queries)
    groups = [("query", queries), ("pair", pair), ("relation", relation), ("endpoint", endpoints)]
    all_rows = [row for _, group in groups for row in group]
    too_long = [(row["id"], len(tokenizer.encode(row["text"], add_special_tokens=False,
                                                 truncation=False))) for row in all_rows]
    too_long = [item for item in too_long if item[1] > 512]
    if too_long:
        raise ValueError("encoding input exceeds frozen 512-token budget: " + str(too_long[:5]))
    vectors, execution = encoder.embed([r["text"] for r in all_rows], model, 6, 512, device,
                                        "last_token", "left")
    offset = 0; shapes = {}
    for name, group in groups:
        block = vectors[offset:offset + len(group)]; offset += len(group)
        np.save(out / f"{name}_vectors.npy", block); shapes[name] = list(block.shape)
    weights = sorted(p for p in model.iterdir() if p.suffix in {".safetensors", ".bin"})
    manifest = {"model": str(model.resolve()), "model_config_sha256": sha(model / "config.json"),
        "description_predictions_sha256": sha(out / "description_predictions.jsonl"),
        "model_index_sha256": sha(model / "model.safetensors.index.json")
            if (model / "model.safetensors.index.json").is_file() else None,
        "weight_inventory": {p.name: {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
                             for p in weights},
        "settings": {"pooling": "last_token", "padding_side": "left", "max_length": 512,
                     "normalize": "L2", "query_instruction": QUERY_INSTRUCTION},
        "inputs": {name: sha(out / filename) for name, filename in
            (("query", "query_embedding_inputs.jsonl"), ("pair", "edge_inputs_pair.jsonl"),
             ("relation", "edge_inputs_relation.jsonl"), ("endpoint", "endpoint_inputs.jsonl"))},
        "vectors": {name: {"file": f"{name}_vectors.npy", "sha256": sha(out / f"{name}_vectors.npy"),
                            "shape": shapes[name]} for name, _ in groups}, "execution": execution}
    write(out / "embedding_manifest.json", manifest)
    write(out / "status.json", {"stage": "embedded", "description_processed": len(pair) // 2,
                                  "description_total": len(pair) // 2})
    return {"embedded": len(all_rows), "shapes": shapes}


def check_embeddings(out: Path) -> None:
    manifest = read(out / "embedding_manifest.json")
    if "description_predictions_sha256" in manifest and sha(out / "description_predictions.jsonl") != manifest["description_predictions_sha256"]:
        raise ValueError("changed description predictions after embedding")
    files = {"query": "query_embedding_inputs.jsonl", "pair": "edge_inputs_pair.jsonl",
             "relation": "edge_inputs_relation.jsonl", "endpoint": "endpoint_inputs.jsonl"}
    for name, filename in files.items():
        if sha(out / filename) != manifest["inputs"][name]:
            raise ValueError("changed embedding input: " + name)
        info = manifest["vectors"][name]
        path = out / info["file"]
        if sha(path) != info["sha256"]:
            raise ValueError("changed vectors: " + name)
        values = np.load(path, allow_pickle=False)
        if list(values.shape) != info["shape"] or not np.isfinite(values).all():
            raise ValueError("invalid vectors: " + name)
        norms = np.linalg.norm(values, axis=1)
        if not np.allclose(norms, 1, atol=2e-4):
            raise ValueError("vectors are not L2 normalized: " + name)


def _global_candidates(direct: list[tuple], graph: list[dict], scores: np.ndarray) -> tuple[list[tuple], list[dict]]:
    if len(graph) != len(scores):
        raise ValueError("edge score length mismatch")
    rank = {p: i for i, p in enumerate(direct)}
    selected = list(direct[:CORE]); seen = set(selected); path = []
    ordered = sorted(range(len(graph)), key=lambda i: (-float(scores[i]), graph[i]["edge_id"]))
    for edge_rank, index in enumerate(ordered[:min(MAX_EDGES_SCANNED, len(ordered))], 1):
        edge = graph[index]
        pages = [(edge["endpoints"][s]["document_id"], edge["endpoints"][s]["page_number"])
                 for s in ("A", "B")]
        pages = sorted(dict.fromkeys(pages), key=lambda p: (rank.get(p, 10**9), p))
        action = []
        for page in pages:
            reason = "already_selected" if page in seen else "budget_full" if len(selected) >= BUDGET else "added"
            if reason == "added": selected.append(page); seen.add(page)
            action.append({"page": page, "decision": reason, "direct_rank": rank.get(page, 10**9) + 1})
        path.append({"edge_rank": edge_rank, "edge_id": edge["edge_id"],
                     "edge_score": float(scores[index]), "endpoints": action})
    for page in direct:
        if len(selected) >= BUDGET: break
        if page not in seen: selected.append(page); seen.add(page)
    if len(selected) != BUDGET or len(set(selected)) != BUDGET:
        raise ValueError("candidate page budget failure")
    return selected, path


def _b_candidates(qid: str, direct: list[tuple], gate_paths: dict, gate_predictions: dict,
                  gate_contexts: dict) -> tuple[list[tuple], list[dict]]:
    ids = gate_contexts[qid]["path_ids"]
    pp = [gate_paths[i] for i in ids]
    accepted = {i for i in ids if gate_paths[i]["source_role_route"] == "semantic" and
        gate_predictions[i]["valid"] and gate_predictions[i]["result"]["role"] in old_gate.NAVIGATION_ROLES}
    selected = old_query.select_candidates(direct, pp, accepted, budget=BUDGET, core_size=CORE)
    return selected, [{"path_id": i, "edge_id": gate_paths[i]["edge_id"],
                       "accepted": i in accepted} for i in ids]


def retrieve(out: Path) -> dict:
    check_prepared(out); check_embeddings(out)
    graph = rows(out / "edge_records.jsonl")
    queries = rows(out / "queries.jsonl")
    contexts = {q["question_id"]: q for q in rows(GATE_SOURCE / "query_contexts.jsonl")}
    gate_paths = {p["id"]: p for p in rows(GATE_SOURCE / "gate_inputs.jsonl")}
    gate_predictions = {p["id"]: p for p in rows(GATE_SOURCE / "gate_predictions.jsonl")}
    qvec = np.load(out / "query_vectors.npy", allow_pickle=False)
    pair = np.load(out / "pair_vectors.npy", allow_pickle=False).reshape(len(graph), 2, -1)
    relation = np.load(out / "relation_vectors.npy", allow_pickle=False).reshape(len(graph), 2, -1)
    endpoint = np.load(out / "endpoint_vectors.npy", allow_pickle=False).reshape(len(graph), 2, -1)
    if len(qvec) != len(queries): raise ValueError("query vector mismatch")
    selections, traces, union = [], [], defaultdict(set)
    for qi, query in enumerate(queries):
        qid = query["question_id"]
        context = contexts[qid]; direct = [tuple(x) for x in context["direct_ranking"]]
        scores = {
            "C_pair": np.maximum(pair[:, 0] @ qvec[qi], pair[:, 1] @ qvec[qi]),
            "D_relation": np.maximum(relation[:, 0] @ qvec[qi], relation[:, 1] @ qvec[qi]),
            "E_endpoint": np.maximum(endpoint[:, 0] @ qvec[qi], endpoint[:, 1] @ qvec[qi]),
        }
        arms = {"A_node": direct[:BUDGET]}; arm_paths = {"A_node": []}
        arms["B_current"], arm_paths["B_current"] = _b_candidates(
            qid, direct, gate_paths, gate_predictions, contexts)
        for arm in ("C_pair", "D_relation", "E_endpoint"):
            arms[arm], arm_paths[arm] = _global_candidates(direct, graph, scores[arm])
        for arm, pages in arms.items():
            union[qid].update(pages)
            selections.append({"question_id": qid, "arm": arm, "pages": pages,
                "changed_vs_dense20": set(pages) != set(direct[:BUDGET])})
            traces.append({"question_id": qid, "question": query["question"], "arm": arm,
                "entry": "global_edge_index" if arm in {"C_pair", "D_relation", "E_endpoint"}
                         else "historical_seed_gate" if arm == "B_current" else "dense_only",
                "direct_top20": direct[:BUDGET], "selected_pages": pages, "paths": arm_paths[arm]})
    jsonl(out / "query_candidates.jsonl", selections); jsonl(out / "search_paths.jsonl", traces)
    # Shared frozen page evidence: best two 0.6B-hit windows for every union page.
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(ROOT / "EvidenceNet/models/Qwen3-Embedding-0.6B/tokenizer.json"))
    units = rows(TRACE / "units.jsonl"); windows = rows(TRACE / "windows.jsonl")
    window_tokens = rows(TRACE / "window_tokens.jsonl")
    similarities = np.load(SOURCE / "search/query_window_scores.npy", allow_pickle=False)
    rerank = {}; evidence_rows = []
    for qi, query in enumerate(queries):
        qid = query["question_id"]; per_page = defaultdict(list)
        for wi, window in enumerate(windows):
            unit = units[window["unit_input_line"] - 1]
            page = (unit["document_id"], str(unit["page_number"]))
            per_page[page].append((float(similarities[qi, wi]), wi))
        mapping = {}
        for page in sorted(union[qid]):
            ids = []
            for _, wi in sorted(per_page[page], key=lambda x: (-x[0], x[1]))[:2]:
                rid = records.digest([qid, wi]); ids.append(rid)
                rerank[rid] = {"id": rid, "query": query["question"],
                    "text": tokenizer.decode(window_tokens[wi]["input_ids"], skip_special_tokens=True),
                    "question_id": qid, "window_input_line": wi + 1, "page": page}
            if not ids: raise ValueError("candidate page has no frozen window")
            mapping[json.dumps(page)] = ids
        evidence_rows.append({"question_id": qid, "page_reranker_ids": mapping})
    # Public reranker contract accepts exactly id/query/text; provenance is separate.
    jsonl(out / "reranker_inputs.jsonl", [{k: row[k] for k in ("id", "query", "text")}
                                           for row in rerank.values()])
    jsonl(out / "reranker_provenance.jsonl", list(rerank.values()))
    jsonl(out / "page_reranker_ids.jsonl", evidence_rows)
    changed = Counter(row["arm"] for row in selections if row["changed_vs_dense20"])
    write(out / "retrieval_summary.json", {"queries": len(queries), "arms": list(ARMS),
        "candidate_set_changed_queries": {a: changed[a] for a in ARMS},
        "reranker_tasks": len(rerank), "candidate_budget": BUDGET})
    write(out / "status.json", {"stage": "candidates_ready", "reranker_processed": 0,
                                  "reranker_total": len(rerank)})
    return read(out / "retrieval_summary.json")


def report(out: Path) -> dict:
    check_prepared(out); check_embeddings(out)
    from evaluate_vldocir import evaluate
    from evaluate_vldocir_ap import average_precision
    from run_cached_query_reranker import load_inputs, load_scores
    inputs = load_inputs(out / "reranker_inputs.jsonl")
    scored = load_scores(out / "reranker_scores.jsonl", inputs)
    if len(scored) != len(inputs):
        status = {"stage": "reranker_partial", "reranker_processed": len(scored),
                  "reranker_total": len(inputs), "complete": False}
        write(out / "status.json", status); return status
    score = {r["id"]: r["score"] for r in scored}
    queries = rows(out / "queries.jsonl")
    contexts = {q["question_id"]: q for q in rows(GATE_SOURCE / "query_contexts.jsonl")}
    selections = {(r["question_id"], r["arm"]): [tuple(p) for p in r["pages"]]
                  for r in rows(out / "query_candidates.jsonl")}
    evidence = {r["question_id"]: r["page_reranker_ids"] for r in rows(out / "page_reranker_ids.jsonl")}
    run_rows = defaultdict(list); rankings = defaultdict(dict)
    for query in queries:
        qid = query["question_id"]; direct = [tuple(p) for p in contexts[qid]["direct_ranking"]]
        for arm in ARMS:
            chosen = selections[(qid, arm)]
            ranked = sorted(chosen, key=lambda p: (-max(score[i] for i in evidence[qid][json.dumps(p)]), p))
            ranked += [p for p in direct if p not in set(ranked)]
            rankings[arm][qid] = ranked
            run_rows[arm].extend({"question_id": qid, "document_id": p[0],
                                  "page_number": int(p[1]), "score": -i}
                                 for i, p in enumerate(ranked))
    gold = rows(TRACE / "gold_evidence.jsonl")
    g = defaultdict(set)
    for row in gold: g[row["question_id"]].add((row["document_id"], str(row["page_number"])))
    metrics, per_query = {}, {}
    by_type = {q["question_id"]: q["question_type"] for q in queries}
    for arm in ARMS:
        result = evaluate(queries, gold, run_rows[arm])
        macro = result["macro_six_types"]
        groups = defaultdict(list); details = result["per_query"]
        for qid, ranked in rankings[arm].items():
            value = average_precision(ranked, g[qid], 5); details[qid]["AP@5"] = value
            groups[by_type[qid]].append(value)
        macro["mAP@5"] = sum(sum(v) / len(v) for v in groups.values()) / len(groups)
        metrics[arm] = macro; per_query[arm] = details
        jsonl(out / "runs" / f"{arm}.jsonl", run_rows[arm])
    paired = {}
    for arm in ARMS[1:]:
        delta = [per_query[arm][qid]["AP@5"] - per_query["A_node"][qid]["AP@5"]
                 for qid in per_query[arm]]
        paired[arm] = {"control": "A_node", "AP@5_wins": sum(x > 1e-12 for x in delta),
            "AP@5_losses": sum(x < -1e-12 for x in delta), "AP@5_ties": sum(abs(x) <= 1e-12 for x in delta),
            "metric_deltas": {k: metrics[arm][k] - metrics["A_node"][k] for k in metrics[arm]}}
    description_predictions = rows(out / "description_predictions.jsonl")
    description_inputs = [r for r in rows(out / "edge_inputs_relation.jsonl") if r["order"] == "AB"]
    description_diagnostics = {
        "total": len(description_predictions),
        "invalid": sum(not r["valid"] for r in description_predictions),
        "statuses": dict(Counter(r["description_status"] for r in description_inputs)),
        "truncated": sum(r["relation_token_meta"]["truncated"] for r in description_inputs),
        "relation_appended": sum(r.get("relation_appended", "[RELATION]" in r["text"]) for r in description_inputs),
        "semantic_truth_verified": False,
    }
    result = {"complete": True, "metrics": metrics, "paired": paired, "per_query": per_query,
              "description_diagnostics": description_diagnostics,
              "protocol": read(out / "protocol.json"), "retrieval_summary": read(out / "retrieval_summary.json")}
    write(out / "results.json", result)
    lines = ["# VL-DocIR edge-embedding pilot", "", "24 inspected queries / 518 pages; regression, not held-out.", "",
        "| Arm | Recall@5 | nDCG@5 | RecallAll@5 | mAP@5 |", "| --- | ---: | ---: | ---: | ---: |"]
    for arm in ARMS:
        m = metrics[arm]; lines.append("| " + arm + " | " + " | ".join(
            f'{100*m[k]:.2f}%' for k in ("Recall@5", "nDCG@5", "RecallAll@5", "mAP@5")) + " |")
    lines += ["", "Edge cosine selects candidates only; all arms use the same BGE page scores.",
              "Open relation descriptions are query-independent retrieval metadata, not verified evidence.",
              "", "Description diagnostics: " + json.dumps(description_diagnostics, sort_keys=True)]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    write(out / "status.json", {"stage": "complete", "complete": True,
                                  "reranker_processed": len(scored), "reranker_total": len(inputs)})
    return {"complete": True, "metrics": metrics, "paired": paired}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "describe", "embed", "retrieve", "report", "check"))
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--embedding-model", type=Path, default=MODEL)
    parser.add_argument("--description-model", type=Path, default=QWEN)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--minutes", type=float, default=50)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--edge-limit", type=int,
                        help="prepare-only deterministic prefix for an isolated smoke run")
    parser.add_argument("--description-policy", choices=("legacy", bounded.PROFILE, sentence.PROFILE), default="legacy",
                        help="prepare-only: freeze the description contract for all later stages")
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == "prepare": result = prepare(out, args.embedding_model.resolve(), args.edge_limit, args.description_policy)
    elif args.stage == "describe": result = describe(out, args.description_model.resolve(), args.minutes, args.max_items)
    elif args.stage == "embed": result = embed(out, args.embedding_model.resolve(), args.device)
    elif args.stage == "retrieve": result = retrieve(out)
    elif args.stage == "report": result = report(out)
    else:
        check_prepared(out); result = {"prepared": True}
        if (out / "embedding_manifest.json").exists(): check_embeddings(out); result["embedded"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
