"""Prepare a leak-separated VL-DocIR mini corpus for dynamic edge retrieval.

The retriever-facing records deliberately contain no answers or qrels.  Exact
HTML evidence alignment is kept in ``qrels_private`` for state building and
evaluation only.  This is a new namespace; no Pilot IDs or vectors are reused.
"""
from __future__ import annotations

import argparse, hashlib, json, os
from collections import Counter, defaultdict
from pathlib import Path


def rows(path):
    with path.open(encoding="utf-8") as handle:
        yield from (json.loads(line) for line in handle if line.strip())


def dump_jsonl(path, records):
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_pick(items, take, seed):
    return sorted(items, key=lambda item: hashlib.sha256(f"{seed}:{item['question_id']}".encode()).hexdigest())[:take]


def stratified_pick(items, take, seed):
    """Proportional deterministic sampling by declared question_type only."""
    groups = defaultdict(list)
    for item in items: groups[item.get("question_type", "UNKNOWN")].append(item)
    if take >= len(items): return sorted(items, key=lambda x: x["question_id"])
    allocated, remainder = {}, []
    for kind, values in groups.items():
        exact = take * len(values) / len(items); allocated[kind] = min(len(values), int(exact))
        remainder.append((exact - int(exact), kind))
    for _, kind in sorted(remainder, reverse=True):
        if sum(allocated.values()) >= take: break
        if allocated[kind] < len(groups[kind]): allocated[kind] += 1
    picked = []
    for kind in sorted(groups): picked.extend(stable_pick(groups[kind], allocated[kind], seed))
    return sorted(picked, key=lambda x: x["question_id"])


