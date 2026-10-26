#!/usr/bin/env python3
"""Build an offline, escaped edge-review page from an immutable graph and audit.

This is a source/claim review, not a retrieval-results dashboard. Focus notes
are human-review leads; neither these notes nor source-role routes are gold
labels for the truth of a model's claim or the validity of a broad RELATED edge.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'migration/vldocir-edge-20261022/results'
ROUTES = {
    'reference_review': '参考文献来源 · 待审',
    'administrative_review': '行政／声明类内容 · 待审',
    'semantic': '通过来源角色筛查 · 仍需语义核验',
}
FOCUS_NOTES = {
    'REL_b3f69c18d0e2e266': (
        '不同谓词被合并成共同 claim',
        'A 的原文是 “no competing interests”，B 的原文是 “no financial support was received”。'
        '无利益冲突与未收到财务支持是不同谓词；同属作者披露主题，不代表两端都陈述了这两个事实。'
        '请复核模型 matched_claim 和 reason 的合并是否越过原文。'),
    'REL_fdd92d94c346482c': (
        'obtained OR waived 的限定条件与同意用途',
        'B 的原文保留了 “obtained or waived”，不能删去 “or waived” 后断言一定获得了同意。'
        'A 讨论问卷访问前的数字同意，B 讨论治疗与开放获取发表的同意。'
        '程序主题相近不自动说明是同一研究或同一批参与者。'),
    'REL_7bdbef0921d8b6d8': (
        '要求提供、已经获得、获得或豁免不是同一个命题',
        'A 说 “was required to provide digital informed consent”，B 说 “was obtained or waived”。'
        '要求提供同意不应被自动改写为已经获得；“obtained or waived” 的选择条件也必须保留。'
        '请分别核对谓词、限定条件和模型关于 “same study” 的依据。'),
    'REL_4b2fb0480ff65b32': (
        '省略 OR waived 后把带条件声明强化为事实',
        'B 的完整原文是 “obtained or waived”，模型 reason 中的省略片段不能替代它。'
        'A 描述数字同意要求及参与流程，B 描述治疗与发表同意。'
        '请核对模型所说 “obtained from all participants” 是否被两端各自的原文支持。'),
    'REL_cf616a195193e963': (
        '程序相似不等于同一研究',
        '两端都涉及自愿参与、匿名与同意，因此宽泛 RELATED 可能有讨论空间。'
        '但 “same study” 是模型 added claim，不能仅凭共用伦理程序模板确认研究身份相同。'
        '请将主题／机制关联与实体身份判断分开复核。'),
    'REL_af7b78060a02bd79': (
        '文献条目被用作具体 claim 的证据',
        '两端展示的是不同文献条目。标题或主题相关可进入引用／文献关联通道，'
        '但不能仅凭条目推断两篇文献都陈述了同一个具体实验结论或指标比较。'
        '请对照原始 anchors 与 model matched_claim，而不是把模型理由当作原文。'),
}


def escaped(value) -> str:
    if value is None:
        value = '未提供'
    elif isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, indent=2)
    return html.escape(str(value), quote=True)


def snapshot(path: Path, jsonl=False):
    raw = path.read_bytes()
    value = ([json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
             if jsonl else json.loads(raw))
    return value, {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}


def indexed(records, key, label):
    result = {}
    for record in records:
        identity = record.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError(f'Missing/duplicate {label} ID: {identity!r}')
        result[identity] = record
    return result


def anchor_html(anchor):
    kind = str(anchor.get('kind', 'UNKNOWN'))
    if kind in {'ORIGINAL_TEXT', 'ORIGINAL_TABLE_ROW'}:
        category, label = 'original', '原始文本／表格 anchor'
    elif 'DESCRIPTION' in kind or 'GENERATED' in kind:
        category, label = 'generated', '生成描述：不等于原始文字证据'
    else:
        category, label = 'unknown', '其他 anchor：按 kind 原样展示'
    metadata = {key: value for key, value in anchor.items() if key not in {'kind', 'quote'}}
    return (
        f'<section class="anchor {category}"><div class="anchor-label">{escaped(label)}'
        f' · <code>{escaped(kind)}</code></div>'
        f'<pre class="quote">{escaped(anchor.get("quote", "未记录 quote"))}</pre>'
        f'<details><summary>anchor 定位与哈希</summary><pre>{escaped(metadata)}</pre></details></section>'
    )


def endpoint_html(edge, side, nodes, audit):
    field = 'source' if side == 'A' else 'target'
    node_id = edge[field]
    node = nodes[node_id]
    endpoint_audit = audit.get('endpoints', {}).get(field, {})
    anchors = edge.get('model_result', {}).get('anchors', {}).get(side, [])
    rendered_anchors = ''.join(anchor_html(anchor) for anchor in anchors)
    if not rendered_anchors:
        rendered_anchors = '<p class="notice">未记录 anchor；不会用模型理由补造原文。</p>'
    metadata = {
        'node': node_id,
        'document': node.get('document'),
        'page': node.get('page'),
        'node_type': node.get('node_type'),
        'source_atom_ids': node.get('source_atom_ids', []),
        'source_role': endpoint_audit.get('role'),
        'source_route': endpoint_audit.get('route'),
        'source_reasons': endpoint_audit.get('reasons', []),
    }
    return (f'<section class="endpoint"><h3>{side} · {escaped(field)}</h3>'
            f'<pre class="endpoint-meta">{escaped(metadata)}</pre>{rendered_anchors}</section>')


def edge_html(edge, nodes, audit):
    edge_id = edge['task_id']
    route = audit['route']
    model = edge.get('model_result', {})
    focus = FOCUS_NOTES.get(edge_id)
    review = ''
    if focus:
        review = (f'<section class="focus-note"><h3>人工复核线索：{escaped(focus[0])}</h3>'
                  f'<p>{escaped(focus[1])}</p><p class="muted">不是自动金标，也不是整条 RELATED 边已确定错误的判决。</p></section>')
    fields = ''.join(f'<div><dt>{escaped(key)}</dt><dd><pre>{escaped(model.get(key))}</pre></dd></div>'
                     for key in ('matched_claim', 'shared_identity', 'reason', 'limitation'))
    details = {key: edge.get(key) for key in ('edge_type', 'direction', 'status', 'evidence_propagation_allowed')}
    details['model_decision'] = model.get('decision')
    details['model_basis'] = model.get('basis')
    details['model_discovery_level'] = model.get('discovery_level')
    return (
        f'<article class="edge" id="{escaped(edge_id)}" data-route="{escaped(route)}" '
        f'data-focus="{str(bool(focus)).lower()}">'
        f'<header><h2><a href="#{escaped(edge_id)}">{escaped(edge_id)}</a></h2>'
        f'<span class="badge {escaped(route)}">{escaped(route)} · {escaped(ROUTES[route])}</span></header>'
        f'{review}<div class="endpoints">{endpoint_html(edge, "A", nodes, audit)}'
        f'{endpoint_html(edge, "B", nodes, audit)}</div>'
        f'<section class="model"><h3>模型输出 · 以下是待核验的解释，不是原始证据</h3><dl>{fields}</dl></section>'
        f'<details><summary>edge 元数据与完整来源角色审查</summary><pre>{escaped(details)}</pre>'
        f'<pre>{escaped(audit)}</pre></details></article>'
    )


STYLE = '''
:root{color-scheme:light;--ink:#183142;--muted:#566774;--line:#d8e2e7;--paper:#fff;--bg:#f3f6f8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,sans-serif}
main{max-width:1440px;margin:auto;padding:30px 24px 80px}h1{font-size:30px;margin:0 0 8px}h2{font-size:18px;margin:0}h3{font-size:15px;margin:0 0 10px}
p{margin:8px 0}a{color:#176c85;overflow-wrap:anywhere}pre{font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:7px 0}
.intro,.edge{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:22px;margin:20px 0}.intro{border-top:5px solid #287e8a}
.muted{color:var(--muted);font-size:13px}.notice{background:#fff7df;border-left:4px solid #b88624;padding:10px 14px}
.counts{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}.count{background:#edf4f6;padding:10px 14px;border-radius:8px}.count b{font-size:23px;margin-right:8px}
.filters{position:sticky;top:0;z-index:2;display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:14px;background:#e7eff2;border:1px solid #ccdce2;border-radius:8px}
select,input[type=search]{font:inherit;padding:7px;border:1px solid #a9bec7;border-radius:5px;background:white}input[type=search]{min-width:250px;flex:1}
.edge header{display:flex;flex-wrap:wrap;align-items:center;gap:12px;justify-content:space-between}.badge{font-size:12px;border-radius:5px;padding:4px 8px;background:#edf4f6}
.reference_review{background:#fff0d4}.administrative_review{background:#eee5f6}.semantic{background:#e9f1f3}
.endpoints{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.endpoint{min-width:0;padding:16px;border:1px solid var(--line);border-radius:8px}
.endpoint-meta{color:var(--muted);font-size:12px}.anchor{margin-top:14px;padding:12px;background:#f5f8fa;border-left:3px solid #438493}.anchor.generated{border-color:#ab7334;background:#fff5e7}
.anchor-label{font-size:12px;color:var(--muted)}.quote{font-family:ui-monospace,monospace;font-size:14px}.focus-note{margin:18px 0;padding:15px;background:#fff8e8;border:1px solid #ead7a7;border-radius:8px}
.model{padding:16px;background:#f0f3f8;border-radius:8px;margin:18px 0}dl{margin:0}dl>div{display:grid;grid-template-columns:140px 1fr;gap:12px}dt{font-size:12px;color:var(--muted);padding-top:8px}dd{margin:0;min-width:0}
details{margin-top:12px}summary{cursor:pointer;color:#416775;font-size:13px}nav{display:flex;gap:10px;flex-wrap:wrap}nav a{font-size:12px}footer{margin-top:25px}.edge[hidden]{display:none}
@media(max-width:800px){main{padding:18px 12px}.endpoints{grid-template-columns:1fr}.edge{padding:15px}dl>div{grid-template-columns:1fr;gap:0}.filters{position:static}input[type=search]{min-width:180px;width:100%}}
'''

SCRIPT = '''
const cards = Array.from(document.querySelectorAll('article.edge'));
const route = document.querySelector('#route');
const focus = document.querySelector('#focus');
const query = document.querySelector('#query');
function filter() {
  const term = query.value.toLocaleLowerCase().trim();
  let shown = 0;
  for (const card of cards) {
    const visible = (!route.value || card.dataset.route === route.value)
      && (!focus.checked || card.dataset.focus === 'true')
      && (!term || card.textContent.toLocaleLowerCase().includes(term));
    card.hidden = !visible;
    shown += Number(visible);
  }
  document.querySelector('#shown').textContent = String(shown) + ' / ' + String(cards.length);
}
for (const control of [route, focus, query]) control.addEventListener('input', filter);
function revealHash() {
  const id = decodeURIComponent(location.hash.slice(1));
  const card = document.getElementById(id);
  if (card && card.classList.contains('edge')) {
    route.value = ''; query.value = ''; focus.checked = false; filter();
    card.scrollIntoView();
  }
}
window.addEventListener('hashchange', revealHash);
filter(); revealHash();
'''


def page_html(edges, nodes, audits, summary):
    counts = ''.join(f'<div class="count"><b>{summary["routes"].get(route, 0)}</b>{escaped(route)}</div>'
                     for route in ROUTES)
    options = ''.join(f'<option value="{escaped(route)}">{escaped(route)} · {escaped(label)}</option>'
                      for route, label in ROUTES.items())
    nav = ''.join(f'<a href="#{escaped(edge_id)}">{escaped(edge_id)}</a>'
                  for edge_id in FOCUS_NOTES if edge_id in audits)
    ordered = sorted(edges, key=lambda edge: (edge['task_id'] not in FOCUS_NOTES,
                                              list(FOCUS_NOTES).index(edge['task_id'])
                                              if edge['task_id'] in FOCUS_NOTES else 0))
    cards = ''.join(edge_html(edge, nodes, audits[edge['task_id']]) for edge in ordered)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EvidenceNet · Edge 来源与 claim 复核</title><style>{STYLE}</style></head><body><main>
<h1>Edge 来源与 claim 复核</h1><p class="muted">只看已有 edge 本身；不混入搜索结果、query 分数或检索金标。</p>
<section class="intro"><h2>把三个问题分开</h2>
<p>① 来源应走哪个通道？② 两个节点是否值得建立宽泛 RELATED？③ 模型写出的具体 claim 是否分别被两端原文支持？</p>
<p class="notice">来源角色筛查通过 ≠ 关系已正确；同主题 RELATED ≠ 同一个对象／研究 ≠ 事实相互支持。
这里的 reference_review 与 administrative_review 是待审路由，不是自动判错或删除。
保留 RELATED 宽关系，不把它升级为可信证据传播。</p>
<p>六个固定 focus 是人工复核线索，不是自动金标。模型原话、原始 anchors、生成描述分区展示；原始换行与限定条件完整保留，不补写原文。</p>
<div class="counts"><div class="count"><b>{summary['edges']}</b>现有边</div>{counts}</div>
<nav aria-label="固定复核线索">{nav}</nav></section>
<section class="filters" aria-label="筛选"><label>路由 <select id="route"><option value="">全部</option>{options}</select></label>
<label><input id="focus" type="checkbox" checked> 只看固定 focus</label>
<input id="query" type="search" aria-label="搜索边、节点、原文或模型解释" placeholder="搜索 edge ID / node / 原文 / claim">
<span id="shown" aria-live="polite"></span></section>
{cards}<footer class="muted"><p>本页为只读快照，未修改源图；不进行在线 embedding 或模型推理。</p>
<details><summary>输入路径、SHA-256 与生成器哈希</summary><pre>{escaped(summary['inputs'])}</pre>
<pre>{escaped(summary['generator'])}</pre></details><p><a href="summary.json">summary.json</a></p></footer>
</main><script>{SCRIPT}</script></body></html>'''


def build(edges_path: Path, nodes_path: Path, audit_path: Path, output: Path):
    if output.exists():
        raise ValueError('Fresh output directory required; refusing to overwrite a review snapshot')
    edges, edge_source = snapshot(edges_path, jsonl=True)
    node_records, node_source = snapshot(nodes_path, jsonl=True)
    audit_document, audit_source = snapshot(audit_path)
    edge_map = indexed(edges, 'task_id', 'edge')
    nodes = indexed(node_records, 'id', 'node')
    audits = indexed(audit_document['edge_audits'], 'edge_id', 'audit edge')
    if set(edge_map) != set(audits):
        raise ValueError('Audit/graph edge ID sets differ; refuse a partial or mismatched audit')
    for edge_id, edge in edge_map.items():
        audit = audits[edge_id]
        if audit.get('route') not in ROUTES:
            raise ValueError(f'Unsupported audit route for {edge_id}: {audit.get("route")!r}')
        for endpoint in ('source', 'target'):
            if edge.get(endpoint) not in nodes:
                raise ValueError(f'Missing {endpoint} node for {edge_id}')
            audited_id = audit.get('endpoints', {}).get(endpoint, {}).get('node_id')
            if audited_id is not None and audited_id != edge[endpoint]:
                raise ValueError(f'Audit/graph endpoint mismatch for {edge_id}')
    code = Path(__file__).read_bytes()
    summary = {
        'kind': 'edge_source_and_claim_review_not_retrieval_evaluation',
        'edges': len(edges),
        'routes': dict(Counter(audit['route'] for audit in audits.values())),
        'focus_ids': [identity for identity in FOCUS_NOTES if identity in edge_map],
        'missing_focus_ids': [identity for identity in FOCUS_NOTES if identity not in edge_map],
        'focus_status': 'human_review_leads_not_gold_labels_or_confirmed_edge_errors',
        'semantic_route_means': 'passes_source_role_check_only_not_claim_truth_or_relation_correctness',
        'source_graph_modified': False,
        'new_model_inference': False,
        'inputs': {'edges': edge_source, 'nodes': node_source, 'audit': audit_source},
        'generator': {'path': str(Path(__file__).resolve()), 'sha256': hashlib.sha256(code).hexdigest()},
    }
    rendered = page_html(edges, nodes, audits, summary)
    summary['html_sha256'] = hashlib.sha256(rendered.encode('utf-8')).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'index.html').write_text(rendered, encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edges', type=Path, default=RESULTS / 'graph/related.jsonl')
    parser.add_argument('--nodes', type=Path, default=RESULTS / 'nodes.jsonl')
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = build(args.edges, args.nodes, args.audit, args.output)
    print(json.dumps({'edges': summary['edges'], 'routes': summary['routes'],
                      'focus': len(summary['focus_ids']), 'html': str(args.output / 'index.html')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
