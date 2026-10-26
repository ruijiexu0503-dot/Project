"""Report gate-only results without pretending missing reranking is complete."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

import run_query_edge_repair as experiment


def report(source, output):
    if output.exists():
        raise ValueError('Fresh report directory required')
    experiment.check(source)
    entries=experiment.rows(source/'gate_inputs.jsonl')
    expected={e['id']:e for e in entries}
    predictions=experiment.rows(source/'gate_predictions.jsonl')
    seen=set(); decisions=[]
    for prediction in predictions:
        rid=prediction['id']
        if rid in seen or rid not in expected:
            raise ValueError('Duplicate or unknown prediction ID')
        seen.add(rid); entry=expected[rid]
        if prediction['prompt_sha256']!=entry['prompt_sha256']:
            raise ValueError('Prediction/input hash mismatch')
        if prediction['valid']:
            experiment.gate.validate(prediction['result'],entry['input'])
        role=prediction['result']['role'] if prediction['valid'] else 'INVALID'
        decisions.append({**entry,'prediction':prediction,'role':role,
            'navigation_allowed':entry['source_role_route']=='semantic' and role in experiment.gate.NAVIGATION_ROLES})
    execution=experiment.read(source/'gate_execution.json')
    if execution['input_manifest']!=experiment.sha(source/'manifest.json'):
        raise ValueError('Execution/input manifest mismatch')
    summary={'gate_complete':len(seen)==len(expected),'processed':len(seen),'total':len(expected),
             'role_counts':dict(Counter(d['role'] for d in decisions)),
             'source_routes':dict(Counter(d['source_role_route'] for d in decisions)),
             'navigation_allowed':sum(d['navigation_allowed'] for d in decisions),
             'retrieval_metrics_computed':False,
             'note':'Model judgments of query-specific navigation, not edge truth or measured retrieval gains. '
                    'Quote validation checks literal grounding only. No document/edge re-embedding.',
             'source':str(source.resolve()),
             'inputs_sha256':{n:experiment.sha(source/n) for n in
                ('manifest.json','gate_inputs.jsonl','gate_predictions.jsonl','gate_execution.json')}}
    esc=lambda v:html.escape(str(v),quote=True)
    cards=[]
    for d in decisions:
        v=d['input']; result=d['prediction']['result']
        cards.append(f'<article><h2>{esc(d["question_id"])} · {esc(d["role"])}</h2>'
                     f'<p>{esc(v["query"])}</p><p>Edge: {esc(d["edge_id"])} · '
                     f'来源通道: {esc(d["source_role_route"])} · 允许导航: {d["navigation_allowed"]}</p>'
                     f'<details><summary>实际命中窗口（仅定位，不作原始事实证据）</summary><pre>{esc(v["seed_hit"]["text"])}</pre></details>'
                     '<div class="pair">'+''.join(f'<section><h3>{side}</h3><pre>{esc(v[side]["anchor"])}</pre></section>'
                                                   for side in ('source','target'))+'</div>'
                     f'<h3>模型判断，不是人工金标</h3><pre>{esc(json.dumps(result,ensure_ascii=False,indent=2))}</pre></article>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Query–edge 路径核验</title>
<style>body{max-width:1200px;margin:30px auto;padding:0 20px;font:16px/1.6 system-ui;background:#f4f6f8;color:#183142}
article{background:white;border:1px solid #ccd6df;padding:20px;margin:20px 0;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style>
<h1>Query–edge 路径核验</h1><p>BACKGROUND 不等于原 edge 错误；它表示此模型认为该边对当前问题仅提供背景。
本页没有计算 Recall/AP，也不把模型判断当作准确率。</p>'''
    page+='<pre>'+esc(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(cards)+'</html>'
    experiment.write(output/'summary.json',summary)
    experiment.jsonl(output/'decisions.jsonl',decisions)
    (output/'index.html').write_text(page)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report(args.source,args.output)
