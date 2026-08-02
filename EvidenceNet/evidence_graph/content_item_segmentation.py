from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .boundary_experiments import title_anchors
from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm

PROMPT_VERSION = "content-item-segmentation-v1"
DECISIONS = {"CONTINUES_CURRENT_ITEM", "STARTS_NEW_ITEM", "INSERTED_STANDALONE_ITEM"}
KINDS = {"editorial", "advertisement", "cover", "contents", "credits", "visual_content", "other"}


def _primary_page(node):
    pages = node.get("page_ids", [])
    return pages[0] if pages else "NO_PAGE"


def _text(node, limit=850):
    return " ".join((node.get("plain_text") or node.get("original_markdown") or "").split())[:limit]


def _candidate_boundaries(nodes):
    candidates = defaultdict(set)
    for i in range(len(nodes) - 1):
        if _primary_page(nodes[i]) != _primary_page(nodes[i + 1]):
            candidates[i].add("page_transition")
    for i in title_anchors(nodes):
        candidates[i].add("title_anchor")
    # Add document-local lexical valleys. They only propose transitions; the LLM
    # remains the boundary decision maker.
    from .embeddings import cosine, generate_document_embeddings
    vectors, _ = generate_document_embeddings(nodes, {n["node_id"] for n in nodes}, "original_only")
    similarities = [cosine(vectors[i]["vector"], vectors[i + 1]["vector"])
                    for i in range(len(nodes) - 1)]
    valleys = []
    for i, value in enumerate(similarities):
        left = similarities[max(0, i - 3):i]
        right = similarities[i + 1:min(len(similarities), i + 4)]
        neighborhood = left + right
        prominence = (sum(neighborhood) / len(neighborhood) - value) if neighborhood else 0
        if prominence >= .05: valleys.append((prominence, i))
    # Exact zero similarities are common for short OCR blocks. Cap this signal
    # so it cannot turn candidate retrieval into an all-pairs LLM pass.
    for _, i in sorted(valleys, reverse=True)[:30]:
        candidates[i].add("lexical_similarity_valley")
    return candidates, similarities


def _verify_boundaries(nodes, candidates, similarities, llm, checkpoint):
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_index = {r["boundary_index"]: r for r in existing if r.get("prompt_version") == PROMPT_VERSION}
    system = ("Segment a document into logical content items using only supplied local evidence. "
              "An advertisement, cover, contents page, artwork, or other standalone insert is a valid "
              "content item, not noise. Return valid JSON only.")
    for index in sorted(candidates):
        if by_index.get(index, {}).get("decision") in DECISIONS: continue
        left = nodes[max(0, index - 2):index + 1]
        right = nodes[index + 1:min(len(nodes), index + 4)]
        payload = {"boundary_index": index, "candidate_reasons": sorted(candidates[index]),
            "lexical_similarity": similarities[index],
            "left": [{"node_id": n["node_id"], "page": _primary_page(n), "text": _text(n)} for n in left],
            "right": [{"node_id": n["node_id"], "page": _primary_page(n), "text": _text(n)} for n in right]}
        prompt = f'''Judge the transition between the nearest LEFT and RIGHT evidence.
CONTINUES_CURRENT_ITEM means the same logical article, advertisement, visual feature, or other item continues.
STARTS_NEW_ITEM means RIGHT starts a different logical item.
INSERTED_STANDALONE_ITEM means RIGHT starts an inserted standalone item, such as an advertisement or visual insert;
the earlier item might resume after it. Do not call a page an advertisement merely because it is image-heavy or has
little text: require explicit promotional/commercial evidence. A title/byline/layout reset supports a new item;
a subsection, caption, running header, or ordinary paragraph does not.
Return boundary_index, decision, confidence (0..1), right_content_kind ({sorted(KINDS)}),
supporting_span_left, supporting_span_right, and rationale.
INPUT:\n{json.dumps(payload, ensure_ascii=False)}'''
        try:
            generation = llm.generate_json(system, prompt, max_new_tokens=500)
            row = generation.parsed
            decision = str(row.get("decision", "")).upper() if isinstance(row, dict) else ""
            if decision not in DECISIONS: raise ValueError("invalid boundary decision")
            kind = str(row.get("right_content_kind", "other")).lower()
            result = {"boundary_index": index, "left_id": nodes[index]["node_id"],
                "right_id": nodes[index + 1]["node_id"], "decision": decision,
                "confidence": max(0., min(1., float(row.get("confidence", 0)))),
                "right_content_kind": kind if kind in KINDS else "other",
                "supporting_span_left": str(row.get("supporting_span_left", "")),
                "supporting_span_right": str(row.get("supporting_span_right", "")),
                "rationale": str(row.get("rationale", "")), "candidate_reasons": sorted(candidates[index]),
                "lexical_similarity": similarities[index], "model": generation.model,
                "timestamp": generation.timestamp, "prompt_version": PROMPT_VERSION}
        except Exception as exc:
            result = {"boundary_index": index, "left_id": nodes[index]["node_id"],
                "right_id": nodes[index + 1]["node_id"], "decision": "UNRESOLVED", "error": str(exc),
                "candidate_reasons": sorted(candidates[index]), "prompt_version": PROMPT_VERSION}
        by_index[index] = result
        write_jsonl(checkpoint, [by_index[i] for i in sorted(by_index)])
        print({"boundary": index, "decision": result["decision"]}, flush=True)
    return [by_index[i] for i in sorted(by_index)]


