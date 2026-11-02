#!/usr/bin/env python3
"""Prepare and encode matched directional relation representations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

import compare_edge_embedding_models as encoder
import prepare_directional_relation_views as views_module

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = views_module.DEFAULT_OUT
DEFAULT_MODEL = ROOT / "EvidenceNet/models/Qwen3-Embedding-8B"
QUERY_INSTRUCTION = "Instruct: Rank reachable evidence-graph routes useful for answering the question\nQuery: "
ARMS = ("R1_type", "R2_open", "R3_directional", "R4_hybrid", "R5_target")


def _truncate(tokenizer, text: str, limit: int) -> tuple[str, dict[str, Any]]:
    ids = tokenizer.encode(text, add_special_tokens=False, truncation=False)
    kept = ids[:limit]
    return tokenizer.decode(kept, skip_special_tokens=True), {
        "original_tokens": len(ids), "kept_tokens": len(kept), "truncated": len(ids) > len(kept)}


def render(view: dict[str, Any], arm: str, tokenizer) -> tuple[str, dict[str, Any]]:
    if arm in {"R1_type", "R2_open"}:
        return _truncate(tokenizer, view["representations"][arm], 512)
    source, smeta = _truncate(tokenizer, view["known_source_contribution"], 192)
    target, tmeta = _truncate(tokenizer, view["target_contribution"], 192)
    relation = view["relation_statement"]
    if view.get("qualifiers"): relation += " Qualifiers: " + " ".join(view["qualifiers"])
    relation, rmeta = _truncate(tokenizer, relation, 64)
    if arm == "R5_target":
        text = "Target original evidence:\n" + target
    else:
        prefix = (f"Relation family: {view['relation_family']}.\n\n" if arm == "R4_hybrid" else "")
        text = (prefix + "Known source original evidence:\n" + source +
                "\n\nRetrieve linked target original evidence:\n" + target +
                ("\n\nSupported relation: " + relation if relation else ""))
    count = len(tokenizer.encode(text, add_special_tokens=False, truncation=False))
    if count > 512: raise ValueError(f"{view['view_id']} {arm} has {count} tokens")
    return text, {"source": smeta, "target": tmeta, "relation": rmeta, "total_tokens": count}


def prepare_inputs(out: Path, model: Path) -> dict[str, Any]:
    views_module.check(out)
    from transformers import AutoTokenizer
    tokenizer = encoder.load_tokenizer(model, "left")
    directed = views_module.rows(out / "edges_with_views.jsonl")
    queries = views_module.rows(out / "queries.jsonl")
    mappings, counts = {}, {}
    for arm in ARMS:
        rendered = []
        for view in directed:
            text, token_meta = render(view, arm, tokenizer)
            rendered.append({"id": view["view_id"], "edge_id": view["edge_id"],
                             "source_node_id": view["source_node_id"], "target_node_id": view["target_node_id"],
                             "arm": arm, "text": text, "text_sha256": views_module.digest(text),
                             "token_meta": token_meta})
        filename = f"inputs_{arm}.jsonl"; views_module.jsonl(out / filename, rendered)
        mappings[arm] = {"file": filename, "sha256": views_module.sha(out / filename), "rows": len(rendered)}
        counts[arm] = sum(row["token_meta"].get("total_tokens", row["token_meta"].get("kept_tokens", 0)) for row in rendered)
    query_rows = [{"id": q["question_id"], "text": QUERY_INSTRUCTION + q["question"]} for q in queries]
    views_module.jsonl(out / "query_embedding_inputs.jsonl", query_rows)
    manifest = {"model": str(model.resolve()), "model_config_sha256": views_module.sha(model / "config.json"),
        "view_manifest_sha256": views_module.sha(out / "relation_representation_manifest.json"),
        "settings": {"pooling": "last_token", "padding_side": "left", "max_length": 512,
                     "normalize": "L2", "query_instruction": QUERY_INSTRUCTION,
                     "source_tokens": 192, "target_tokens": 192, "relation_tokens": 64},
        "inputs": mappings,
        "query_input": {"file": "query_embedding_inputs.jsonl",
                        "sha256": views_module.sha(out / "query_embedding_inputs.jsonl"), "rows": len(query_rows)},
        "total_rendered_tokens": counts, "queries_or_gold_used_to_build_views": False}
    views_module.write(out / "encoding_input_manifest.json", manifest)
    return {"views_per_arm": len(directed), "queries": len(query_rows), "arms": list(ARMS)}


def embed(out: Path, model: Path, device: str) -> dict[str, Any]:
    manifest = json.loads((out / "encoding_input_manifest.json").read_text())
    if views_module.sha(model / "config.json") != manifest["model_config_sha256"]:
        raise ValueError("model config differs from prepared input")
    if (out / "embedding_manifest.json").exists():
        check(out); return {"already_complete": True}
    groups = [("query", views_module.rows(out / "query_embedding_inputs.jsonl"))]
    groups += [(arm, views_module.rows(out / f"inputs_{arm}.jsonl")) for arm in ARMS]
    flat = [row["text"] for _, group in groups for row in group]
    vectors, execution = encoder.embed(flat, model, 6, 512, device, "last_token", "left")
    offset, outputs = 0, {}
    for name, group in groups:
        block = vectors[offset:offset + len(group)]; offset += len(group)
        path = out / f"vectors_{name}.npy"; np.save(path, block)
        outputs[name] = {"file": path.name, "sha256": views_module.sha(path), "shape": list(block.shape)}
    result = {"encoding_input_manifest_sha256": views_module.sha(out / "encoding_input_manifest.json"),
              "model": str(model.resolve()), "prepared_model_path": manifest["model"],
              "model_relocated": manifest["model"] != str(model.resolve()),
              "outputs": outputs, "execution": execution,
              "online_llm_calls": 0, "normalized": True}
    views_module.write(out / "embedding_manifest.json", result)
    views_module.write(out / "status.json", {"stage": "embedded", "complete": True})
    check(out)
    return {"embedded": len(flat), "shapes": {k: v["shape"] for k, v in outputs.items()}}


def check(out: Path) -> None:
    views_module.check(out)
    manifest = json.loads((out / "encoding_input_manifest.json").read_text())
    for arm, item in manifest["inputs"].items():
        if views_module.sha(out / item["file"]) != item["sha256"]: raise ValueError("changed input: " + arm)
    if views_module.sha(out / manifest["query_input"]["file"]) != manifest["query_input"]["sha256"]:
        raise ValueError("changed query inputs")
    embedded = out / "embedding_manifest.json"
    if not embedded.exists():
        print("DIRECTIONAL_RELATION_ENCODING_INPUTS_OK"); return
    em = json.loads(embedded.read_text())
    if views_module.sha(out / "encoding_input_manifest.json") != em["encoding_input_manifest_sha256"]:
        raise ValueError("stale embeddings")
    for name, item in em["outputs"].items():
        path = out / item["file"]
        if views_module.sha(path) != item["sha256"]: raise ValueError("changed vectors: " + name)
        vector = np.load(path, allow_pickle=False)
        if list(vector.shape) != item["shape"] or not np.isfinite(vector).all(): raise ValueError("invalid vectors: " + name)
        if not np.allclose(np.linalg.norm(vector, axis=1), 1, atol=2e-4): raise ValueError("not normalized: " + name)
    print("DIRECTIONAL_RELATION_EMBEDDINGS_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "embed", "check"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    if args.stage == "prepare": result = prepare_inputs(args.out, args.model)
    elif args.stage == "embed": result = embed(args.out, args.model, args.device)
    else: check(args.out); result = {"checked": True}
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
