"""Isolated five-arm formula diagnostic using the unchanged routed verifier.

Reruns all unique requests; historical model responses are not imported. Exact
requests within this trial share one cached response with explicit provenance.
"""
import argparse
from pathlib import Path
import json

import run_routed_edge_context as routed
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
from build_formula_context_review import ARMS


def prepare(source, out):
    if out.exists():
        raise ValueError('fresh output directory required')
    for filename, expected in read(source/'manifest.json')['sources'].items():
        if sha(ROOT/filename) != expected:
            raise ValueError('changed reviewed input '+filename)
    cases=rows(source/'cases.jsonl')
    inputs={a:rows(source/'prepared_ablation'/a/'inputs.jsonl') for a in ARMS}
    for arm, entries in inputs.items():
        if len(entries)!=len(inputs['control']):raise ValueError('arm length mismatch')
        for original,entry in zip(inputs['control'],entries):
            for key in ('task','lookups','images','image_sha256'):
                if entry[key]!=original[key]: raise ValueError('changed endpoints/images '+arm)
            if routed.inference_key(entry)!=entry['inference_key']: raise ValueError('invalid inference key')
    for arm,entries in inputs.items():jsonl(out/arm/'inputs.jsonl',entries)
    refs=[dict(c['reference'],cohort=c['cohort']) for c in cases if c['reference']]
    jsonl(out/'reference.jsonl',refs)
    jsonl(out/'case_map.jsonl',[{k:c[k] for k in ('task_id','case_id','cohort')} for c in cases])
    model_configs={read(ROOT/'EvidenceNet/output'/name/'protocol.json')['model_config_sha256'] for name in
                   ('routed_edge_context_v1_20261020','routed_edge_context_fresh_v1_20261021')}
    if len(model_configs)!=1:raise ValueError('historical model configs differ')
    write(out/'protocol.json',{'experiment':'formula_context_repair_v1_20261026','arms':list(ARMS),
        'pairs':len(cases),'unique_requests':len({e['inference_key'] for es in inputs.values() for e in es}),
        'model_config_sha256':model_configs.pop(),'source_root':str(ROOT),'system':routed.SYSTEM,
        'inference':{'max_new_tokens':700,'attempts':2,'thinking':False,'sampling':False},
        'scope':'Retrospective 6 old + 8 fresh formula cases; all are now development diagnostics.',
        'controls':['No context vs selected definitions crossed with original vs mathematical comparison policy',
                    'Additional historical context selection comparator',
                    'Same original endpoint evidence, crops, model, validator, response budget and metadata repair',
                    'Compile definitions per node without pair partner or reference label',
                    'No historical response reuse; identical requests inside this run may reuse one prediction',
                    'No production graph changes or full-corpus accuracy claim'],
        'preparation_manifest_sha256':sha(source/'manifest.json')})
    routed.freeze(out)
    manifest=read(out/'manifest.json')
    for p in (Path(__file__),Path(__file__).with_name('build_formula_context_review.py'),Path(__file__).with_name('formula_context_packets.py')):
        manifest['code'][str(p.relative_to(ROOT))]=sha(p)
    write(out/'manifest.json',manifest)
    return read(out/'protocol.json')


def report(out):
    routed.verify(out)
    if not read(out/'summary.json')['complete']:raise ValueError('incomplete trial: retain checkpoint, no final metrics')
    refs={r['task_id']:r for r in rows(out/'reference.jsonl')}
    case_map=rows(out/'case_map.jsonl');metrics={};cases=[]
    for arm in ARMS:
        predictions={p['task_id']:p for p in rows(out/arm/'predictions.jsonl')}
        if set(predictions)!={c['task_id'] for c in case_map}:raise ValueError('missing or unexpected pair')
        metrics[arm]={}
        for cohort in sorted({c['cohort'] for c in case_map}):
            stats=dict(pairs=0,invalid=0,strict_scored=0,strict_correct=0,positive=0,useful_tp=0,
                       negative=0,accepted_fp=0,discovery_fp=0)
            for c in case_map:
                if c['cohort']!=cohort:continue
                p=predictions[c['task_id']];ref=refs.get(c['task_id']);result=p.get('result') or {}
                valid=bool(p['valid'] and result);decision=result.get('decision') if valid else 'INVALID'
                stats['pairs']+=1;stats['invalid']+=not valid
                if ref and ref.get('decision_evaluable'):
                    stats['strict_scored']+=1;stats['strict_correct']+=decision in ref['allowed_decisions']
                if ref and ref.get('cutoff_evaluable'):
                    positive=min(ref['allowed_levels'])>=2
                    stats['positive' if positive else 'negative']+=1
                    stats['useful_tp' if positive else 'accepted_fp']+=decision in ('EVIDENCE_LINK','NAVIGATION_LINK')
                    if not positive:stats['discovery_fp']+=valid and result['discovery_level']>=2
                cases.append(dict(c,arm=arm,prediction=p,reference=ref))
            metrics[arm][cohort]=stats
    write(out/'formula_results.json',{'complete':True,'metrics':metrics,'scope':read(out/'protocol.json')['scope'],
        'interpretation':'Decision metrics do not certify the correctness of mathematical explanations; inspect case_results.jsonl.'})
    jsonl(out/'case_results.jsonl',cases)
    lines=['# Formula context diagnostic','',read(out/'protocol.json')['scope'],'',
           '| Arm | Fresh strict | Fresh useful TP | Fresh accepted FP | Invalid |',
           '| --- | ---: | ---: | ---: | ---: |']
    for arm,cohorts in metrics.items():
        s=cohorts['fresh_reviewed_now_diagnostic']
        lines.append(f"| {arm} | {s['strict_correct']}/{s['strict_scored']} | {s['useful_tp']}/{s['positive']} | {s['accepted_fp']}/{s['negative']} | {s['invalid']} |")
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return {'complete':True,'metrics':metrics}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','verify','run','report'])
    p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',type=Path);p.add_argument('--image-root',type=Path,default=ROOT)
    p.add_argument('--minutes',type=int,default=52)
    a=p.parse_args();out=a.output.resolve();routed.ARMS=ARMS
    if a.stage=='prepare':result=prepare(a.source.resolve(),out)
    elif a.stage=='verify':routed.verify(out,a.model);result={'verified':True}
    elif a.stage=='run':
        routed.run(out,a.model,a.image_root,a.minutes);result=report(out)
    else:result=report(out)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