def _make_segments(nodes, decisions, threshold=.8):
    accepted = {r["boundary_index"]: r for r in decisions if r.get("decision") in
                {"STARTS_NEW_ITEM", "INSERTED_STANDALONE_ITEM"} and r.get("confidence", 0) >= threshold}
    segments, current = [], []
    for i, node in enumerate(nodes):
        if i and i - 1 in accepted:
            segments.append(current); current = []
        current.append(node)
    if current: segments.append(current)
    starts = {r["right_id"]: r for r in accepted.values()}
    rows = []
    for number, members in enumerate(segments, 1):
        boundary = starts.get(members[0]["node_id"], {})
        rows.append({"segment_id": f"SEGMENT_{number:04d}",
            "initial_content_item_id": f"ITEM_{number:04d}",
            "content_kind": boundary.get("right_content_kind", "front_matter" if number == 1 else "other"),
            "boundary_decision": boundary.get("decision", "DOCUMENT_START"),
            "node_ids": [n["node_id"] for n in members],
            "pages": sorted({p for n in members for p in n.get("page_ids", [])}),
            "text": " ".join(_text(n, 1200) for n in members)[:6000]})
    return rows


def _verify_resumptions(segments, llm, checkpoint):
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_segment = {r["segment_id"]: r for r in existing if r.get("prompt_version") == PROMPT_VERSION}
    item_for = {}; kind_for = {}; assignments = []
    system = ("Determine whether a separated document segment resumes a prior logical content item. "
              "Require specific continuity; topic similarity alone is insufficient. Return JSON only.")
    for i, segment in enumerate(segments):
        initial = segment["initial_content_item_id"]
        if i < 2:
            item_for[segment["segment_id"]] = initial; kind_for[initial] = segment["content_kind"]; continue
        candidates = []
        # The common insertion pattern is A / standalone insert / A resumed.
        for prior in segments[max(0, i - 5):i - 1]:
            prior_item = item_for[prior["segment_id"]]
            if prior_item not in {x["content_item_id"] for x in candidates}:
                candidates.append({"content_item_id": prior_item, "content_kind": kind_for.get(prior_item, "other"),
                                   "segment_id": prior["segment_id"], "text": prior["text"][-2500:]})
        cached = by_segment.get(segment["segment_id"])
        if cached:
            row = cached
        else:
            payload = {"segment_id": segment["segment_id"], "content_kind": segment["content_kind"],
                       "current_text": segment["text"][:3000], "prior_candidates": candidates}
            prompt = f'''Does CURRENT resume one of the prior content items after an inserted segment?
Return segment_id; decision (RESUMES_PRIOR_ITEM or NEW_CONTENT_ITEM); resume_content_item_id
(null for new); confidence; supporting_span_current; supporting_span_prior; rationale.
Match an interrupted argument, sentence, named article, author/byline, or explicit continuation. Do not merge
different articles merely because both concern the same broad subject. Do not merge advertisements with editorial items.
INPUT:\n{json.dumps(payload, ensure_ascii=False)}'''
            try:
                generation = llm.generate_json(system, prompt, max_new_tokens=500); parsed = generation.parsed
                decision = str(parsed.get("decision", "NEW_CONTENT_ITEM")).upper()
                resume = parsed.get("resume_content_item_id")
                valid_ids = {c["content_item_id"] for c in candidates}
                if decision != "RESUMES_PRIOR_ITEM" or resume not in valid_ids or float(parsed.get("confidence", 0)) < .8:
                    decision, resume = "NEW_CONTENT_ITEM", None
                row = {"segment_id": segment["segment_id"], "decision": decision,
                    "resume_content_item_id": resume, "confidence": float(parsed.get("confidence", 0)),
                    "supporting_span_current": str(parsed.get("supporting_span_current", "")),
                    "supporting_span_prior": str(parsed.get("supporting_span_prior", "")),
                    "rationale": str(parsed.get("rationale", "")), "model": generation.model,
                    "timestamp": generation.timestamp, "prompt_version": PROMPT_VERSION}
            except Exception as exc:
                row = {"segment_id": segment["segment_id"], "decision": "UNRESOLVED", "error": str(exc),
                       "prompt_version": PROMPT_VERSION}
            by_segment[segment["segment_id"]] = row
            write_jsonl(checkpoint, [by_segment[k] for k in sorted(by_segment)])
        item = row.get("resume_content_item_id") if row.get("decision") == "RESUMES_PRIOR_ITEM" else initial
        item_for[segment["segment_id"]] = item; kind_for.setdefault(item, segment["content_kind"])
    for segment in segments:
        item = item_for[segment["segment_id"]]
        for node_id in segment["node_ids"]:
            assignments.append({"node_id": node_id, "segment_id": segment["segment_id"],
                "content_item_id": item, "content_kind": kind_for.get(item, segment["content_kind"])})
    return assignments, list(by_segment.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", required=True); parser.add_argument("--config", required=True)
    args = parser.parse_args(); config = load_config(args.config)
    root = Path(config["output"]["graph_root"]) / args.doc_id
    nodes = sorted(read_jsonl(root / "evidence_nodes.jsonl"), key=lambda n: n["document_order"])
    llm = create_llm(config["enrichment"])
    candidates, similarities = _candidate_boundaries(nodes)
    decisions = _verify_boundaries(nodes, candidates, similarities, llm,
                                   root / "content_item_boundary_checkpoint.jsonl")
    segments = _make_segments(nodes, decisions)
    assignments, resumptions = _verify_resumptions(
        segments, llm, root / "content_item_resumption_checkpoint.jsonl")
    write_jsonl(root / "content_item_segments.jsonl", segments)
    write_jsonl(root / "content_item_assignments.jsonl", assignments)
    summary = {"doc_id": args.doc_id, "nodes": len(nodes), "candidate_boundaries": len(candidates),
        "segments": len(segments), "content_items": len({r["content_item_id"] for r in assignments}),
        "standalone_segments": sum(s["boundary_decision"] == "INSERTED_STANDALONE_ITEM" for s in segments),
        "resumed_segments": sum(r.get("decision") == "RESUMES_PRIOR_ITEM" for r in resumptions),
        "unresolved_boundaries": sum(r.get("decision") == "UNRESOLVED" for r in decisions)}
    write_json(root / "content_item_segmentation_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
