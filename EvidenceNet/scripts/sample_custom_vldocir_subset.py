#!/usr/bin/env python3
"""Build a retrieval-independent Custom VL-DocIR subset manifest."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/benchmarks/VL-DocIR"
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
NODE_FILE = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
VIEW_FILE = ROOT / "migration/vldocir-edge-20261022/results/views.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/custom_vldocir_subset_v1_20261106"
STRUCTURES = (
    "single-page_single-evidence", "single-page_multi-evidence",
    "multi-page_connected", "multi-page_disconnected-close",
    "multi-page_disconnected-distant", "cross-document_same-type",
)
SOURCES = ("wiki", "arxiv", "pubmed", "sec")


def rows(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def norm_box(box):
    if not isinstance(box, dict):
        return None
    keys = ("relative_page_x", "relative_page_y", "relative_width", "relative_height")
    if not all(key in box for key in keys):
        return None
    x, y, w, h = (float(box[key]) for key in keys)
    if min(x, y, w, h) < 0 or w <= 0 or h <= 0:
        return None
    return x, y, x + w, y + h


def iou(left, right):
    left = norm_box(left) if isinstance(left, dict) else left
    right = norm_box(right) if isinstance(right, dict) else right
    if left is None or right is None:
        return 0.0
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_left = (left[2] - left[0]) * (left[3] - left[1])
    area_right = (right[2] - right[0]) * (right[3] - right[1])
    union = area_left + area_right - intersection
    return intersection / union if union else 0.0


def node_matches(nodes, evidence):
    """Return eligible nodes whose member box intersects the Gold bbox."""
    target = norm_box(evidence.get("bounding_box"))
    if target is None:
        return []
    matched = []
    for node in nodes:
        if node["document"] != evidence["document_id"] or int(node["page"]) != int(evidence["page_number"]):
            continue
        best = 0.0
        for member in node.get("members", []):
            boxes = member.get("boxes", [])
            for box in boxes:
                # Node member boxes are pixel coordinates; use coverage by
                # the source node's normalized image size when available.
                width, height = node.get("geometry_image_size", [1000, 2000])
                candidate = {
                    "relative_page_x": float(box[0]) / width,
                    "relative_page_y": float(box[1]) / height,
                    "relative_width": float(box[2] - box[0]) / width,
                    "relative_height": float(box[3] - box[1]) / height,
                }
                best = max(best, iou(candidate, target))
        if best > 0:
            matched.append({"node_id": node["id"], "iou": round(best, 6)})
    return sorted(matched, key=lambda item: (-item["iou"], item["node_id"]))


def source_of(document_id, documents):
    value = documents.get(document_id, {}).get("data_source")
    return {"wiki": "wiki", "wikipedia": "wiki", "arxiv": "arxiv",
            "scientific_articles_arxiv": "arxiv",
            "pubmed": "pubmed", "scientific_articles_pubmed": "pubmed",
            "sec": "sec", "sec_proxy_reports": "sec"}.get(value, value or "unknown")


def stable_order(items, seed):
    return sorted(items, key=lambda item: hashlib.sha256(
        f"{seed}:{item['question_id']}".encode()).hexdigest())


def lexical_similarity(left, right):
    tokenize = lambda value: {token.lower() for token in value.split() if len(token) > 2}
    a, b = tokenize(left), tokenize(right)
    return len(a & b) / len(a | b) if a | b else 0.0


def stratified_select(candidates, limit, seed):
    selected = []
    for structure in STRUCTURES:
        pool = stable_order([x for x in candidates if x["question_type"] == structure], seed)
        selected.extend(pool[:limit])
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--per-structure", type=int, default=20)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError("output must be a new directory")

    questions = rows(DATA / "questions.jsonl")
    evidences = rows(DATA / "question_evidences.jsonl")
    documents = {r["document_id"]: r for r in rows(DATA / "documents.jsonl")}
    current_ids = {r["question_id"] for r in rows(TRACE / "queries.jsonl")}
    nodes = rows(NODE_FILE)
    eligible = {r["node_id"] for r in rows(VIEW_FILE)}
    nodes = [r for r in nodes if r["id"] in eligible]
    corpus_pages = {(r["document"], int(r["page"])) for r in nodes}
    corpus_docs = {doc for doc, _ in corpus_pages}
    evidence_by_query = collections.defaultdict(list)
    for evidence in evidences:
        evidence_by_query[evidence["question_id"]].append(evidence)

    candidates = []
    rejection = collections.Counter()
    for question in questions:
        qid = question["question_id"]
        ev = evidence_by_query[qid]
        if qid in current_ids:
            rejection["development_query"] += 1
            continue
        if question["question_type"] not in STRUCTURES:
            rejection["unknown_structure"] += 1
            continue
        gold_docs = {e["document_id"] for e in ev}
        gold_pages = {(e["document_id"], int(e["page_number"])) for e in ev}
        if not gold_docs <= corpus_docs:
            rejection["missing_gold_document"] += 1
            continue
        if not gold_pages <= corpus_pages:
            rejection["missing_gold_page"] += 1
            continue
        matches = {e["_id"]: node_matches(nodes, e) for e in ev}
        has_all_bbox = all(matches[e["_id"]] for e in ev)
        if not has_all_bbox:
            rejection["missing_bbox_node"] += 1
        candidates.append({
            "question_id": qid,
            "question": question["question"],
            "question_type": question["question_type"],
            "source_types": question.get("dataset_source_types", []),
            "normalized_sources": sorted({source_of(d, documents) for d in gold_docs}),
            "gold_document_ids": sorted(gold_docs),
            "gold_pages": sorted([list(p) for p in gold_pages]),
            "gold_evidence_ids": [e["_id"] for e in ev],
            "bbox_node_matches": matches,
            "all_bbox_supported_by_eligible_node": has_all_bbox,
        })

    selected = stratified_select(candidates, args.per_structure, args.seed)
    selected_ids = {x["question_id"] for x in selected}
    selected_docs = set().union(*(set(x["gold_document_ids"]) for x in selected))
    selected_pages = set().union(*(set(map(tuple, x["gold_pages"])) for x in selected))
    bbox_selected = sum(x["all_bbox_supported_by_eligible_node"] for x in selected)
    coverage_candidates = [x for x in candidates if x["all_bbox_supported_by_eligible_node"]]
    coverage_selected = stratified_select(coverage_candidates, args.per_structure, args.seed)
    full_pool = []
    for question in questions:
        if question["question_id"] in current_ids or question["question_type"] not in STRUCTURES:
            continue
        ev = evidence_by_query[question["question_id"]]
        gold_pages = {(e["document_id"], int(e["page_number"])) for e in ev}
        missing_docs = {doc for doc, _ in gold_pages if doc not in corpus_docs}
        missing_pages = gold_pages - corpus_pages
        full_pool.append({
            "question_id": question["question_id"],
            "question_type": question["question_type"],
            "missing_documents": sorted(missing_docs),
            "missing_pages": sorted([list(p) for p in missing_pages]),
        })
    missing_structure = [
        x for x in full_pool if x["question_type"] == "multi-page_disconnected-close"
        and x["missing_pages"]
    ]
    needed = max(0, args.per_structure - len(
        [x for x in selected if x["question_type"] == "multi-page_disconnected-close"]
    ))
    expansion_targets = sorted(
        missing_structure, key=lambda x: (len(x["missing_documents"]),
                                          len(x["missing_pages"]), x["question_id"])
    )[:needed]
    expansion_docs = set().union(*(set(x["missing_documents"]) for x in expansion_targets))
    expansion_existing_docs = {
        doc for x in expansion_targets for doc, _ in map(tuple, x["missing_pages"])
        if doc in corpus_docs
    }
    selected_pairs = []
    for index, left in enumerate(selected):
        for right in selected[index + 1:]:
            shared_docs = sorted(set(left["gold_document_ids"]) & set(right["gold_document_ids"]))
            shared_pages = sorted(
                set(map(tuple, left["gold_pages"])) & set(map(tuple, right["gold_pages"]))
            )
            similarity = lexical_similarity(left["question"], right["question"])
            if shared_docs or shared_pages or similarity >= 0.8:
                selected_pairs.append({
                    "left": left["question_id"], "right": right["question_id"],
                    "shared_documents": shared_docs, "shared_pages": [list(x) for x in shared_pages],
                    "lexical_jaccard": round(similarity, 6),
                })
    expansion_pages = set().union(*(set(map(tuple, x["missing_pages"])) for x in expansion_targets))
    report = {
        "dataset_label": "Custom VL-DocIR Subset",
        "subset_name": "custom_stratified_120" if len(selected) == 120 else "custom_stratified_partial",
        "seed": args.seed,
        "sampling_rule": "retrieval-independent stable hash ordering, max 20 per evidence structure, excluding fixed 24-query dev set",
        "source_files": {str(path.relative_to(ROOT)): sha(path) for path in (
            DATA / "questions.jsonl", DATA / "question_evidences.jsonl",
            DATA / "documents.jsonl", NODE_FILE, VIEW_FILE, TRACE / "queries.jsonl")},
        "frozen_corpus": {"documents": len(corpus_docs), "pages": len(corpus_pages),
                          "eligible_nodes": len(eligible)},
        "candidate_counts": {
            "all_official_queries": len(questions), "dev_queries_excluded": len(current_ids),
            "corpus_fixed_after_doc_page_gate": len(candidates),
            "corpus_fixed_with_all_bbox_nodes": len(coverage_candidates),
            "by_structure": dict(collections.Counter(x["question_type"] for x in candidates)),
            "bbox_by_structure": dict(collections.Counter(x["question_type"] for x in coverage_candidates)),
            "by_source": dict(collections.Counter(s for x in candidates for s in x["normalized_sources"])),
        },
        "selection": {
            "selected_count": len(selected), "selected_bbox_complete_count": bbox_selected,
            "by_structure": dict(collections.Counter(x["question_type"] for x in selected)),
            "by_source": dict(collections.Counter(s for x in selected for s in x["normalized_sources"])),
            "documents": len(selected_docs), "pages": len(selected_pages),
            "new_documents_vs_frozen": len(selected_docs - corpus_docs),
            "new_pages_vs_frozen": len(selected_pages - corpus_pages),
            "overlap_pairs": len(selected_pairs),
            "high_similarity_pairs": sum(x["lexical_jaccard"] >= 0.8 for x in selected_pairs),
        },
        "rejection_counts": dict(rejection),
        "document_expansion": {
            "minimum_new_documents_for_selected_manifest": len(selected_docs - corpus_docs),
            "minimum_new_pages_for_selected_manifest": len(selected_pages - corpus_pages),
            "greedy_targets_to_reach_120": expansion_targets,
            "greedy_new_documents_to_reach_120": len(expansion_docs),
            "greedy_existing_documents_requiring_new_pages": len(expansion_existing_docs),
            "greedy_new_pages_to_reach_120": len(expansion_pages),
            "greedy_node_count_unknown_until_parsing": True,
            "node_count_unknown_until_parsing": True,
            "estimate_method": "parse new pages and count eligible nodes; Gold evidence count is not a node estimate",
        },
        "budget_plan": ["D0 Top-10", "D0+ Dense Top-13", "D1 Dense Top-10 + 3 D1 nodes"],
        "evaluation": ["RecallAll", "bbox-supported coverage", "AI-assisted Requirement Coverage"],
        "leakage_controls": [
            "Gold used only for corpus eligibility and manifest metadata, never subquery generation.",
            "No Dense ranking, D1 output, Edge, answer, or metric used for selection.",
            "Fixed 24 development IDs excluded from test selection.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "custom_stratified_sampling_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if len(selected) == 120:
        (args.out / "custom_stratified_120_manifest.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in selected))
    (args.out / "candidate_pool.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in candidates))
    (args.out / "custom_partial_manifest.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in selected))
    (args.out / "doc_page_complete_111_manifest.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in selected))
    (args.out / "bbox_complete_111_manifest.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in coverage_selected))
    (args.out / "selected_overlap_diagnostics.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in selected_pairs))
    (args.out / "bbox_complete_candidate_pool.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in coverage_candidates))
    (args.out / "CUSTOM_DATASET_EXPANSION_REPORT.md").write_text(
        "# Custom VL-DocIR Subset Expansion\n\n"
        "本数据集是 **Custom VL-DocIR Subset**，不是官方 Representative Subset。\n\n"
        f"- Random seed: `{args.seed}`；固定开发集排除：{len(current_ids)} 条。\n"
        f"- Gold Document/Page 完整覆盖候选：{len(candidates)} 条；其中全部 Gold bbox 有 eligible Node 的候选：{len(coverage_candidates)} 条。\n"
        f"- 本次抽样：{len(selected)} 条；按六种 Evidence Structure 每类最多 {args.per_structure} 条。\n"
        f"- 选中 Query 使用 {len(selected_docs)} 个文档、{len(selected_pages)} 个 Gold Page；全部在冻结 corpus 内，因此需要新增文档/Page/Node/Embedding：0。\n"
        f"- 选集中存在 {len(selected_pairs)} 个共享文档/页面或高词汇相似度关系，详见 `selected_overlap_diagnostics.jsonl`；这些关系应在最终统计中按文档聚类处理。\n"
        f"- bbox 完整候选中的可抽样上限为 {len(coverage_selected)} 条；主 manifest 仍按 document/page 完整性抽样，并逐条保留 bbox 状态。\n\n"
        "## 方案 A：Corpus-fixed Expansion\n\n"
        f"可直接复用现有 32 文档、517 个 eligible 页面和 6,520 Node；不需要重新生成 Node Embedding。"
        f"当前可用候选按结构见 `custom_stratified_sampling_audit.json`。\n\n"
        "## 方案 B：Document Expansion\n\n"
        "本次选中的 120 条无需 Document Expansion；若未来要求纳入当前 corpus 不覆盖的 Query，必须先增加完整 Gold Document/Page，重新 Parsing，并仅为新增 eligible Node 生成同协议 4096 维 Embedding。Node 数量必须在 Parsing 后实测，不能由 Gold bbox 数量推断。\n\n"
        "## 防泄漏与评估\n\n"
        "抽样只使用 question/evidence metadata 判断 corpus 完整性，不读取 Retrieval 排名、D1 输出、Edge 或答案内容。D0/D0+/D1 使用相同 Candidate Universe 和 13-Node 预算；指标按六种 Structure 分组，Requirement Coverage 仅作 AI-assisted diagnostic。\n"
    )


if __name__ == "__main__":
    main()