def node_kind(tag, evidence_type, text):
    tag = (tag or "").lower(); evidence_type = (evidence_type or "").lower()
    if tag in {"table", "tr", "td", "th"}: return "TABLE"
    if tag == "figcaption" or evidence_type == "image_caption": return "CAPTION"
    if tag in {"img", "figure", "svg", "canvas"} or evidence_type == "image": return "IMAGE"
    return "TEXT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-root", type=Path, required=True)
    ap.add_argument("--raw-root", type=Path, required=True)
    ap.add_argument("--pilot-queries", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--train", type=int, default=128); ap.add_argument("--dev", type=int, default=32); ap.add_argument("--test", type=int, default=64)
    args = ap.parse_args(); out = args.out; out.mkdir(parents=True, exist_ok=False)
    pilot_ids = {row["question_id"] for row in rows(args.pilot_queries)}
    selected = {}
    for split, take in (("train", args.train), ("dev", args.dev), ("test", args.test)):
        candidates = [q for q in rows(args.sample_root / f"{split}_questions.jsonl") if q["question_id"] not in pilot_ids]
        selected[split] = stratified_pick(candidates, take, args.seed)
    selected_ids = {s: {q["question_id"] for q in qs} for s, qs in selected.items()}
    docs = {d["document_id"]: d for d in rows(args.raw_root / "documents.jsonl")}
    pages = list(rows(args.raw_root / "document_pages.jsonl"))
    # Build canonical nodes from raw metadata. Empty IMAGE is retained with an
    # explicit missing-content mask rather than silently deleted.
    canonical, exclusions, node_by_evidence = [], [], {}
    selected_docs = {s: {d["document_id"] for d in rows(args.sample_root / f"{s}_documents.jsonl")} for s in selected}
    doc_owner = {doc: split for split, values in selected_docs.items() for doc in values}
    duplicate_doc_owner = len(doc_owner) != sum(map(len, selected_docs.values()))
    if duplicate_doc_owner: raise RuntimeError("document component crosses split")
    for doc_id in sorted(doc_owner):
        meta_path = args.raw_root / "document_texts" / doc_id / f"{doc_id}_html_elements_metadata.json"
        html_path = args.raw_root / "document_texts" / doc_id / f"{doc_id}.html"
        if not (meta_path.exists() and html_path.exists()):
            exclusions.append({"record_type":"document", "document_id":doc_id, "reason":"missing_html_or_metadata"}); continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for item in meta.get("items", []):
            element_id = str(item.get("id") or "")
            if not element_id: continue
            text = str(item.get("text_sample") or "").strip()
            kind = node_kind(item.get("tag"), None, text)
            if not text and kind != "IMAGE":
                exclusions.append({"record_type":"element", "document_id":doc_id, "html_unique_element_id":element_id, "reason":"empty_nonvisual_content"}); continue
            for page in item.get("pages") or []:
                page = int(page); node_id = f"dynamic-v1::{doc_id}::p{page:04d}::{element_id}"
                record = {"node_id":node_id, "document_id":doc_id, "page_id":f"{doc_id}:{page}", "page_number":page,
                          "split":doc_owner[doc_id], "node_type":kind, "content_text":text,
                          "context_text":str(docs[doc_id].get("title") or "").strip(), "context_source":"documents.title" if docs[doc_id].get("title") else None,
                          "content_available":bool(text), "visual_asset_available":kind == "IMAGE" and (args.raw_root / "pages" / f"{doc_id}.tar").exists(),
                          "representation_available": bool(text), "missing_mask":{"content":not bool(text), "visual_description":kind == "IMAGE" and not bool(text)},
                          "source":{"html":str(html_path.relative_to(args.raw_root)), "metadata":str(meta_path.relative_to(args.raw_root)), "html_unique_element_id":element_id, "html_tag":item.get("tag"), "bbox":item.get("bbox_orig", item.get("bbox"))}}
                canonical.append(record); node_by_evidence[(doc_id, page, element_id)] = node_id
    canonical.sort(key=lambda x: x["node_id"]); dump_jsonl(out / "nodes.jsonl", canonical)
    # Retriever inputs intentionally omit answer, evidence IDs, and labels.
    for split, qs in selected.items():
        dump_jsonl(out / f"queries_{split}.jsonl", [{"query_id":q["question_id"], "query":q["question"], "split":split, "question_type":q.get("question_type")} for q in qs])
    qrels, alignment = [], []
    for split in selected:
        evidence_by_query = defaultdict(list)
        for e in rows(args.sample_root / f"{split}_evidences.jsonl"):
            if e["question_id"] in selected_ids[split]: evidence_by_query[e["question_id"]].append(e)
        for qid, evidences in evidence_by_query.items():
            pages_for_q = sorted({f"{e['document_id']}:{int(e['page_number'])}" for e in evidences})
            mapped, missing = [], []
            for e in evidences:
                key = (e["document_id"], int(e["page_number"]), str(e["html_unique_element_id"]))
                node_id = node_by_evidence.get(key)
                detail = {"document_id":key[0], "page_number":key[1], "html_unique_element_id":key[2], "evidence_type":e.get("evidence_type"), "node_id":node_id}
                (mapped if node_id else missing).append(detail)
            qrels.append({"query_id":qid, "split":split, "positive_page_ids":pages_for_q, "mapped_positive_nodes":mapped, "unmapped_evidence":missing,
                          "supervision":"page_level_weak; exact node mappings are audit-only, not copied to page nodes"})
            alignment.append({"query_id":qid, "split":split, "evidence_total":len(evidences), "exact_node_mapped":len(mapped), "unmapped":missing})
    dump_jsonl(out / "qrels_private.jsonl", sorted(qrels, key=lambda x:x["query_id"])); dump_jsonl(out / "label_alignment.jsonl", sorted(alignment, key=lambda x:x["query_id"]))
    dump_jsonl(out / "exclusions.jsonl", exclusions)
    mapped = sum(x["exact_node_mapped"] for x in alignment); evidence_total = sum(x["evidence_total"] for x in alignment)
    source = {"dataset":"anonymous-8421/VL-DocIR", "revision":"4cc60a535dc889636e6026feb2c872ff33710aaf", "raw_asset_manifest":json.loads((args.sample_root / "raw_asset_manifest.json").read_text()),
              "input_hashes":{str(p):sha256(p) for p in [args.sample_root / "train_questions.jsonl",args.sample_root / "dev_questions.jsonl",args.sample_root / "test_questions.jsonl",args.raw_root / "documents.jsonl",args.raw_root / "document_pages.jsonl"]}}
    (out / "source_manifest.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    split_manifest = {"seed":args.seed, "targets":{"train":args.train,"dev":args.dev,"test":args.test}, "actual_queries":{s:len(v) for s,v in selected.items()}, "component_document_counts":{s:len(v) for s,v in selected_docs.items()}, "pilot_query_ids_excluded":len(pilot_ids), "selection":"deterministic proportional declared-question_type sampling within original component-safe split; no retrieval/model fields read"}
    (out / "split_manifest.json").write_text(json.dumps(split_manifest, indent=2), encoding="utf-8")
    decision = {"primary_unit":"page", "name":"page_level_weak_supervision", "reason":"VL-DocIR qrels are page evidence for retrieval; exact HTML element mapping is retained for visibility/audit, but is not sufficient to label every node on a relevant page as a strong positive.", "output_k_unit":"page", "graph_search_unit":"node", "node_label_policy":"mapped evidence only; all other nodes remain unknown/masked"}
    (out / "unit_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    readiness = ["# Data Readiness", "", "## P0 conclusion", "", f"- Raw selected assets: **{len(doc_owner)} documents**; HTML/metadata were checked per document during canonicalization.", f"- Canonical nodes: **{len(canonical)}**. Empty visual elements are retained with masks; empty nonvisual elements are excluded with reasons.", f"- Exact evidence→node mapping: **{mapped}/{evidence_total} ({mapped/max(evidence_total,1):.1%})**.", "- Primary learning/evaluation unit is **page-level weak supervision**. Node search is allowed, but only exact mapped evidence nodes have any node-level annotation; other nodes are unknown, not negative.", "- Nodes, compatible embeddings, and a static candidate graph have not yet been built. Training is therefore blocked until those derived assets are generated in this new namespace.", ""]
    (out / "DATA_READINESS.md").write_text("\n".join(readiness), encoding="utf-8")
    report = ["# Label Alignment Report", "", f"Exact mapping: {mapped}/{evidence_total} ({mapped/max(evidence_total,1):.1%}).", "", "Mapping key is exact `(document_id, page_number, html_unique_element_id)`. No similarity-based fallback is used. Unmapped evidence stays visible in `qrels_private.jsonl` and does not become a guessed node label."]
    (out / "label_alignment_report.md").write_text("\n".join(report)+"\n", encoding="utf-8")
    print(json.dumps({"nodes":len(canonical), "mapped":mapped, "evidence":evidence_total, **split_manifest["actual_queries"]}))


if __name__ == "__main__": main()
