#!/usr/bin/env python3
"""Freeze the previous 24 pairs and report existing multisignal-v2 judgments."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(p):
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]


def write(p, rows):
    p.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','report']);args=ap.parse_args()
    old=ROOT/'EdgeGeneration/output/qwen35_description_trial_v1'
    out=ROOT/'EdgeGeneration/output/qwen35_multisignal_review_v1';out.mkdir(parents=True,exist_ok=True)
    units={r['node_id']:r for r in read(old/'units.jsonl')}
    sample=read(old/'review_sample.jsonl')
    if args.stage=='prepare':
        tasks=[]
        for i,r in enumerate(sample):
            def endpoint(key):
                n=units[r[key]]
                return {'node_id':n['node_id'],'document':n['doc_id'],'section':n.get('section_path'),
                        'text':n['plain_text'],'description':n['base_summary'],'key_points':n.get('key_points')}
            tasks.append({'task_id':f'multisignal_{i:03d}','pair_id':r['a']+'::'+r['b'],
                          'evidence_a':endpoint('a'),'evidence_b':endpoint('b')})
        write(out/'tasks.jsonl',tasks)
        manifest={'pairs':len(tasks),'production_modified':False,'same_pairs_and_input_content':True,
                  'no_extra_neighbor_context':True,'prompt':'existence-multisignal-context-v2',
                  'prompt_source':'EvidenceNet/evidence_graph/run_existence_prompt_v2.py',
                  'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      [old/'units.jsonl',old/'review_sample.jsonl',old/'reviews.jsonl',ROOT/'EvidenceNet/evidence_graph/run_existence_prompt_v2.py']}}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps(manifest,indent=2));return
    tasks=read(out/'tasks.jsonl');pred={r['task_id']:r for r in read(out/'predictions.jsonl')}
    baseline={(r['a'],r['b']):r for r in read(old/'reviews.jsonl')}
    comparisons=[]
    for t in tasks:
        a,b=t['evidence_a']['node_id'],t['evidence_b']['node_id'];oldrow=baseline[(a,b)];new=pred.get(t['task_id'],{})
        comparisons.append({'a':a,'b':b,'stratum':oldrow['stratum'],'old':oldrow['judgment'],
                            'new':new,'a_text':units[a]['plain_text'],'b_text':units[b]['plain_text']})
    summary={'total':len(tasks),'processed':len(pred),'complete':all(t['task_id'] in pred for t in tasks),
        'valid':sum(bool(r.get('valid')) for r in pred.values()),
        'status_counts':dict(Counter(r.get('status') if r.get('valid') else 'INVALID' for r in pred.values())),
        'multi_signal_related':sum(r.get('valid') and r.get('status')=='RELATED' and len(r.get('signals',[]))>1 for r in pred.values()),
        'by_stratum':{s:dict(Counter(r['new'].get('status') if r['new'].get('valid') else 'INVALID_OR_MISSING' for r in comparisons if r['stratum']==s)) for s in ['shared','original_only','description_only']},
        'production_modified':False,'interpretation':'Prompt-policy comparison, not a pure multi-label ablation or independent accuracy estimate. POSSIBLE_RELATION remains unresolved. Signals have no semantic direction.'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');write(out/'comparison.jsonl',comparisons)
    cards=[]
    for r in comparisons:
        cards.append('<details><summary>'+html.escape(r['stratum']+' | '+r['new'].get('status','MISSING')+' | '+r['a']+' ↔ '+r['b'])+'</summary><pre>'+html.escape(json.dumps({'old':r['old'],'new':r['new']},ensure_ascii=False,indent=2))+'</pre><p>'+html.escape(r['a_text'])+'</p><p>'+html.escape(r['b_text'])+'</p></details>')
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Multisignal review comparison</title><style>body{font:15px system-ui;max-width:1100px;margin:auto}pre{white-space:pre-wrap}details{padding:12px}</style><h1>相同24对：既有多信号prompt对比</h1><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(cards))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
