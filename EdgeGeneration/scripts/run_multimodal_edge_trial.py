#!/usr/bin/env python3
"""Shadow retrieval of text, figure, and table EvidenceNodes.

Uses existing Qwen3.5 descriptions only. It never writes a graph edge.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import sys

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EdgeGeneration" / "scripts"))
from run_ann_candidate_pilot import index_for, normalize, search_filtered


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path, values):
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values))


def visual_text(row):
    enriched = row.get("visual_enrichment") or {}
    values = [
        enriched.get("final_evidence_description"),
        enriched.get("direct_visual_observation"),
        enriched.get("caption_grounded_interpretation"),
        row.get("caption_text"),
    ]
    normalized = []
    for value in values:
        normalized.append(" ".join(value) if isinstance(value, list) else value)
    return "\n".join(filter(None, normalized)).strip()


def article_id(node):
    return node.get("metadata", {}).get("content_item_id") or "UNRESOLVED_ARTICLE"


def canonical_nodes():
    nodes = []
    for path in sorted((ROOT / "EvidenceNet/output/canonical_graph").glob("*/evidence_nodes.jsonl")):
        nodes.extend(read(path))
    return nodes


def prepare(output, scope):
    if scope == "all_canonical":
        text_nodes = canonical_nodes()
    else:
        text_nodes = read(ROOT / "EdgeGeneration/output/qwen35_description_trial_v1/units.jsonl")
    members, units = {}, []
    for node in text_nodes:
        owner = article_id(node)
        for source in node.get("source_members", []):
            members[(node["doc_id"], source.get("page"), source.get("block_id"))] = owner
        description = "\n".join(filter(None, [node.get("base_summary"), *(node.get("key_points") or [])]))
        units.append({"node_id": node["node_id"], "doc_id": node["doc_id"], "article_id": owner,
                      "evidence_type": node.get("evidence_type", "text"), "text": description or node.get("plain_text", ""),
                      "source_text": node.get("plain_text"), "asset_path": node.get("asset_path"), "bbox": node.get("bbox"),
                      "page_ids": node.get("page_ids", []), "description_source": "qwen35_node_enrichment"})
    visual_by_id = {}
    visual_paths = set((ROOT / "EvidenceNet/output").rglob("visual_descriptions.jsonl"))
    visual_paths.update((ROOT / "EvidenceNet/output/contextual_visual_enrichment_pilot").glob("*/*.jsonl"))
    for path in sorted(visual_paths):
        for row in read(path):
            previous = visual_by_id.get(row.get("visual_node_id"))
            # Contextual visual enrichment has a grounded final description;
            # retain it over the crop-only record with the same visual ID.
            if previous and bool(previous.get("visual_enrichment")) >= bool(row.get("visual_enrichment")):
                continue
            visual_by_id[row.get("visual_node_id")] = row
    visual_rows = []
    for row in visual_by_id.values():
            path_hint = str(row.get("asset_path", ""))
            page = next((part for part in Path(path_hint).parts if part.startswith("page_")), None)
            if not page:
                page = row.get("visual_node_id", "").split("_VIS_", 1)[-1].split("_layout", 1)[0]
            doc = row.get("visual_node_id", "").split("_VIS_page_", 1)[0]
            block = row.get("caption_block_id")
            owner = members.get((doc, page, block))
            # Captions are often short and deliberately absent from the 25-word
            # text trial. A grounded in-article reference block still supplies
            # the article owner without guessing from visual similarity.
            if not owner:
                for reference in row.get("reference_blocks") or []:
                    owner = members.get((doc, page, reference.get("source_block_id")))
                    if owner:
                        break
            text = visual_text(row)
            if not text:
                continue
            # The retained visual description is still useful for cross-document
            # retrieval when its article binding is absent. Fall back to the
            # document owner, which safely excludes within-document candidates;
            # record the weaker ownership rather than inventing an article.
            owner_source = "grounded_source_block" if owner else "document_fallback"
            owner = owner or doc
            visual_rows.append({"node_id": row["visual_node_id"], "doc_id": doc, "article_id": owner,
                                "evidence_type": row.get("visual_type", "figure"), "text": text,
                                "source_text": row.get("caption_text"), "asset_path": row.get("asset_path"),
                                "bbox": row.get("bbox"), "page_ids": [page], "description_source": "qwen35_visual_enrichment",
                                "visual_consistency": (row.get("visual_enrichment") or {}).get("consistency"),
                                "article_owner_source": owner_source})
    # The narrow historical trial did not include canonical tables. Add its one
    # table only in that mode; all-canonical already contains every table.
    if scope != "all_canonical":
      for doc in ("gw150914_detection",):
       for node in read(ROOT / "EvidenceNet/output/canonical_graph" / doc / "evidence_nodes.jsonl"):
        if node.get("evidence_type") != "table" or not node.get("asset_path"):
            continue
        units.append({"node_id": node["node_id"], "doc_id": doc, "article_id": doc,
                      "evidence_type": "table", "text": node.get("plain_text", ""), "source_text": node.get("plain_text"),
                      "asset_path": node.get("asset_path"), "bbox": node.get("bbox"), "page_ids": node.get("page_ids", []),
                      "description_source": "canonical_table_text"})
    # Dedupe visual description records, preserving the contextual enrichment row.
    seen = {u["node_id"] for u in units}
    units.extend(u for u in visual_rows if not (u["node_id"] in seen or seen.add(u["node_id"])))
    write_rows(output / "units.jsonl", units)
    (output / "manifest.json").write_text(json.dumps({"units": len(units), "by_type": Counter(u["evidence_type"] for u in units),
        "by_description_source": Counter(u["description_source"] for u in units), "visual_records_matched_to_article": len(visual_rows), "scope": scope,
        "production_modified": False, "policy": "Existing descriptions retrieve candidates only; assets and bbox remain attached for later visual verification."}, ensure_ascii=False, indent=2) + "\n")


def run(output):
    units = read(output / "units.jsonl")
    model_path = ROOT.parent / ".cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
    if not torch.cuda.is_available():
        raise RuntimeError("Submit via GPU Slurm")
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModel.from_pretrained(model_path, local_files_only=True, dtype=torch.float16).cuda().eval()
    vectors = []
    for start in range(0, len(units), 16):
        batch = tokenizer([u["text"] for u in units[start:start + 16]], padding=True, truncation=True, max_length=512, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            vectors.append(torch.nn.functional.normalize(model(**batch).last_hidden_state[:, 0].float(), dim=1).cpu().numpy())
    vectors = normalize(np.concatenate(vectors)); np.save(output / "vectors.npy", vectors)
    index, _ = index_for(vectors, True, 128)
    owners = [u["doc_id"] + "::" + u["article_id"] for u in units]
    hits = search_filtered(index, vectors, owners, owners, 12)
    pairs = {}
    for i, found in enumerate(hits):
        for rank, (j, score) in enumerate(found, 1):
            a, b = sorted((i, j))
            pairs[(a, b)] = max(pairs.get((a, b), -1), score)
    candidates = []
    for (a, b), score in sorted(pairs.items(), key=lambda item: -item[1]):
        left, right = units[a], units[b]
        candidates.append({"a": left, "b": right, "score": score,
                           "pair_type": "{}↔{}".format(*sorted([left["evidence_type"], right["evidence_type"]])),
                           "status": "UNVERIFIED"})
    write_rows(output / "candidates.jsonl", candidates)
    docs = defaultdict(list)
    for row in candidates:
        key = tuple(sorted((row["a"]["doc_id"] + "::" + row["a"]["article_id"], row["b"]["doc_id"] + "::" + row["b"]["article_id"])))
        docs[key].append(row)
    article_edges = [{"article_a": key[0], "article_b": key[1], "candidate_count": len(rows), "top_score": rows[0]["score"],
                      "evidence_pairs": [{"a": r["a"]["node_id"], "b": r["b"]["node_id"], "pair_type": r["pair_type"], "score": r["score"]} for r in rows[:3]], "status": "UNVERIFIED"}
                     for key, rows in docs.items()]
    article_edges.sort(key=lambda row: (-row["top_score"], -row["candidate_count"]))
    write_rows(output / "article_edge_candidates.jsonl", article_edges)
    selected = []
    for kind in sorted({r["pair_type"] for r in candidates}):
        rows = [r for r in candidates if r["pair_type"] == kind]
        rows.sort(key=lambda r: hashlib.sha256((r["a"]["node_id"] + r["b"]["node_id"]).encode()).hexdigest())
        selected.extend(rows[:4])
    write_rows(output / "review_sample.jsonl", selected)
    summary = {"units": len(units), "candidate_pairs": len(candidates), "article_edge_candidates": len(article_edges),
               "candidate_pair_types": Counter(r["pair_type"] for r in candidates), "sample_pair_types": Counter(r["pair_type"] for r in selected),
               "production_modified": False, "next_step": "Review sampled candidates with original assets where present; do not materialize edges from retrieval."}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    cards = ["<details><summary>{} {:.3f} | {} ↔ {}</summary><pre>{}</pre></details>".format(html.escape(r["pair_type"]), r["score"], html.escape(r["a"]["node_id"]), html.escape(r["b"]["node_id"]), html.escape(json.dumps(r, ensure_ascii=False, indent=2))) for r in selected]
    (output / "report.html").write_text("<!doctype html><meta charset=utf-8><title>Multimodal edge candidates</title><style>body{font:15px system-ui;max-width:1100px;margin:auto}pre{white-space:pre-wrap}</style><h1>多模态 Evidence 候选</h1><pre>" + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>" + "".join(cards))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("stage", choices=["prepare", "run"]); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--scope", choices=["historical_qwen", "all_canonical"], default="historical_qwen")
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    prepare(args.output, args.scope) if args.stage == "prepare" else run(args.output)
