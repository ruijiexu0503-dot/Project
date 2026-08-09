from __future__ import annotations

import math
import re
import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")


def embedding_text(node: dict[str, Any], mode: str) -> str:
    original, summary = node.get("plain_text", ""), node.get("base_summary") or ""
    if mode == "original_only": return original
    if mode == "base_summary_only": return summary
    if mode == "original_plus_summary": return f"{original}\n{summary}".strip()
    raise ValueError(f"Invalid embedding input_mode: {mode}")


def _transformer_embeddings(selected: list[dict[str, Any]], mode: str, model_path: str):
    import torch
    import torch.nn.functional as functional
    from transformers import AutoModel, AutoTokenizer

    device = "cpu"
    if torch.cuda.is_available():
        free, _ = torch.cuda.mem_get_info(0)
        if free >= 4 * 1024 ** 3:
            device = "cuda:0"
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModel.from_pretrained(model_path, local_files_only=True,
                                      torch_dtype=torch.float16 if device.startswith("cuda") else torch.float32)
    model.to(device).eval()
    rows = []
    texts = [embedding_text(node, mode) for node in selected]
    for offset in range(0, len(texts), 16):
        encoded = tokenizer(texts[offset:offset + 16], padding=True, truncation=True,
                            max_length=512, return_tensors="pt")
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode():
            hidden = model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
            pooled = functional.normalize(pooled.float(), p=2, dim=1).cpu().tolist()
        for node, vector in zip(selected[offset:offset + 16], pooled):
            rows.append({"node_id": node["node_id"], "doc_id": node["doc_id"],
                         "vector": [round(value, 8) for value in vector]})
    dimensions = len(rows[0]["vector"]) if rows else 0
    del model
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return rows, {"model": str(Path(model_path).resolve()), "architecture": "dense_mean_pooling",
                  "input_mode": mode, "dimensions": dimensions, "device": device}


def generate_document_embeddings(nodes: list[dict[str, Any]], selected_ids: set[str],
                                 mode="original_plus_summary", model_path: str | None = None):
    selected = [n for n in nodes if n["node_id"] in selected_ids]
    if model_path:
        return _transformer_embeddings(selected, mode, model_path)
    docs = [Counter(t.lower() for t in TOKEN.findall(embedding_text(n, mode))) for n in selected]
    df = Counter(term for doc in docs for term in doc)
    vocab = sorted(df); index = {term: i for i, term in enumerate(vocab)}; total = len(docs)
    rows = []
    for node, counts in zip(selected, docs):
        vector = [0.0] * len(vocab)
        for term, count in counts.items(): vector[index[term]] = (1+math.log(count)) * (math.log((1+total)/(1+df[term]))+1)
        norm = math.sqrt(sum(x*x for x in vector)) or 1.0
        vector = [round(x/norm, 8) for x in vector]
        rows.append({"node_id": node["node_id"], "doc_id": node["doc_id"], "vector": vector})
    return rows, {"model": "document_local_tfidf_v1", "input_mode": mode, "dimensions": len(vocab), "vocabulary": vocab}


def cosine(a, b): return sum(x*y for x, y in zip(a, b))


def main():
    from .io_utils import read_jsonl, write_json, write_jsonl
    parser = argparse.ArgumentParser(description="Generate document-local Evidence embeddings")
    parser.add_argument("--nodes", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", required=True)
    parser.add_argument("--input-mode", default="original_plus_summary",
                        choices=["original_only", "base_summary_only", "original_plus_summary"])
    parser.add_argument("--model-path")
    args = parser.parse_args(); nodes = read_jsonl(args.nodes)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metadata_output).parent.mkdir(parents=True, exist_ok=True)
    rows, metadata = generate_document_embeddings(nodes, {node["node_id"] for node in nodes},
                                                   args.input_mode, args.model_path)
    write_jsonl(args.output, rows); write_json(args.metadata_output, metadata)
    print(json.dumps({"nodes": len(rows), **{k: metadata.get(k) for k in ("model", "input_mode", "dimensions", "device")}}, indent=2))


if __name__ == "__main__":
    main()
