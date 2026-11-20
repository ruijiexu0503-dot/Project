"""Encode routed Pilot node representations into one verified vector space."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from common import load_config, read_jsonl, run_dir, sha256_file, write_json, write_jsonl

def token_windows(tokenizer, record, context_budget, max_length):
    context = tokenizer.encode(record["context_text"], add_special_tokens=False)[:context_budget]
    content = tokenizer.encode(record["content_text"], add_special_tokens=False)
    capacity = max_length - len(context)
    if capacity <= 0: raise ValueError("context budget consumes encoder input")
    chunks = [content[start:start + capacity] for start in range(0, max(1, len(content)), capacity)] or [[]]
    return [context + chunk for chunk in chunks], len(context), len(content)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--allow-cpu", action="store_true"); args = parser.parse_args()
    config = load_config(args.config); out = run_dir(config); records = list(read_jsonl(out / "node_representations.jsonl"))
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(config["encoder_path"], local_files_only=True, trust_remote_code=True, padding_side="left")
    plans = []; total_windows = 0
    for record in records:
        windows, context_tokens, content_tokens = token_windows(tokenizer, record, int(config["context_token_budget"]), int(config["max_length"]))
        plans.append((record, windows)); total_windows += len(windows)
        record["encoding_plan"] = {"context_tokens": context_tokens, "content_tokens": content_tokens, "windows": len(windows)}
    manifest = {"nodes": len(records), "windows": total_windows, "encoder_id": config["encoder_id"], "pooling": "normalized_mean_over_content_windows", "max_length": config["max_length"], "context_token_budget": config["context_token_budget"], "dry_run": args.dry_run}
    if args.dry_run:
        write_json(out / "node_embedding_plan.json", manifest); print(json.dumps(manifest)); return
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and not args.allow_cpu: raise RuntimeError("CUDA unavailable; rerun explicitly with --allow-cpu for a bounded CPU test")
    model = __import__("transformers").AutoModel.from_pretrained(config["encoder_path"], local_files_only=True, trust_remote_code=True, torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32).to(device).eval()
    node_vectors = []; ids = []
    for record, windows in plans:
        vectors = []
        for start in range(0, len(windows), int(config["batch_size"])):
            encoded = tokenizer.pad({"input_ids": windows[start:start + int(config["batch_size"])]}, padding=True, return_tensors="pt").to(device)
            with torch.inference_mode(): vector = model(**encoded).last_hidden_state[:, -1].float(); vector = torch.nn.functional.normalize(vector, p=2, dim=1)
            vectors.append(vector.cpu().numpy())
        pooled = np.concatenate(vectors).mean(axis=0); pooled /= max(np.linalg.norm(pooled), 1e-12)
        node_vectors.append(pooled.astype(config["dtype"])); ids.append({"node_id": record["node_id"], "representation_sha256": record["representation_sha256"]})
    matrix = np.asarray(node_vectors); np.save(out / "node_embeddings.npy", matrix); write_jsonl(out / "embedding_ids.jsonl", ids)
    manifest.update(dry_run=False, shape=list(matrix.shape), dtype=str(matrix.dtype), vector_sha256=sha256_file(out / "node_embeddings.npy"), ids_sha256=sha256_file(out / "embedding_ids.jsonl"))
    write_json(out / "node_embedding_manifest.json", manifest); print(json.dumps(manifest))
if __name__ == "__main__": main()
