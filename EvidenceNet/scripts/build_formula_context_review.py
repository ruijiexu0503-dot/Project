"""Reproduce historical formula outcomes and prepare a separate diagnostic ablation.

No inference or production graph mutation. New context is compiled once per node,
without queries, pair partners or labels. Historical annotations remain unchanged.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
ARMS = ('control', 'legacy_context', 'selected_context', 'math_policy', 'selected_context_math_policy')
MATH_POLICY = '''\nFORMULA COMPARISON CHECKS:
Compare the smallest explicit mathematical statement or subexpression at both endpoints.
Distinguish correspondence of a subexpression from equality of the full equations or outputs.
State the shared operation and the differences in matched_claim/reason/limitation.
Different variable letters, head indices, parent models or application domains alone do not
disprove a local mathematical correspondence. Renaming symbols for comparison does NOT
establish equal inputs, parameters, datasets or physical quantities.
Preserve operators, powers, absolute values, denominators, transpose, normalization, units,
aggregation axes and conditions. A common purpose or common variables alone is insufficient:
different error measures are not the same mathematical definition just because both evaluate predictions.
Context may resolve symbol roles or assumptions; the claimed operation must still occur in
the original endpoint evidence. Do not silently correct a printed formula to a textbook version.
An introductory 'defined as follows' or equation number refers to its own document; it does not
establish a direct pointer to a formula in another document.
Keep the original decision schema and evidence ownership requirements. No relation is mandatory.
'''


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))


def build(out):
    import formula_context_packets as packets
    import run_routed_edge_context as routed
    import run_named_identity_gate_verifier as gate
    if out.exists():
        raise ValueError('Use a fresh output directory; historical artifacts are immutable.')
    corpus = ROOT/'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
    nodes = {n['id']: n for n in rows(corpus/'corpus_nodes.jsonl')}
    policies = json.loads((corpus/'corpus_policies.json').read_text())
    reading_paths = routed.prior.READING
    reading = [e for path in reading_paths for e in rows(path)]
    cohorts = {
        'old_development': ('routed_edge_context_v1_20261020', 'horeka-edge-context-20261020',
                            ROOT/'EvidenceNet/output/routed_edge_context_v1_20261020/reference.jsonl'),
        'fresh_reviewed_now_diagnostic': ('routed_edge_context_fresh_v1_20261021', 'horeka-edge-fresh-20261021',
                            ROOT/'data/benchmarks/evidence_edges_fresh_v1_20261021_review/reference.jsonl'),
    }
    files = [Path(__file__), Path(packets.__file__), corpus/'corpus_nodes.jsonl', corpus/'corpus_policies.json', *reading_paths]
    cases, node_packets, planned, metrics = [], {}, {a: [] for a in ARMS}, {}
    for cohort, (input_name, result_name, reference) in cohorts.items():
        base = ROOT/'EvidenceNet/output'/input_name
        result = ROOT/'migration'/result_name/'results'
        paths = [base/a/'inputs.jsonl' for a in ('control', 'multimodal_context')]
        pred_paths = [result/a/'predictions.jsonl' for a in ('control', 'multimodal_context')]
        files += [reference, *paths, *pred_paths]
        refs = {r['task_id']: r for r in rows(reference)}
        original = {e['task']['task_id']: e for e in rows(paths[0])}
        legacy = {e['task']['task_id']: e for e in rows(paths[1])}
        predictions = {a: {p['task_id']: p for p in rows(p)} for a,p in zip(('control','legacy_context'), pred_paths)}
        cohort_cases = []
        for tid, control in original.items():
            if control['routing']['group'] != 'formula':
                continue
            context = {'A': [], 'B': []}
            for side in ('A', 'B'):
                if control['routing'][side] != 'formula':
                    continue
                nid = control['task'][side]['node_id']
                if nid not in node_packets:
                    node_packets[nid] = packets.build_packet(nid, nodes, policies, reading)
                # Original source spans remain separately owned supplemental evidence.
                context[side] = node_packets[nid]['contexts']
            for arm in ARMS:
                entry = copy.deepcopy(control)
                if arm == 'legacy_context':
                    entry = copy.deepcopy(legacy[tid])
                elif arm not in ('control',):
                    entry['contexts'] = context if arm.startswith('selected_context') else {'A': [], 'B': []}
                    entry['prompt'] = gate.prompt(entry['task']) + routed.POLICY + json.dumps(entry['contexts'], ensure_ascii=False)
                    if arm in ('math_policy', 'selected_context_math_policy'):
                        entry['prompt'] += MATH_POLICY
                    entry['inference_key'] = routed.inference_key(entry)
                # The treatment must not rewrite endpoint anchors, images or source text.
                assert entry['task'] == control['task'] and entry['lookups'] == control['lookups']
                assert entry['images'] == control['images'] and entry['image_sha256'] == control['image_sha256']
                planned[arm].append(entry)
            case = {'cohort': cohort, 'task_id': tid, 'case_id': refs.get(tid, {}).get('suite_case_id', tid),
                    'reference': refs.get(tid), 'task': control['task'], 'images': [],
                    'historical_contexts': legacy[tid]['contexts'], 'selected_contexts': context,
                    'new_inference_status': 'NOT_RUN',
                    'historical_predictions': {a: predictions[a].get(tid) for a in predictions}}
            for path, expected in zip(control['images'], control['image_sha256']):
                path = Path(path)
                assert sha(path) == expected, path
                target = out/'assets'/(expected[:20] + path.suffix)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists(): shutil.copyfile(path, target)
                case['images'].append(str(target.relative_to(out)))
            cases.append(case); cohort_cases.append(case)
        metrics[cohort] = {}
        for arm in ('control', 'legacy_context'):
            stats = {'pairs': len(cohort_cases), 'strict_scored': 0, 'strict_correct': 0,
                     'broad_positive': 0, 'useful_tp': 0, 'broad_negative': 0, 'useful_fp': 0, 'discovery_fp': 0,
                     'invalid_or_missing': 0}
            for c in cohort_cases:
                ref, p = c['reference'], c['historical_predictions'][arm]
                valid = bool(p and p.get('valid') and p.get('result'))
                stats['invalid_or_missing'] += not valid
                decision = p['result']['decision'] if valid else 'INVALID_OR_MISSING'
                if ref and ref.get('decision_evaluable'):
                    stats['strict_scored'] += 1
                    stats['strict_correct'] += decision in ref['allowed_decisions']
                if ref and ref.get('cutoff_evaluable'):
                    positive = min(ref['allowed_levels']) >= 2
                    stats['broad_positive' if positive else 'broad_negative'] += 1
                    stats['useful_tp' if positive else 'useful_fp'] += decision in ('EVIDENCE_LINK','NAVIGATION_LINK')
                    if not positive: stats['discovery_fp'] += valid and p['result']['discovery_level'] >= 2
            metrics[cohort][arm] = stats
    for arm, entries in planned.items(): jsonl(out/'prepared_ablation'/arm/'inputs.jsonl', entries)
    jsonl(out/'node_packets.jsonl', node_packets.values())
    jsonl(out/'cases.jsonl', cases)
    summary = {'historical_metrics': metrics, 'formula_pairs': len(cases), 'compiled_nodes': len(node_packets),
               'arms': ARMS, 'new_inference_status': 'NOT_RUN',
               'unique_requests': len({e['inference_key'] for entries in planned.values() for e in entries}),
               'scope': 'Retrospective diagnostic, assistant-reviewed provisional labels; not independent held-out evidence.'}
    dump(out/'summary.json', summary)
    dump(out/'manifest.json', {'sources': {str(p.relative_to(ROOT)): sha(p) for p in files},
                              'new_inference_status': 'NOT_RUN', 'production_changed': False})
    render(out, cases, node_packets, summary)
    return summary


def render(out, cases, packets, summary):
    esc = lambda value: html.escape(str(value))
    def text(value):
        return '<pre>' + esc(value) + '</pre>'
    def spans(items):
        return ''.join('<div class="span"><small>'+esc(i.get('route'))+' · '+esc(i['source_node_id'])+
                       ' / '+esc(i['member_id'])+'</small>'+text(i['quote'])+'</div>' for i in items) or '<p>无额外上下文</p>'
    cards = []
    order = {'F015':0, 'F033':1, 'F013':2, 'F016':3, 'P12':4}
    for c in sorted(cases, key=lambda c:(order.get(c['case_id'],10),c['cohort'],c['case_id'])):
        parts = ['<article><h2>'+esc(c['case_id'])+'</h2><p>'+esc(c['cohort'])+' · '+esc(c['task_id'])+'</p>']
        ref = c['reference'] or {}
        parts.append('<p>历史标签：'+esc(ref.get('allowed_decisions', ref.get('allowed_levels','未标注')))+'</p><div class="grid">')
        for arm in ('control','legacy_context'):
            p = c['historical_predictions'][arm] or {}
            r = p.get('result') or {}
            parts.append('<section><h3>'+('不加上下文' if arm=='control' else '旧上下文')+'</h3><strong>'+esc(r.get('decision','INVALID'))+
                '</strong> · discovery='+esc(r.get('discovery_level'))+text(r.get('reason',''))+text(r.get('limitation',''))+'</section>')
        parts.append('</div><details open><summary>原始端点和源图</summary><div class="grid">')
        for side in ('A','B'):
            endpoint=c['task'][side]
            parts.append('<section><h3>'+side+'</h3><small>'+esc(endpoint['node_id'])+'</small>')
            for e in endpoint['evidence']:
                if e.get('text'): parts.append(text(e['text']))
            parts.append('</section>')
        parts.append('</div><div class="images">'+''.join('<img loading="lazy" src="'+esc(p)+'">' for p in c['images'])+'</div></details>')
        parts.append('<details><summary>上下文选择对照（新方案尚未运行模型）</summary><div class="grid">')
        for side in ('A','B'):
            parts.append('<section><h3>'+side+'：旧选择</h3>'+spans(c['historical_contexts'][side])+
                         '<h3>'+side+'：新选择预览</h3>'+spans(c['selected_contexts'][side]))
            nid=c['task'][side]['node_id']
            if nid in packets:
                parts.append('<details><summary>路径、限制与舍弃原因</summary>'+text(json.dumps(packets[nid],ensure_ascii=False,indent=2))+'</details>')
            parts.append('</section>')
        parts.append('</div></details></article>');cards.append(''.join(parts))
    (out/'index.html').write_text('''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>公式上下文诊断 · 2026-10-26</title><style>
body{font:16px/1.6 system-ui;background:#f2f5fa;color:#17243c;margin:0 auto;max-width:1300px;padding:28px}
article,header{background:white;padding:24px;border-radius:14px;margin:20px 0}h1,h2,h3{line-height:1.25}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}section{min-width:0}.span{border-left:3px solid #7aa2d7;padding-left:12px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.55 ui-monospace,monospace;background:#f6f8fc;padding:12px}
small{overflow-wrap:anywhere;color:#52647a}summary{cursor:pointer;font-weight:600;margin:16px 0}.images img{max-width:100%;max-height:480px;margin:10px;border:1px solid #d7dfeb}
.notice{background:#fff2d6;padding:16px;border-radius:8px}@media(max-width:800px){.grid{grid-template-columns:1fr}body{padding:12px}}
</style><header><h1>公式上下文：哪里选错，哪里判断错</h1>
<p class="notice">这里重放历史真实预测。新上下文仅为可追溯输入预览，尚未运行新模型；不能把输入改善当作准确率提升。</p>
<p>新8对公式：严格标签正确率保持5/8；有效关联召回4/4→3/4来自F015；F034只有discovery分数升高，最终仍拒绝。旧P12应与修正共同prompt后的结果分开。</p>
<p>新方案跨过同页连续公式组，找变量/算子定义，过滤其他独立公式；数学判断另作独立消融。原始node、图和标签保持不变。</p>
<p><a href="summary.json">统计</a> · <a href="cases.jsonl">原始对照</a> · <a href="node_packets.jsonl">新上下文及来源</a></p>
</header>'''+''.join(cards)+'</html>')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().output.resolve()),ensure_ascii=False,indent=2))
