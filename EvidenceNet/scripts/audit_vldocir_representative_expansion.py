#!/usr/bin/env python3
"""Audit VL-DocIR representative-subset expansion without model execution."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/benchmarks/VL-DocIR"
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
DEFAULT_OUT = ROOT / "EvidenceNet/output/vldocir_representative_expansion_feasibility_v1_20261106"
STRUCTURES = (
    "single-page_single-evidence", "single-page_multi-evidence",
    "multi-page_connected", "multi-page_disconnected-close",
    "multi-page_disconnected-distant", "cross-document_same-type",
)


def rows(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--subset-dir", type=Path,
                        help="Local copy of the four small official subset JSONL files.")
    args = parser.parse_args()

    subset_dir = args.subset_dir
    subset_access = {
        "repository": "https://huggingface.co/datasets/anonymous-8421/VL-DocIR-RepresentativeSubset",
        "creation_rule": "4 data sources x 6 evidence structures x 5 unique queries = 120",
        "files": ["questions.jsonl", "question_evidences.jsonl", "documents.jsonl", "document_pages.jsonl"],
        "access_status": "not_read_in_this_run",
    }
    full_questions = rows(DATA / "questions.jsonl")
    full_evidences = rows(DATA / "question_evidences.jsonl")
    if subset_dir:
        questions_path = subset_dir / "questions.jsonl"
        evidence_path = subset_dir / "question_evidences.jsonl"
        if not questions_path.exists() or not evidence_path.exists():
            raise FileNotFoundError("subset-dir must contain questions.jsonl and question_evidences.jsonl")
        subset_questions = rows(questions_path)
        subset_evidences = rows(evidence_path)
        subset_access["access_status"] = "local_files_read"
        subset_access["local_dir"] = str(subset_dir)
    else:
        subset_questions = []
        subset_evidences = []
        subset_access["access_status"] = "official_files_unavailable_http_401"
    official = {q["question_id"]: q for q in full_questions}
    evidence_by_q = collections.defaultdict(list)
    for evidence in full_evidences:
        evidence_by_q[evidence["question_id"]].append(evidence)
    current_queries = rows(TRACE / "queries.jsonl")
    current_ids = {q["question_id"] for q in current_queries}
    current_official = [official[qid] for qid in current_ids]
    subset_ids = {q["question_id"] for q in subset_questions}
    subset_evidence_by_q = collections.defaultdict(list)
    for evidence in subset_evidences:
        subset_evidence_by_q[evidence["question_id"]].append(evidence)
    all_nodes = rows(SOURCE / "nodes.jsonl")
    eligible_nodes = {r["node_id"] for r in rows(SOURCE / "views.jsonl")}
    corpus_docs = {r["document"] for r in all_nodes if r["id"] in eligible_nodes}
    corpus_pages = {(r["document"], int(r["page"])) for r in all_nodes if r["id"] in eligible_nodes}
    pages_by_doc = collections.Counter(doc for doc, _ in corpus_pages)

    def coverage(q):
        ev = evidence_by_q[q["question_id"]]
        gold_docs = {e["document_id"] for e in ev}
        gold_pages = {(e["document_id"], int(e["page_number"])) for e in ev}
        return {
            "gold_documents": sorted(gold_docs),
            "gold_pages": sorted([list(p) for p in gold_pages]),
            "all_gold_documents_in_corpus": gold_docs <= corpus_docs,
            "all_gold_pages_in_corpus": gold_pages <= corpus_pages,
            "missing_documents": sorted(gold_docs - corpus_docs),
            "missing_pages": sorted([list(p) for p in gold_pages - corpus_pages]),
            "gold_evidence_count": len(ev),
        }

    current_type_counts = collections.Counter(q["question_type"] for q in current_official)
    current_doc_ids = set().union(*(set(coverage(q)["gold_documents"]) for q in current_official))
    current_gold_pages = set().union(*(set(map(tuple, coverage(q)["gold_pages"])) for q in current_official))

    reusable = []
    for q in full_questions:
        cov = coverage(q)
        if cov["all_gold_documents_in_corpus"]:
            reusable.append((q, cov))
    reusable_type_counts = collections.Counter(q["question_type"] for q, _ in reusable)

    # This is deliberately a candidate pool, not an assertion that it is the
    # official representative subset. It gives an exact, reproducible audit
    # until the official 120-ID manifest is supplied.
    candidate_120 = []
    for structure in STRUCTURES:
        candidates = sorted(
            ((q, cov) for q, cov in reusable if q["question_type"] == structure),
            key=lambda item: item[0]["question_id"],
        )
        candidate_120.extend(candidates[:20])
    selected_ids = {q["question_id"] for q, _ in candidate_120}
    selected_docs = set().union(*(set(c["gold_documents"]) for _, c in candidate_120))
    selected_pages = set().union(*(set(map(tuple, c["gold_pages"])) for _, c in candidate_120))
    selected_missing_pages = selected_pages - corpus_pages

    manifest_status = {
        "official_repository_exists": True,
        "official_120_manifest_supplied": bool(subset_dir),
        "official_membership_verified": bool(subset_dir),
        "access": subset_access,
    }
    if subset_dir:
        manifest_ids = subset_ids
        manifest_status.update({
            "official_membership_verified": len(manifest_ids) == 120 and manifest_ids <= set(official),
            "manifest_count": len(manifest_ids),
            "unknown_manifest_ids": sorted(manifest_ids - set(official)),
            "manifest_type_counts": collections.Counter(
                official[qid]["question_type"] for qid in manifest_ids if qid in official
            ),
        })

    audit = {
        "dataset": {
            "questions": len(full_questions), "question_evidences": len(full_evidences),
            "documents": len(rows(DATA / "documents.jsonl")),
            "document_pages": len(rows(DATA / "document_pages.jsonl")),
        },
        "representative_manifest": {
            **manifest_status,
            "question_count": len(subset_questions),
            "evidence_count": len(subset_evidences),
            "question_ids": sorted(subset_ids) if subset_dir else [],
            "question_type_counts": dict(collections.Counter(
                official[qid]["question_type"] for qid in subset_ids if qid in official
            )),
            "source_type_counts": dict(collections.Counter(
                source for qid in subset_ids if qid in official
                for source in official[qid].get("dataset_source_types", [])
            )),
        },
        "current_24": {
            "count": len(current_ids), "all_ids_in_official": current_ids <= set(official),
            "question_type_counts": dict(current_type_counts),
            "gold_document_count": len(current_doc_ids),
            "gold_page_count": len(current_gold_pages),
            "gold_document_ids": sorted(current_doc_ids),
            "all_gold_documents_in_corpus": all(
                coverage(q)["all_gold_documents_in_corpus"] for q in current_official
            ),
            "all_gold_pages_in_corpus": all(
                coverage(q)["all_gold_pages_in_corpus"] for q in current_official
            ),
        },
        "frozen_corpus": {
            "documents": len(corpus_docs), "pages": len(corpus_pages),
            "eligible_nodes": len(eligible_nodes),
            "pages_by_document": dict(pages_by_doc),
            "embedding_dimensions": 4096,
            "embedding_profile": "Qwen3-Embedding-8B last_token L2 normalized",
        },
        "reusable_official_pool_by_document_gate": {
            "query_count": len(reusable), "question_type_counts": dict(reusable_type_counts),
            "all_gold_documents_present": True,
        },
        "reproducible_candidate_120_not_official": {
            "count": len(candidate_120), "question_type_counts": dict(
                collections.Counter(q["question_type"] for q, _ in candidate_120)
            ),
            "document_count": len(selected_docs), "gold_page_count": len(selected_pages),
            "gold_pages_missing_from_frozen_nodes": len(selected_missing_pages),
            "new_gold_pages": len(selected_pages - current_gold_pages),
            "new_documents": len(selected_docs - current_doc_ids),
            "requires_new_node_embedding": len(selected_missing_pages),
            "note": "Fallback estimate only; never report as official membership.",
        },
        "resource_plan": {
            "no_gpu_preparation": [
                "Reuse official question/evidence metadata and frozen 6,520-node vectors.",
                "Prepare only missing document/page membership and node-input manifests on CPU.",
                "Run D0/D0+ ranking from frozen node vectors; D1 subquery encoding is the only model-dependent step.",
            ],
            "consistency_gate": [
                "New nodes must use the same Qwen3-Embedding-8B checkpoint, tokenizer, last-token pooling, left padding, max_length=512, L2 normalization.",
                "Do not compare 0.6B query vectors with frozen 8B node vectors.",
                "Abort if model/config/tokenizer hashes or vector dimension differ.",
            ],
            "storage_estimates": {
                "float32_bytes_per_node": 4096 * 4,
                "float32_mib_per_node": round(4096 * 4 / 2**20, 6),
                "float32_mib_per_10000_nodes": round(10000 * 4096 * 4 / 2**20, 2),
                "note": "Exact new node count requires parsing the missing pages; gold-page count is a lower bound, not a node count.",
            },
            "budget_arms": ["D0 Top-10", "D0+ Dense Top-13", "D1 Top-10 + 3 existing D1 nodes"],
            "evaluation": ["RecallAll", "bbox-supported coverage", "AI-assisted Requirement Coverage"],
            "structure_breakdown": list(STRUCTURES),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    (args.out / "current_24_query_coverage.jsonl").write_text(
        "".join(json.dumps({"question_id": q["question_id"], "question_type": q["question_type"],
                            **coverage(q)}, ensure_ascii=False) + "\n" for q in current_official)
    )
    (args.out / "reusable_official_pool.jsonl").write_text(
        "".join(json.dumps({"question_id": q["question_id"], "question_type": q["question_type"],
                            **cov}, ensure_ascii=False) + "\n" for q, cov in reusable)
    )
    (args.out / "candidate_120_not_official.jsonl").write_text(
        "".join(json.dumps({"question_id": q["question_id"], "question_type": q["question_type"],
                            **cov}, ensure_ascii=False) + "\n" for q, cov in candidate_120)
    )
    report = [
        "# VL-DocIR Representative Expansion Feasibility Audit",
        "",
        "本轮为只读数据审计；未提交 GPU/CPU 作业，未修改 24-query 输出，未重新生成 Embedding。",
        "",
        "## 结论",
        f"- 完整本地 VL-DocIR 包含 {len(full_questions):,} Query；官方独立仓库已确认存在，但其四个数据文件当前因 gated/manual access 返回 HTTP 401。",
        f"- 当前 24 Query 全部存在于官方 questions.jsonl，且六种 Evidence Structure 各 4 条。",
        f"- 当前冻结语料：{len(corpus_docs)} 文档、{len(corpus_pages)} 页、{len(eligible_nodes)} eligible Node、4096 维 Qwen3-Embedding-8B Node vector。",
        f"- 按“Gold Document 全部在冻结语料”筛选，官方可复用候选池为 {len(reusable):,} Query；类型分布见 audit.json。",
        f"- 可复现但非官方的候选 120：六种结构各取 ID 排序前 20；本轮仅用于估算资源，不用于正式结果。",
        "",
        "## 严格纳入条件",
        "正式纳入任何扩展 Query 前，必须同时验证 question_id 在官方 metadata、全部 Gold Document 在候选语料、并记录每个 Gold page 的 Node/Embedding 可用性。缺失页面不能用同页替代，也不能把 Gold Node 当作新增 Edge。",
        "",
        "## 增量方案",
        "- CPU：读取 metadata/evidence、生成 Query manifest、计算文档/页面/Node 缺口和 hash。",
        "- Parsing：仅处理新增 document/page，不触碰既有 32 文档和 6,520 Node。",
        "- Embedding：新 Node 必须由与冻结向量完全一致的 Qwen3-Embedding-8B 协议生成；D0/D0+ 可复用冻结向量。",
        "- D1：只为新增 Query 的 subquery 生成向量；三组 Arm 统一 13 Node 总预算。",
        "- 评估：六种 Evidence Structure 分别报告 RecallAll、bbox-supported 和 AI-assisted Requirement Coverage。",
        "",
        "## 阻断项",
        "在获得官方 120-ID 清单前，不提交扩展 Retrieval 作业；否则会把自定义候选 120 与官方 Representative Subset 混淆。",
    ]
    (args.out / "FEASIBILITY_AUDIT.md").write_text("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
