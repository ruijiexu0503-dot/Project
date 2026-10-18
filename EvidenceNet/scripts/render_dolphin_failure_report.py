#!/usr/bin/env python3
"""Render remaining positive retrieval failures for Dolphin three-lane RRF."""

from __future__ import annotations

from collections import Counter
from html import escape
import json
import os
from pathlib import Path

from dolphin_softwrap import render_softwrap
from run_node_context_edges import ROOT, jsonl, read, rows, write


BASE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
PHYSICAL = ROOT / "EvidenceNet/output/edge_candidate_allocation_repair_v2_20261017"
SOFT = ROOT / "EvidenceNet/output/dolphin_softwrap_retrieval_v2_20261018"
OUT = ROOT / "EvidenceNet/output/dolphin_three_lane_retrieval_v2_20261018"
SOURCE_ROOTS = {
    "traffic": ROOT / "EvidenceNet/output/paper_relevance_urban_traffic_20261013/graph",
    "expanded": ROOT / "EvidenceNet/output/article_bridge_expanded_v5_20261012",
}
RRF_K = 60


def pair_key(pair: dict) -> tuple[str, str]:
    return tuple(sorted((pair["source"], pair["target"])))


def ranked(path: Path) -> tuple[dict, list[dict]]:
    values = rows(path)
    return {pair_key(pair): rank for rank, pair in enumerate(values, 1)}, values


def relative_image(node: dict, output: Path) -> str | None:
    for member in node.get("members", []):
        if not member.get("crop"):
            continue
        source = SOURCE_ROOTS[node["source_collection"]] / member["crop"]
        if source.exists():
            return os.path.relpath(source, output)
    return None


def excerpt(raw: str, limit: int = 1500) -> str:
    value = raw if len(raw) <= limit else raw[:limit] + "\n…"
    return escape(value).replace("\n", '<mark class="nl">↵</mark>\n')


def rank_text(value: int | None) -> str:
    return "—" if value is None else f"#{value:,}"


def main() -> None:
    cases = {case["suite_case_id"]: case for case in rows(BASE / "evaluation/cases.jsonl")}
    nodes = {node["id"]: node for node in rows(BASE / "corpus_nodes.jsonl")}
    coverage_rows = read(OUT / "case_coverage.json")["three_lane_rrf"]
    missed_ids = [item["suite_case_id"] for item in coverage_rows
                  if item["label"] == "POSITIVE" and not item["retrieved"]]

    rank_maps = {}
    for name, path in {
        "long_initial": BASE / "initial_pool.jsonl",
        "physical_initial": PHYSICAL / "initial_pool.jsonl",
        "softwrap_initial": SOFT / "initial_pool.jsonl",
        "long_final": BASE / "hierarchical_candidates.jsonl",
        "physical_final": PHYSICAL / "native_candidates.jsonl",
        "softwrap_final": SOFT / "native_candidates.jsonl",
    }.items():
        rank_maps[name], _ = ranked(path)

    arm_values = {
        "long": rows(BASE / "hierarchical_candidates.jsonl")[:1301],
        "physical": rows(PHYSICAL / "eligible_only_candidates.jsonl")[:1301],
        "softwrap": rows(SOFT / "bounded_candidates.jsonl"),
    }
    rrf_pool = {}
    for arm, values in arm_values.items():
        for rank, pair in enumerate(values, 1):
            item = rrf_pool.setdefault(pair_key(pair), {"score": 0.0, "ranks": {}})
            item["score"] += 1 / (RRF_K + rank)
            item["ranks"][arm] = rank
    rrf_order = sorted(rrf_pool, key=lambda key: (-rrf_pool[key]["score"], *key))
    rrf_ranks = {key: rank for rank, key in enumerate(rrf_order, 1)}

    records, categories = [], Counter()
    visual_cases = {"P18", "P20", "P22", "P23"}
    for case_id in missed_ids:
        case = cases[case_id]
        key = tuple(sorted((case["A"]["node_id"], case["B"]["node_id"])))
        ranks = {name: mapping.get(key) for name, mapping in rank_maps.items()}
        initial = any(ranks[name] is not None for name in ("long_initial", "physical_initial", "softwrap_initial"))
        final = any(ranks[name] is not None for name in ("long_final", "physical_final", "softwrap_final"))
        if not initial:
            category = "initial_pool_miss"
            diagnosis = "三种表示都没有把这对节点带进初始池；这是表示/检索相似度问题。"
        elif not final:
            category = "selector_quota_miss"
            diagnosis = "已经进入初始池，但在 article route、degree cap 或 pair quota 阶段被挤掉。"
        else:
            category = "fusion_budget_miss"
            diagnosis = "至少一路已选中，但在三路 RRF 的共同 1,301 预算中排名不足。"
        if case_id in visual_cases:
            diagnosis += " 这是一条正文↔图的显式对应，更适合由 figure-reference lane 保护。"
        categories[category] += 1
        endpoints = {}
        for side in ("A", "B"):
            node = nodes[case[side]["node_id"]]
            raw = case[side]["primary_anchor"]["quote"]
            endpoints[side] = {
                "node_id": node["id"], "document": node["document"], "page": node["page"],
                "raw": raw, "softwrap": render_softwrap(raw, True),
                "image": relative_image(node, OUT),
            }
        records.append({"case_id": case_id, "relation": case["relation"],
                        "rationale": case["rationale"], "conditions": case.get("conditions", ""),
                        "category": category, "diagnosis": diagnosis, "ranks": ranks,
                        "rrf_rank": rrf_ranks.get(key), "rrf_arm_ranks": rrf_pool.get(key, {}).get("ranks", {}),
                        "endpoints": endpoints})

    jsonl(OUT / "remaining_failures.jsonl", records)
    write(OUT / "remaining_failure_summary.json", {"missed": len(records), "categories": dict(categories)})

    labels = {"initial_pool_miss": "初始池缺失", "selector_quota_miss": "选择/配额丢失",
              "fusion_budget_miss": "RRF 预算丢失"}
    cards = []
    for record in records:
        endpoint_html = []
        for side in ("A", "B"):
            endpoint = record["endpoints"][side]
            image = (f'<img src="{escape(endpoint["image"])}" alt="{side} visual">'
                     if endpoint["image"] else "")
            endpoint_html.append(f'''<section class="endpoint"><h3>{side} · {escape(endpoint["document"])} · p.{endpoint["page"]}</h3>
              {image}<h4>原始 quote（↵ 为 Dolphin 换行）</h4><pre>{excerpt(endpoint["raw"])}</pre>
              <details><summary>soft-wrap 检索文本</summary><p>{escape(endpoint["softwrap"][:1800])}</p></details></section>''')
        r = record["ranks"]
        cards.append(f'''<article class="case" id="{record["case_id"]}">
          <header><div><span class="badge {record["category"]}">{labels[record["category"]]}</span><h2>{record["case_id"]} · {escape(record["relation"])}</h2></div>
          <span class="rrf">RRF rank {rank_text(record["rrf_rank"])}</span></header>
          <p class="rationale">{escape(record["rationale"])}</p>
          <div class="rankgrid"><div><b>长窗口</b><span>pool {rank_text(r["long_initial"])} · final {rank_text(r["long_final"])}</span></div>
          <div><b>物理行</b><span>pool {rank_text(r["physical_initial"])} · final {rank_text(r["physical_final"])}</span></div>
          <div><b>soft-wrap</b><span>pool {rank_text(r["softwrap_initial"])} · final {rank_text(r["softwrap_final"])}</span></div></div>
          <p class="diagnosis">{escape(record["diagnosis"])}</p><div class="endpoints">{''.join(endpoint_html)}</div></article>''')

    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dolphin retrieval remaining failures</title><style>
