#!/usr/bin/env python3
"""Report the completed retrieval once per frozen 111-query manifest."""
import collections
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "EvidenceNet/output/custom_vldocir_benchmark_v1_20261106"
MANIFESTS = ROOT / "EvidenceNet/output/custom_vldocir_subset_v2_20261106"
OUT = ROOT / "EvidenceNet/output/custom_vldocir_benchmark_v1_20261106"
REQ = ROOT / "EvidenceNet/output/answer_requirement_sufficiency_audit_v2_20261106/query_requirement_diagnostics.jsonl"


def rows(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def requirement_state(qid, node_ids, requirement_by_q, text_by_node):
    if qid not in requirement_by_q:
        return None
    text = " ".join(text_by_node.get(n, "") for n in node_ids).lower()
    states = []
    for item in requirement_by_q[qid]["requirements"]:
        groups = item["requirement"].get("groups", [])
        matched = [g for g in groups if any(t.lower() in text for t in g)]
        states.append("supported" if groups and len(matched) == len(groups)
                      else "partial" if matched else "missing")
    return states


def main():
    records = {r["question_id"]: r for r in rows(RUN / "retrieval_records.jsonl")}
    manifests = {
        "doc_page_complete_111": rows(MANIFESTS / "doc_page_complete_111_manifest.jsonl"),
        "bbox_complete_111": rows(MANIFESTS / "bbox_complete_111_manifest.jsonl"),
    }
    if any(len(v) != 111 or len({r["question_id"] for r in v}) != 111 for v in manifests.values()):
        raise ValueError("manifest is not exactly 111 unique queries")
    if not all(set(r["question_id"] for r in v) <= set(records) for v in manifests.values()):
        raise ValueError("retrieval output does not cover a manifest")
    views = rows(ROOT / "migration/vldocir-edge-20261022/results/views.jsonl")
    node_pages = {
        r["id"]: [r["document"], int(r["page"])]
        for r in rows(ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl")
    }
    text_by_node = {}
    for view in views:
        text_by_node[view["node_id"]] = max(text_by_node.get(view["node_id"], ""), view.get("quote", ""), key=len)
    req = {r["question_id"]: r for r in rows(REQ)}
    diagnostics = {}
    for name, manifest_rows in manifests.items():
        manifest = {r["question_id"]: r for r in manifest_rows}
        per_query = []
        for qid, row in manifest.items():
            result = records[qid]
            gold_pages = {tuple(p) for p in row["gold_pages"]}
            evidence_nodes = {
                match["node_id"]
                for matches in row["bbox_node_matches"].values()
                for match in matches
            }
            arms = {}
            for arm, ids in (
                ("d0_top10", result["d0_top10"]),
                ("dense_top13", result["dense_top13"]),
                ("d1", result["d1_top13"]),
            ):
                pages = {
                    tuple(node_pages.get(node, [None, None]))
                    for node in ids
                }
                page_complete = gold_pages <= pages
                bbox = bool(evidence_nodes & set(ids)) if evidence_nodes else False
                req_states = requirement_state(qid, ids, req, text_by_node)
                arms[arm] = {
                    "gold_page_complete": page_complete,
                    "bbox_supported": bbox,
                    "requirement_states": req_states,
                    "requirement_fully_supported": (
                        all(s == "supported" for s in req_states)
                        if req_states is not None else None
                    ),
                    "node_ids": ids,
                }
            per_query.append({
                "question_id": qid, "question": result["question"],
                "question_type": result["question_type"], "arms": arms,
                "d1_added": result["d1_added"],
                "d1_unique_vs_dense13": sorted(set(result["d1_top13"]) - set(result["dense_top13"])),
                "gold_documents": row["gold_document_ids"],
            })
        clusters = collections.defaultdict(list)
        for query in per_query:
            clusters["|".join(sorted(query["gold_documents"]))].append(query)
        rng = random.Random(20261106)
        cluster_values = list(clusters.values())
        uncertainty = {}
        for field in ("gold_page_complete", "bbox_supported"):
            uncertainty[field] = {}
            for arm in ("d0_top10", "dense_top13", "d1"):
                samples = []
                for _ in range(2000):
                    draw = [cluster_values[rng.randrange(len(cluster_values))] for _ in cluster_values]
                    flat = [query for cluster in draw for query in cluster]
                    samples.append(sum(q["arms"][arm][field] for q in flat) / len(flat))
                samples.sort()
                uncertainty[field][arm] = {
                    "mean": sum(samples) / len(samples),
                    "ci95": [samples[50], samples[1949]],
                    "cluster_count": len(cluster_values),
                }
        def count(arm, field):
            return sum(bool(q["arms"][arm][field]) for q in per_query)
        structure = {}
        for st in sorted({q["question_type"] for q in per_query}):
            group = [q for q in per_query if q["question_type"] == st]
            structure[st] = {
                field: {
                    arm: sum(bool(q["arms"][arm][field]) for q in group)
                    for arm in ("d0_top10", "dense_top13", "d1")
                }
                for field in ("gold_page_complete", "bbox_supported", "requirement_fully_supported")
            }
        diagnostics[name] = {
            "query_count": len(per_query),
            "arms": {
                field: {arm: count(arm, field) for arm in ("d0_top10", "dense_top13", "d1")}
                for field in ("gold_page_complete", "bbox_supported", "requirement_fully_supported")
            },
            "d1_unique_vs_dense13": {
                field: sum(bool(q["arms"]["d1"][field]) and not bool(q["arms"]["dense_top13"][field])
                           for q in per_query)
                for field in ("gold_page_complete", "bbox_supported")
            },
            "d1_loss_vs_dense13": {
                field: sum(bool(q["arms"]["dense_top13"][field]) and not bool(q["arms"]["d1"][field])
                           for q in per_query)
                for field in ("gold_page_complete", "bbox_supported")
            },
            "structure": structure,
            "document_cluster_uncertainty": uncertainty,
            "per_query": per_query,
            "requirement_coverage_note": (
                "Only the prior 24-query requirement schema exists; new-query "
                "AI-assisted Requirement Coverage is NOT evaluated and is not treated as Gold."
            ),
        }
    overlap = set(next(iter(manifests.values()))[i]["question_id"] for i in range(111)) & {
        r["question_id"] for r in manifests["bbox_complete_111"]
    }
    summary = {
        "retrieval_record_union_count": len(records),
        "manifest_counts": {k: len(v) for k, v in manifests.items()},
        "manifest_intersection_count": len(overlap),
        "manifest_union_count": len(set(records) & (
            {r["question_id"] for r in manifests["doc_page_complete_111"]} |
            {r["question_id"] for r in manifests["bbox_complete_111"]}
        )),
        "protocol": "D0 Top-10, Dense Top-13, D1 Top-10 + 3; same 6,520-node universe",
        "d1_subquery_gold_leakage": False,
        "edge_construction_changed": False,
        "requirement_coverage_status": "not evaluated for new 111-query sets",
    }
    (OUT / "custom_111_diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n")
    (OUT / "custom_111_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Custom VL-DocIR 111-query Retrieval Benchmark",
        "",
        "数据集标签：**Custom VL-DocIR Subset**，不是官方 Representative Subset。",
        "",
        "## Protocol correction",
        f"- 两个独立 manifest 各 111 条；交集 {len(overlap)} 条。",
        f"- 检索作业为两套 manifest 的并集，共 {len(records)} 条，因此本报告分别切分，不能把 125 条报告为一个 111-query 集合。",
        "- D0=Top-10，D0+=Dense Top-13，D1=Top-10+3；候选 universe=6,520。",
        "",
    ]
    for name, result in diagnostics.items():
        lines += [f"## {name}", ""]
        for field, label in (
            ("gold_page_complete", "Gold Page 完整覆盖"),
            ("bbox_supported", "bbox-supported Coverage"),
            ("requirement_fully_supported", "AI-assisted Requirement Coverage"),
        ):
            vals = result["arms"][field]
            lines.append(f"- {label}: D0 {vals['d0_top10']}/111；D0+ {vals['dense_top13']}/111；D1 {vals['d1']}/111")
        lines.append(
            f"- D1 独有收益：Gold Page {result['d1_unique_vs_dense13']['gold_page_complete']}；"
            f"bbox {result['d1_unique_vs_dense13']['bbox_supported']}；"
            "Requirement N/A（新测试集未建立独立 Requirement schema）"
        )
        lines.append("")
        lines.append("### Document-cluster bootstrap 95% intervals")
        for field in ("gold_page_complete", "bbox_supported"):
            values = result["document_cluster_uncertainty"][field]
            lines.append(f"- {field}: " + json.dumps(values, ensure_ascii=False))
        lines.append("### Structure breakdown")
        for st, values in result["structure"].items():
            lines.append(f"- {st}: " + json.dumps(values, ensure_ascii=False))
        lines.append("")
    lines += [
        "## Requirement Coverage limitation",
        "新 111-query 测试集没有人工或独立 AI-assisted Requirement schema；旧 24-query schema 未外推，避免把答案或旧标签泄漏到测试集。因此本报告对新集的 Requirement Coverage 标记为 N/A，而不是伪造指标。",
        "",
        "完整逐 Query 数据见 `custom_111_diagnostics.json`。",
    ]
    (OUT / "CUSTOM_111_RETRIEVAL_REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
