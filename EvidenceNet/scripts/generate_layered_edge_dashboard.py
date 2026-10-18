#!/usr/bin/env python3
"""Build a standalone-ish HTML review page for the layered edge verifier."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import quote


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def short_quote(anchors: list[dict], limit: int = 430) -> str:
    text = "\n\n".join(a.get("quote", "") for a in anchors)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def node_id(anchors: list[dict]) -> str:
    return anchors[0].get("node_id", "") if anchors else ""


def crop_url(anchors: list[dict]) -> str | None:
    for anchor in anchors:
        path = anchor.get("crop")
        if path and Path(path).is_file():
            return quote(path, safe="/")
    return None


def result_status(reference: dict, result: dict) -> tuple[str, str]:
    # The ordinal reference regards levels 2 and 3 as related, and 0/1 as
    # unrelated. Some cases allow more than one exact ordinal level.
    expected_positive = max(reference.get("allowed_levels", [0])) >= 2
    predicted_positive = result.get("decision") != "NO_LINK"
    if expected_positive and predicted_positive:
        return "TP", "ok"
    if expected_positive:
        return "FN", "miss"
    if predicted_positive:
        return "FP", "bad"
    return "TN", "ok"


def is_caption(text: str) -> bool:
    clean = text.strip()
    return bool(
        re.match(r"^(?:fig(?:ure)?\.?\s*\d+|table\s*\d+|\d+\.\s+[^\n]{3,})", clean, re.I)
    )


def inferred_reference_direction(edge: dict) -> str:
    a_text = " ".join(x.get("quote", "") for x in edge["anchors"].get("A", []))
    b_text = " ".join(x.get("quote", "") for x in edge["anchors"].get("B", []))
    a_caption, b_caption = is_caption(a_text), is_caption(b_text)
    if a_caption and not b_caption:
        return "B_TO_A"
    if b_caption and not a_caption:
        return "A_TO_B"
    return "UNCERTAIN"


def endpoint(label: str, anchors: list[dict]) -> str:
    image = crop_url(anchors)
    image_html = f'<img loading="lazy" src="{image}" alt="{esc(label)} visual crop">' if image else ""
    return f"""
      <section class="endpoint">
        <div class="endpoint-head"><b>{esc(label)}</b><code>{esc(node_id(anchors))}</code></div>
        {image_html}
        <pre>{esc(short_quote(anchors))}</pre>
      </section>"""


def case_card(row: dict, old: dict | None) -> str:
    ref = row["reference"]
    result = row["prediction"]["result"]
    status, status_class = result_status(ref, result)
    old_result = (old or {}).get("prediction", {}).get("result", {})
    old_level = old_result.get("level", "–")
    case_id = ref.get("suite_case_id") or row["prediction"]["task_id"]
    anchors = result.get("anchors", {})
    relation = result.get("relation") or "—"
    return f"""
    <article class="case" data-status="{status}" data-decision="{esc(result['decision'])}"
      data-case="{esc(case_id)}">
      <div class="case-title">
        <div><span class="pill {status_class}">{status}</span><h3>{esc(case_id)}</h3></div>
        <div class="labels">
          <span class="pill decision-{result['decision'].lower()}">{esc(result['decision'])}</span>
          <span>{esc(result.get('basis') or '—')}</span><span>{esc(relation)}</span>
        </div>
      </div>
      <div class="transition">旧 verifier level <b>{esc(old_level)}</b><span>→</span>新 verifier <b>{esc(result['decision'])}</b></div>
      <p class="claim">{esc(result.get('matched_claim') or '')}</p>
      <div class="pair">{endpoint('A', anchors.get('A', []))}{endpoint('B', anchors.get('B', []))}</div>
      <details><summary>模型理由与限制</summary><p>{esc(result.get('reason', ''))}</p><p class="muted">{esc(result.get('limitation', ''))}</p></details>
    </article>"""


def reference_card(edge: dict) -> str:
    model_direction = edge["explicit_reference"]
    pointer_direction = inferred_reference_direction(edge)
    same = model_direction == pointer_direction
    cls = "ok" if same else "warn"
    anchors = edge["anchors"]
    return f"""
    <article class="reference-card">
      <div class="case-title"><h3>{esc(edge['id'])}</h3><span class="pill {cls}">{'一致' if same else '需拆分/复核'}</span></div>
      <div class="direction-grid">
        <div><small>LLM explicit_reference</small><b>{esc(model_direction)}</b></div>
        <div class="arrow">→</div>
        <div><small>按显式 Fig./Table 指针</small><b>{esc(pointer_direction)}</b></div>
      </div>
      <p class="claim">{esc(edge.get('matched_claim', ''))}</p>
      <div class="pair">{endpoint('A', anchors.get('A', []))}{endpoint('B', anchors.get('B', []))}</div>
    </article>"""


def build(root: Path, output: Path) -> None:
    new_dir = root / "EvidenceNet/output/layered_edge_verifier_v1_20261016"
    old_dir = root / "EvidenceNet/output/relatedness_ordinal_mixed_v1_20261015"
    summary = json.loads((new_dir / "summary.json").read_text(encoding="utf-8"))
    old_summary = json.loads((old_dir / "summary.json").read_text(encoding="utf-8"))
    new_rows = read_jsonl(new_dir / "evaluation/review.jsonl")
    old_rows = {r["reference"]["task_id"]: r for r in read_jsonl(old_dir / "evaluation/review.jsonl")}
    refs = read_jsonl(new_dir / "reference_edges.jsonl")
    evaluable = [r for r in new_rows if r["reference"].get("cutoff_evaluable")]

    cards = "\n".join(case_card(r, old_rows.get(r["reference"]["task_id"])) for r in evaluable)
    ref_cards = "\n".join(reference_card(r) for r in refs)
    counts = summary["decisions"]
    max_decision = max(counts.values())
    bars = "".join(
        f'<div class="bar-row"><span>{esc(label)}</span><div class="bar"><i class="bar-{key.lower()}" style="width:{value / max_decision * 100:.1f}%"></i></div><b>{value}</b></div>'
        for key, label, value in [
            ("EVIDENCE", "Evidence", counts["EVIDENCE_LINK"]),
            ("NAVIGATION", "Navigation", counts["NAVIGATION_LINK"]),
            ("NO_LINK", "No link", counts["NO_LINK"]),
        ]
    )
    old_ref = old_summary["reference_counts"]
    new_ref = summary["reference_cutoff_counts"]
    html_text = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Layered Edge Verifier · 可视化复核</title>
<style>
:root{{--ink:#172638;--muted:#66758a;--paper:#fff;--bg:#f3f6fa;--line:#dce4ed;--blue:#2878c8;--teal:#148f83;--red:#c84c4c;--amber:#c47a16;--slate:#738299}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1280px;margin:auto;padding:28px 22px 80px}} h1{{font-size:30px;margin:0 0 8px}} h2{{margin-top:40px}} h3{{margin:0;font-size:16px}} p{{max-width:1000px}}
.hero,.panel,.case,.reference-card{{background:var(--paper);border:1px solid var(--line);border-radius:16px;box-shadow:0 3px 16px #24364a0a}}
.hero{{padding:26px}} .hero-grid{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:22px}} .panel{{padding:20px}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}} .metric{{background:#f7f9fc;padding:13px;border-radius:11px;text-align:center}} .metric b{{display:block;font-size:25px}} .metric small,.muted,small{{color:var(--muted)}}
.comparison{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px}} .score{{padding:16px;border-radius:12px;background:#f7f9fc;text-align:center}} .score b{{font-size:23px;display:block}} .big-arrow{{font-size:27px;color:var(--teal)}}
.bar-row{{display:grid;grid-template-columns:90px 1fr 32px;gap:10px;align-items:center;margin:13px 0}} .bar{{height:14px;background:#edf1f6;border-radius:99px;overflow:hidden}} .bar i{{display:block;height:100%;border-radius:99px}} .bar-evidence{{background:var(--blue)}} .bar-navigation{{background:var(--teal)}} .bar-no_link{{background:var(--slate)}}
.direction-model{{display:grid;grid-template-columns:1fr 60px 1fr;gap:12px;align-items:stretch;margin-top:16px}} .direction-model>div{{padding:17px;background:#f7f9fc;border-radius:12px}} .direction-model .center{{display:grid;place-items:center;background:none;font-size:26px}}
.direction-model code{{display:block;margin-top:8px;color:#314860}} .controls{{position:sticky;top:0;z-index:5;background:#f3f6faeF;backdrop-filter:blur(8px);padding:13px 0;display:flex;gap:9px;flex-wrap:wrap}}
button{{border:1px solid #cad5e1;background:white;border-radius:99px;padding:8px 13px;cursor:pointer}} button.active{{background:var(--ink);color:white;border-color:var(--ink)}}
.case,.reference-card{{padding:20px;margin:15px 0}} .case-title{{display:flex;align-items:center;justify-content:space-between;gap:14px}} .case-title>div{{display:flex;align-items:center;gap:9px}} .labels{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}} .labels span,.pill{{padding:4px 9px;border-radius:99px;background:#edf1f6;font-size:12px}}
.pill.ok{{background:#dff5eb;color:#096c54}} .pill.bad{{background:#ffe1e1;color:#9d2929}} .pill.miss,.pill.warn{{background:#fff0d8;color:#8a5510}} .decision-evidence_link{{color:#185f9f!important;background:#e2f0ff!important}} .decision-navigation_link{{color:#087266!important;background:#dcf6f1!important}}
.transition{{margin:14px 0;color:var(--muted)}} .transition span{{padding:0 13px;color:var(--teal)}} .claim{{font-weight:650}} .pair{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .endpoint{{min-width:0;border:1px solid var(--line);border-radius:12px;padding:13px}} .endpoint-head{{display:flex;gap:9px;align-items:center;margin-bottom:9px}} code{{overflow-wrap:anywhere;font-size:11px;color:var(--muted)}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;background:#f7f9fc;padding:12px;border-radius:9px;font:12px/1.5 ui-monospace,monospace}} img{{width:100%;max-height:360px;object-fit:contain;margin-bottom:10px;background:#fff}}
details{{margin-top:12px}} summary{{cursor:pointer;color:#365b7d}} .direction-grid{{display:grid;grid-template-columns:1fr 40px 1fr;gap:10px;align-items:center;margin:13px 0}} .direction-grid>div:not(.arrow){{background:#f7f9fc;border-radius:10px;padding:12px}} .direction-grid b,.direction-grid small{{display:block}} .arrow{{text-align:center;font-size:22px;color:var(--amber)}}
.hidden{{display:none}} .note{{border-left:4px solid var(--amber);padding:8px 15px;background:#fff8ea;border-radius:0 10px 10px 0}}
@media(max-width:800px){{.hero-grid,.pair,.direction-model{{grid-template-columns:1fr}} .direction-model .center{{display:none}} .metric-grid{{grid-template-columns:1fr 1fr}} .case-title{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><main>
<section class="hero"><h1>Layered Edge Verifier · 可视化复核</h1><p>103 个冻结 pair 的 shadow experiment。下方 58 个带 provisional reference 的样例可逐条筛选；这不是 held-out 或端到端 retrieval 指标。</p>
<div class="hero-grid"><div class="panel"><h3>新 verifier 决策分布</h3>{bars}</div>
<div class="panel"><h3>错连变化</h3><div class="comparison"><div class="score"><small>旧 verifier</small><b>{old_ref['fp']} FP</b><span>{old_ref['tp']} TP / {old_ref['fn']} FN</span></div><div class="big-arrow">→</div><div class="score"><small>分层 verifier</small><b>{new_ref.get('fp', 0)} FP</b><span>{new_ref['tp']} TP / {new_ref['fn']} FN</span></div></div></div></div>
<div class="metric-grid" style="margin-top:18px"><div class="metric"><b>{summary['processed']}</b><small>processed</small></div><div class="metric"><b>{summary['evidence_edges']}</b><small>evidence</small></div><div class="metric"><b>{summary['navigation_edges']}</b><small>navigation</small></div><div class="metric"><b>{summary['reference_edges']}</b><small>explicit refs</small></div></div></section>

<h2>方向为什么可以“两边都有道理”</h2>
<p class="note">你的直觉是对的。此前的“5 条方向错误”只针对字段 <code>explicit_reference</code> 的严格定义，并不代表图文语义关系只能朝一个方向。</p>
<div class="direction-model">
  <div><b>显式引用方向</b><code>正文 --REFERS_TO--&gt; Figure 7</code><p>由哪一端实际出现 “Fig. 7” 决定，属于文献结构事实。</p></div>
  <div class="center">≠</div>
  <div><b>语义角色方向</b><code>图片 --ILLUSTRATES--&gt; 文字主张</code><code>文字 --EXPLAINS--&gt; 图片</code><p>两种都合理，且互为不同关系；也可以另存对称的 <code>ASSOCIATED_WITH</code>。</p></div>
</div>

<h2>六条图文显式引用边</h2><p>左侧是模型字段，右侧只检查“哪一端写出了 Fig./Table 指针”。语义上的 illustrates/explains 不在这一列判错。</p>{ref_cards}

<h2>58 个可评估样例</h2>
<div class="controls"><button class="active" data-filter="ALL">全部</button><button data-filter="FP">FP</button><button data-filter="FN">FN</button><button data-filter="TP">TP</button><button data-filter="TN">TN</button><button data-filter="EVIDENCE_LINK">Evidence</button><button data-filter="NAVIGATION_LINK">Navigation</button><button data-filter="NO_LINK">No link</button></div>
<div id="cases">{cards}</div>
<script>document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('active'));b.classList.add('active');const f=b.dataset.filter;document.querySelectorAll('.case').forEach(c=>c.classList.toggle('hidden',f!=='ALL'&&c.dataset.status!==f&&c.dataset.decision!==f));}}));</script>
</main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.output or args.root / "EvidenceNet/output/layered_edge_verifier_v1_20261016/index.html"
    build(args.root.resolve(), destination.resolve())
    print(destination.resolve())


if __name__ == "__main__":
    main()
