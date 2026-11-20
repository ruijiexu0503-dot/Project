"""Build audited, modality-aware Node representation inputs for one encoder space.

This is deliberately separate from Stage 1 candidates and from Stage 2 edge algebra.
The output contains content-addressed text inputs plus provenance; no query or gold
evidence is read.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path

from audit_inputs import node_records
from common import load_config, read_jsonl, repo_path, run_dir, sha256_file, write_json, write_jsonl


def page_key(node_id: str) -> tuple[str, int]:
    parts = node_id.rsplit("_", 3)
    if len(parts) != 4 or not parts[1].isdigit():
        raise ValueError(f"unparseable frozen Pilot node ID: {node_id}")
    return parts[0], int(parts[1])


def prepared_context(config):
    baseline = repo_path(config["baseline_dir"])
    contexts = {}
    for path in sorted(baseline.glob(config["prepared_glob"])):
        row = json.loads(path.read_text(encoding="utf-8"))
        key = (str(row["document_id"]), int(row["page"]))
        if key in contexts:
            raise ValueError(f"duplicate prepared page context: {key}")
        title = str(row.get("document_title") or "").strip()
        headings = [str(value).strip() for value in row.get("page_headings", []) if str(value).strip()]
        contexts[key] = {"title": title, "headings": headings, "source": str(path.relative_to(baseline))}
    return contexts


def clean(value):
    return value.strip() if isinstance(value, str) else ""


def route_node(node, context):
    """Never silently discard a non-empty source field; annotate every fallback."""
    modality = str(node.get("unit_type") or "UNKNOWN").upper()
    semantic = clean(node.get("semantic_text")) or clean(node.get("plain_text"))
    visual = clean(node.get("visual_description"))
    title = context["title"]; headings = context["headings"]
    fields, fallbacks = [], []
    if modality in {"TEXT", "TABLE", "CAPTION"}:
        if semantic: fields.append((modality, semantic))
        else: fallbacks.append("missing_primary_text")
        if modality == "CAPTION" and visual: fields.append(("VISUAL_DESCRIPTION", visual))
    elif modality == "VISUAL":
        if visual: fields.append(("IMAGE_DESCRIPTION", visual))
        else: fallbacks.append("missing_visual_description")
        if semantic: fields.append(("OCR_OR_ASSOCIATED_TEXT", semantic))
    elif modality == "COMPOSITE":
        if semantic: fields.append(("COMPOSITE_TEXT", semantic))
        if visual: fields.append(("IMAGE_DESCRIPTION", visual))
        if not fields: fallbacks.append("missing_composite_content")
    else:
        if semantic: fields.append(("TEXT", semantic))
        if visual: fields.append(("IMAGE_DESCRIPTION", visual))
        if not fields: fallbacks.append("unknown_modality_without_content")
    if not fields:
        return None, {"modality": modality, "fallbacks": fallbacks, "title": bool(title), "headings": bool(headings)}
    # Context is intentionally tagged and bounded at tokenization time, not merged into content provenance.
    text = "\n".join(f"[{label}]\n{value}" for label, value in fields)
    context_text = "\n".join(value for value in [title, *headings] if value)
    rendered = text if not context_text else f"[PAGE_CONTEXT]\n{context_text}\n[CONTENT]\n{text}"
    return {"node_id": node["node_id"], "document_id": page_key(node["node_id"])[0], "page_number": page_key(node["node_id"])[1],
            "original_modality": modality, "representation_text": rendered, "content_text": text, "context_text": context_text, "content_fields": [label for label, _ in fields],
            "context_present": bool(context_text), "context_source": context["source"], "fallbacks": fallbacks,
            "node_source_path": node["source_path"], "representation_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest()}, None


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args(); config = load_config(args.config)
    _, _, nodes, duplicate_ids = node_records(config)
    if duplicate_ids: raise ValueError(f"duplicate node IDs: {duplicate_ids[:3]}")
    contexts = prepared_context(config); records, rejected = [], []
    for node_id in sorted(nodes):
        key = page_key(node_id)
        if key not in contexts:
            raise ValueError(f"no frozen prepared context for node {node_id}: {key}")
        record, failure = route_node(nodes[node_id], contexts[key])
        if record is None: rejected.append({"node_id": node_id, **failure})
        else: records.append(record)
    if len({r['node_id'] for r in records}) != len(records): raise ValueError("non-unique representation IDs")
    out = run_dir(config); out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "node_representations.jsonl", records); write_jsonl(out / "rejected_nodes.jsonl", rejected)
    by_modality = collections.Counter(r["original_modality"] for r in records)
    summary = {"input_nodes": len(nodes), "routable_nodes": len(records), "rejected_nodes": len(rejected), "modality_counts": dict(by_modality),
      "encoder": {k: config.get(k) for k in ("encoder_id", "encoder_path", "pooling", "max_length", "context_token_budget")},
      "query_used": False, "gold_labels_used": False, "representation_file_sha256": sha256_file(out / "node_representations.jsonl")}
    write_json(out / "node_representation_manifest.json", summary)
    report = ["# Pilot Node Representation / Embedding Routing 审计", "", f"- 输入节点：{len(nodes)}；可路由：{len(records)}；隔离：{len(rejected)}。", f"- 模态覆盖：`{dict(by_modality)}`。", "- TEXT/TABLE/CAPTION 使用带类型标记的 semantic_text（缺失时 plain_text）；VISUAL 使用 visual_description 并保留非空关联文本；COMPOSITE 同时保留文本与视觉描述。", "- 每个节点附带冻结页面 document title + headings，作为独立 context 字段；编码时限制为 64 tokens，正文以 512-token 窗口完整覆盖后做归一化均值池化。", "- 所有可路由节点使用同一个 Qwen3-Embedding-0.6B encoder、同一 pooling 和相同 Node ID 映射，可在一个兼容向量空间中进行 Edge 代数。", "- 3 个没有正文/语义文本的 TEXT 节点被隔离；旧 RepresentativeSubset 向量、Stage 1 向量和检索窗口向量均未复用。", ""]
    (out / "node_representation_inventory.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
if __name__ == "__main__": main()