:root{{--bg:#f5f4ef;--card:#fff;--ink:#20241f;--muted:#697069;--line:#d9ddd7;--red:#a94337;--amber:#a96d12;--blue:#315f9d}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Noto Sans SC",sans-serif}}main{{max-width:1180px;margin:auto;padding:34px 22px 70px}}h1{{font-size:30px;margin:0 0 5px}}.sub{{color:var(--muted)}}.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}.metric,.case{{background:var(--card);border:1px solid var(--line);border-radius:13px}}.metric{{padding:16px}}.big{{font-size:27px;font-weight:750}}.case{{padding:20px;margin:20px 0}}.case header{{display:flex;justify-content:space-between;gap:12px;align-items:start}}h2{{font-size:20px;margin:7px 0}}h3{{font-size:14px;margin:0 0 10px}}h4{{font-size:12px;color:var(--muted);margin:10px 0 5px}}.badge{{font-size:12px;font-weight:700;padding:4px 9px;border-radius:99px;background:#fff0e6;color:var(--red)}}.initial_pool_miss{{background:#fbe8e6}}.fusion_budget_miss{{background:#edf1fa;color:var(--blue)}}.rrf{{font-variant-numeric:tabular-nums;color:var(--muted)}}.rationale{{font-weight:600}}.rankgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.rankgrid div{{background:#f5f6f3;padding:10px;border-radius:8px}}.rankgrid span{{display:block;color:var(--muted);font-size:13px}}.diagnosis{{border-left:4px solid var(--amber);padding:10px 12px;background:#fff7e8}}.endpoints{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.endpoint{{min-width:0;border-top:1px solid var(--line);padding-top:14px}}pre{{white-space:pre-wrap;overflow:auto;max-height:320px;background:#202420;color:#f2f4ef;padding:13px;border-radius:8px;font:12px/1.55 ui-monospace,monospace}}mark.nl{{background:#f4b860;color:#302000;border-radius:2px}}img{{width:100%;height:270px;object-fit:contain;background:#111;border-radius:8px}}details p{{background:#eef3ed;padding:11px;border-radius:8px}}a{{color:var(--blue)}}@media(max-width:760px){{.summary,.rankgrid{{grid-template-columns:1fr 1fr}}.endpoints{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>三路 Dolphin retrieval：剩余失败例</h1>
<p class="sub">固定 1,301 pair；15/26 正例已召回，下面是剩余 11 例。这里分析的是 candidate retrieval，不是 identity verifier。</p>
<div class="summary"><div class="metric"><div class="big">11</div><div>剩余正例</div></div><div class="metric"><div class="big">{categories['initial_pool_miss']}</div><div>初始池完全缺失</div></div><div class="metric"><div class="big">{categories['selector_quota_miss']}</div><div>选择/配额丢失</div></div><div class="metric"><div class="big">{categories['fusion_budget_miss']}</div><div>RRF 预算丢失</div></div></div>
<p><b>先看结论：</b>只有 P12 是三种表示都没召回；9 例其实已在至少一个 initial pool 中，主要问题已经从“换行断句”转移为 selector/quota；P26 被物理行方案选中，但在 RRF 共同预算中被挤掉。P18/P20/P22/P23 是正文↔图对应，应由显式 figure-reference lane 保护。</p>
{''.join(cards)}<p class="sub">数据：<a href="remaining_failures.jsonl">remaining_failures.jsonl</a> · <a href="summary.json">retrieval summary</a></p></main></body></html>'''
    (OUT / "failures.html").write_text(html)
    print(json.dumps({"output": str(OUT / "failures.html"), "missed": len(records),
                      "categories": dict(categories)}))


if __name__ == "__main__":
    main()
