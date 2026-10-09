#!/usr/bin/env python3
"""Frozen candidates, independent multi-signal checks, and synthetic controls."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'EvidenceNet'))
from evidence_graph.run_existence_prompt_v2 import SIGNALS, _prompt, _parse, _anchor_in_target


def read(p): return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]
def write(p,rs): p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rs))
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')


def prepare(out):
    previous=ROOT/'EdgeGeneration/output/qwen35_multisignal_review_v1'
    tasks=read(previous/'tasks.jsonl')
    meta=[{'task_id':t['task_id'],'kind':'real_frozen'} for t in tasks]
    # Hand-authored diagnostic controls are never represented as corpus gold.
    controls=[
        ('positive_measurement','Experiment ORION measured detector efficiency at 90 percent in run R1.','In run R1, ORION detected 90 of 100 injected test pulses.',True,'EVIDENCE_OR_QUANTIFICATION'),
        ('positive_explanation','In sensor VEGA, heating reduces resistance because it increases mobile charge carriers.','VEGA resistance decreases when its temperature rises.',True,'EXPLANATION_OR_MECHANISM'),
        ('positive_scope','The VEGA calibration is valid only between 10 and 20 degrees Celsius.','VEGA uses this calibration to convert resistance into temperature.',True,'CONDITION_OR_SCOPE'),
        ('positive_contrast','For the same sample S at 20 degrees Celsius, test A reports a conductivity of 5 units.','For the same sample S at 20 degrees Celsius, test B reports a conductivity of 12 units, inconsistent with test A.',True,'EXPLICIT_CONTRAST'),
        ('negative_entity','ORION measured detector efficiency at 90 percent in run R1.','The ORION cafeteria serves lunch from noon until two.',False,None),
        ('negative_object','The central black hole in galaxy A was observed using X-rays.','A binary merger in distant galaxy B was observed using gravitational waves.',False,None),
        ('negative_vocabulary','Construction crews reduced vibration near a new office building.','A gravitational-wave detector was checked for vibration contamination during a merger signal.',False,None),
        ('negative_topic','A textbook chapter lists several dark matter candidates.','A laboratory purchased new desks for its dark matter research group.',False,None),
    ]
    for name,a,b,label,signal in controls:
        tid='control_'+name
        tasks.append({'task_id':tid,'pair_id':tid,'evidence_a':{'node_id':tid+'_a','text':a},'evidence_b':{'node_id':tid+'_b','text':b}})
        meta.append({'task_id':tid,'kind':'synthetic_control','expected_edge':label,'expected_signal':signal})
    # Include all previously accepted/possible/invalid pairs plus one negative,
    # fixed before the new verifier runs, to probe orientation sensitivity.
    predictions={r['task_id']:r for r in read(previous/'predictions.jsonl')}
    chosen=[t for t in tasks[:24] if predictions[t['task_id']].get('status')!='UNRELATED']
    chosen += [next(t for t in tasks[:24] if predictions[t['task_id']].get('status')=='UNRELATED')]
    for t in chosen:
        tid=t['task_id']+'_swapped'
        tasks.append({**t,'task_id':tid,'evidence_a':t['evidence_b'],'evidence_b':t['evidence_a']})
        meta.append({'task_id':tid,'kind':'swapped_real','original_task_id':t['task_id']})
    write(out/'tasks.jsonl',tasks);write(out/'evaluation_only.jsonl',meta)
    dump(out/'manifest.json',{'production_modified':False,'tasks':len(tasks),'kinds':dict(Counter(r['kind'] for r in meta)),
        'model':'Qwen3.5-35B-A3B','method':'existing proposal prompt followed by independent per-signal source checks',
        'all_five_signals_checked':True,'no_neighbor_context_added':True,
        'control_labels_hidden':True,'old_predictions_sha256':hashlib.sha256((previous/'predictions.jsonl').read_bytes()).hexdigest(),
        'limitations':['Eight synthetic controls are sanity checks, not real cross-document accuracy.',
            'Same model proposes and verifies; stages are not independent annotators.',
            'Orientation subset is selected from previous outcomes, not a random stability estimate.']})


def verify_prompt(task,proposal):
    hint={k:proposal.get(k) for k in ['status','signals','best_relation_hypothesis']}
    return '''Check each of the five semantic signals independently against the two ORIGINAL TARGET texts.
The previous screening is an untrusted hypothesis, not a fact. Check ALL signals, including ones it missed.
Do not require every relation to concern the identical event. Relation-specific criteria:
SAME_CLAIM_OR_RESULT: same specific proposition/result/event; a particular instance and a broad generalization are not automatically the same claim.
EVIDENCE_OR_QUANTIFICATION: an observation, quantitative detail or concrete example genuinely bears on the other claim within compatible scope. Merely factual prose is not evidence for every broader topic. An example need not prove the whole generalization; explicitly limit its contribution.
EXPLANATION_OR_MECHANISM: a rationale, mechanism, definition, background or implementation materially explains the other target. A clear implicit link is allowed; common terminology alone is not.
CONDITION_OR_SCOPE: a stated condition or qualification actually applies to the claim in the other target.
EXPLICIT_CONTRAST: a specific comparison/conflict, with compatible objects, measurements and conditions. Distinct events alone are not a contrast.
Inspect identity, time, conditions and epistemic status where relevant. Do not assume a plan is an observation, infer author citation/intent, or count repeated reporting as independent corroboration.
Descriptions can resolve wording, but both anchors must be exact contiguous substrings of target text. Never concatenate spans with ellipses. Do not invent missing context. Multiple signals may be ACCEPT simultaneously; UNCERTAIN remains unresolved.
For directed accepted/uncertain signals, direction means contributor/explanation/qualifier -> statement it develops; use SYMMETRIC for shared-result/contrast, or UNRESOLVED if direction cannot be established.
Return JSON: {"task_id":"exact task ID", "checks":[{"signal":"one of the five signal names", "decision":"ACCEPT|REJECT|UNCERTAIN", "direction":"A_TO_B|B_TO_A|SYMMETRIC|UNRESOLVED|NONE", "anchor_a":"exact substring or null", "anchor_b":"exact substring or null", "reason":"specific grounded explanation and any scope limit"}]}.
Include each signal exactly once. ACCEPT/UNCERTAIN require nonempty anchors and non-NONE direction. REJECT uses NONE and null anchors.
INPUT:\n'''+json.dumps({'targets':task,'untrusted_proposal':hint},ensure_ascii=False)


def validate(value,task):
    if not isinstance(value,dict) or value.get('task_id')!=task['task_id']: return False
    checks=value.get('checks')
    if not isinstance(checks,list) or len(checks)!=len(SIGNALS) or any(not isinstance(c,dict) for c in checks): return False
    if {c.get('signal') for c in checks}!=SIGNALS:return False
    for c in checks:
        if not isinstance(c.get('reason'),str) or not c['reason'].strip():return False
        if c.get('decision')=='REJECT':
            if c.get('direction')!='NONE' or c.get('anchor_a') is not None or c.get('anchor_b') is not None:return False
        elif c.get('decision') in {'ACCEPT','UNCERTAIN'}:
            if c.get('direction') not in {'A_TO_B','B_TO_A','SYMMETRIC','UNRESOLVED'}:return False
            if not all(_anchor_in_target(c.get('anchor_'+side),task['evidence_'+side]) for side in ['a','b']):return False
        else:return False
    return True


def run(out):
    from evidence_graph.llm_client import create_llm
    llm=create_llm({'provider':'transformers','model':str(ROOT/'external/models/Qwen3.5-35B-A3B'),
        'dtype':'bfloat16','device_map':'auto','require_cuda':True,'enable_thinking':False})
    baseline={r['task_id']:r for r in read(ROOT/'EdgeGeneration/output/qwen35_multisignal_review_v1/predictions.jsonl')}
    results=read(out/'results.jsonl') if (out/'results.jsonl').exists() else []
    done={r['task_id'] for r in results}
    tasks=read(out/'tasks.jsonl')
    for task in tasks:
        if task['task_id'] in done:continue
        proposal=baseline.get(task['task_id'])
        if proposal is None:
            try:
                g=llm.generate_json('Screen a scientific Evidence pair for a meaningful semantic relationship with high recall. Check independent signals, use context only to resolve targets, and return exact JSON.',_prompt(task),900)
                parsed,valid=_parse(g.parsed,task);proposal={**parsed,'valid':valid,'raw':g.raw}
            except Exception as exc:proposal={'valid':False,'error':str(exc)}
        value={};valid=False;raw='';error=''
        for attempt in range(2):
            try:
                prompt=verify_prompt(task,proposal)
                if attempt:prompt+='\nPrevious output did not meet the schema or exact target-anchor requirements. Recheck each field.'
                g=llm.generate_json('Verify each semantic signal independently using source text. JSON only.',prompt,2200)
                raw=g.raw;value=g.parsed;valid=validate(value,task)
                if valid:break
            except Exception as exc:error=str(exc)
        checks=value.get('checks',[]) if valid else []
        accepted=[c['signal'] for c in checks if c['decision']=='ACCEPT']
        uncertain=[c['signal'] for c in checks if c['decision']=='UNCERTAIN']
        results.append({'task_id':task['task_id'],'proposal':proposal,'verified':value,'valid':valid,
            'accepted_signals':accepted,'uncertain_signals':uncertain,
            'status':'INVALID' if not valid else 'RELATED' if accepted else 'POSSIBLE_RELATION' if uncertain else 'UNRELATED',
            'raw':raw,'error':error})
        write(out/'results.jsonl',results)
        dump(out/'status.json',{'processed':len(results),'total':len(tasks),'complete':len(results)==len(tasks)})
        print(json.dumps({'processed':len(results),'task':task['task_id'],'status':results[-1]['status']}),flush=True)


def report(out):
    results={r['task_id']:r for r in read(out/'results.jsonl')};tasks={r['task_id']:r for r in read(out/'tasks.jsonl')};meta=read(out/'evaluation_only.jsonl')
    summary={'production_modified':False,'complete':all(m['task_id'] in results for m in meta),'groups':{}}
    for kind in ['real_frozen','synthetic_control','swapped_real']:
        selected=[results[m['task_id']] for m in meta if m['kind']==kind and m['task_id'] in results]
        summary['groups'][kind]={'processed':len(selected),'status_counts':dict(Counter(r['status'] for r in selected)),
            'multi_label_accepted':sum(len(r['accepted_signals'])>1 for r in selected)}
    controls=[];swaps=[]
    for m in meta:
        r=results.get(m['task_id'])
        if not r:continue
        if m['kind']=='synthetic_control':
            controls.append({**m,'proposal_status':r['proposal'].get('status'),'proposal_valid':r['proposal'].get('valid'),
                'verified_status':r['status'],'expected_signal_accepted':m['expected_signal'] in r['accepted_signals'] if m['expected_signal'] else None})
        if m['kind']=='swapped_real' and m['original_task_id'] in results:
            original=results[m['original_task_id']]
            swaps.append({'task_id':m['task_id'],'both_valid':r['valid'] and original['valid'],
                'same_status':r['status']==original['status'],'same_accepted_signals':set(r['accepted_signals'])==set(original['accepted_signals'])})
    summary['controls']=controls;summary['orientation_checks']=swaps
    dump(out/'summary.json',summary)
    cards=[]
    for tid,r in results.items():
        cards.append('<details><summary>'+html.escape(tid+' | '+r['status'])+'</summary><pre>'+html.escape(json.dumps({'targets':tasks[tid],'result':r},ensure_ascii=False,indent=2))+'</pre></details>')
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Per-label verification ablation</title><style>body{font:15px system-ui;max-width:1100px;margin:auto}pre{white-space:pre-wrap}details{padding:12px}</style><h1>逐标签核验对照</h1><p>真实候选无人工金标准；合成对照只用于功能检查。</p><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(cards))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','run','report']);ap.add_argument('--output',type=Path,default=ROOT/'EdgeGeneration/output/relation_policy_ablation_v1');args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    {'prepare':prepare,'run':run,'report':report}[args.stage](args.output)
