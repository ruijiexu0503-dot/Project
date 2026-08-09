from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from .embeddings import generate_document_embeddings
from .io_utils import read_jsonl, write_json, write_jsonl


HEADING = re.compile(r"^(#{1,3})\s+(.+)", re.S)
NON_TITLE = re.compile(r"^(?:references?|further reading|cern courier|volume\s+\d+|january/february|"
                       r"news digest|reports from|appointments(?: and awards)?|background)$", re.I)
ANAPHOR = re.compile(r"^(?:this|these|those|they|their|it|following|however|while|and|but)\b", re.I)


def normal(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def candidate(block):
    markdown = (block.get("markdown") or "").strip()
    match = HEADING.match(markdown)
    if match:
        return " ".join(match.group(2).split()), "explicit_heading", len(match.group(1))
    lines = [" ".join(line.split()) for line in markdown.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    lead, remainder = lines[0].strip(" #"), " ".join(lines[1:])
    words = lead.split()
    if (2 <= len(words) <= 14 and len(lead) <= 100 and len(remainder) >= 100
            and not lead.endswith((".", ",", ";", ":", "?", "!"))
            and not lead.startswith(("•", "-"))):
        return lead, "inline_lead_candidate", None
    return None


def cosine(left, right):
    a, b = np.asarray(left, dtype=np.float32), np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def main():
    parser = argparse.ArgumentParser(description="Post-node-generation title/context coverage audit")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--node-embeddings", required=True)
    parser.add_argument("--aligned-dir", required=True)
    parser.add_argument("--bge-model", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    nodes = sorted(read_jsonl(args.nodes), key=lambda row: row["document_order"])
    node_index = {row["node_id"]: i for i, row in enumerate(nodes)}
    vector_by_id = {row["node_id"]: row["vector"] for row in read_jsonl(args.node_embeddings)}
    by_page = {}
    for node in nodes:
        for page in node.get("page_ids") or []:
            by_page.setdefault(page, []).append(node)

    rows = []
    aligned = Path(args.aligned_dir)
    for path in sorted(aligned.glob("page_*.json")):
        source = json.loads(path.read_text(encoding="utf-8")); page = source.get("page") or path.stem
        page_nodes = by_page.get(page, [])
        block_to_nodes = {}
        for node in page_nodes:
            for member in node.get("source_members") or []:
                block_to_nodes.setdefault(member.get("block_id"), []).append(node)
        blocks = source.get("aligned_blocks") or []
        ranked_nodes = []
        for node in page_nodes:
            ranks = [int(m["block_id"].rsplit("_", 1)[-1]) for m in node.get("source_members") or []
                     if (m.get("block_id") or "").rsplit("_", 1)[-1].isdigit()]
            if ranks: ranked_nodes.append((min(ranks), node))
        for block in blocks:
            found = candidate(block)
            if not found: continue
            title, detection, level = found
            if NON_TITLE.fullmatch(title): classification = "SECTION_OR_RUNNING_LABEL"
            else: classification = "UNRESOLVED"
            block_id = block.get("block_id")
            represented = block_to_nodes.get(block_id, [])
            title_norm = normal(title)
            embedded = [node for node in page_nodes if title_norm and title_norm in normal(node.get("plain_text", ""))]
            status = "PRESENT_IN_EVIDENCE" if represented else ("EMBEDDED_IN_EVIDENCE" if embedded else "MISSING_FROM_EVIDENCE")
            candidates = represented or embedded
            if not candidates and block_id and block_id.rsplit("_", 1)[-1].isdigit():
                rank = int(block_id.rsplit("_", 1)[-1])
                following = [(r, n) for r, n in ranked_nodes if r >= rank]
                if following: candidates = [min(following, key=lambda pair: pair[0])[1]]
            associated = candidates[0] if candidates else None
            rows.append({"page": page, "source_block_id": block_id, "title": title,
                         "detection": detection, "heading_level": level, "coverage_status": status,
                         "classification": classification,
                         "associated_node_id": associated.get("node_id") if associated else None,
                         "associated_order": associated.get("document_order") if associated else None,
                         "geometry_available": bool(block.get("bbox") or block.get("deepseek_bbox")),
                         "title_embedding_key": f"TITLE_{len(rows):05d}"})

    pseudo_nodes = [{"node_id": row["title_embedding_key"], "doc_id": "title-audit",
                     "plain_text": row["title"], "base_summary": ""} for row in rows]
    title_vectors, _ = generate_document_embeddings(
        pseudo_nodes, {row["node_id"] for row in pseudo_nodes}, "original_only", args.bge_model)
    title_vector_by_id = {row["node_id"]: row["vector"] for row in title_vectors}
    for row in rows:
        node_id = row["associated_node_id"]
        if not node_id or node_id not in vector_by_id: continue
        i = node_index[node_id]; title_vector = title_vector_by_id[row["title_embedding_key"]]
        following_ids = [nodes[j]["node_id"] for j in range(i, min(len(nodes), i + 3))]
        preceding_ids = [nodes[j]["node_id"] for j in range(max(0, i - 3), i)]
        following = max((cosine(title_vector, vector_by_id[nid]) for nid in following_ids), default=0.0)
        preceding = max((cosine(title_vector, vector_by_id[nid]) for nid in preceding_ids), default=0.0)
        margin = following - preceding
        row.update(following_similarity=round(following, 4), preceding_similarity=round(preceding, 4),
                   context_margin=round(margin, 4), anaphoric_context=bool(ANAPHOR.match(nodes[i].get("plain_text", ""))))
        if row["classification"] != "SECTION_OR_RUNNING_LABEL":
            if margin >= .08 and following >= .45: row["classification"] = "LIKELY_STARTS_NEW_ITEM"
            elif margin <= -.08: row["classification"] = "LIKELY_SUBHEADING_OR_PREVIOUS_CONTEXT"
            else: row["classification"] = "AMBIGUOUS"
    for row in rows: row.pop("title_embedding_key", None)
    write_jsonl(output / "title_context_audit.jsonl", rows)
    counts = {}
    for field in ("coverage_status", "classification"):
        counts[field] = {value: sum(row[field] == value for row in rows) for value in sorted({r[field] for r in rows})}
    summary = {"source_title_candidates": len(rows), "nodes": len(nodes), "counts": counts,
               "geometry_coverage": round(sum(row["geometry_available"] for row in rows) / len(rows), 4) if rows else 0,
               "uses_llm_or_vlm": False,
               "note": "Inline leads are candidates, not asserted titles; ambiguous cases do not force boundaries."}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
