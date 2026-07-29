from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")


def embedding_text(node: dict[str, Any], mode: str) -> str:
    original, summary = node.get("plain_text", ""), node.get("base_summary") or ""
    if mode == "original_only": return original
    if mode == "base_summary_only": return summary
    if mode == "original_plus_summary": return f"{original}\n{summary}".strip()
    raise ValueError(f"Invalid embedding input_mode: {mode}")


def generate_document_embeddings(nodes: list[dict[str, Any]], selected_ids: set[str], mode="original_plus_summary"):
    selected = [n for n in nodes if n["node_id"] in selected_ids]
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

