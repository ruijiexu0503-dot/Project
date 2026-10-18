"""Compute page AP from frozen scores, without changing the no-edge baseline."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from evaluate_vldocir import TYPES, page, rows

ROOT=Path(__file__).resolve().parents[2]
BASELINE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
OUTPUT=ROOT/'EvidenceNet/output/vldocir_baseline_ap_20261016'
ARMS=('page_mean','page_windows','parser_atoms','parser_atoms_visual','hybrid_text','hybrid_visual')


def average_precision(ranked, gold, k=None, normalize_at_k=False):
    if not gold:raise ValueError('AP requires nonempty gold')
    unique=list(dict.fromkeys(ranked))
    if k is not None:
        if k<1:raise ValueError('k must be positive')
        unique=unique[:k]
    hits=0;total=0.
    for rank,pid in enumerate(unique,1):
        if pid in gold:
            hits+=1;total+=hits/rank
    denominator=min(len(gold),k) if normalize_at_k and k is not None else len(gold)
    return total/denominator


def evaluate(baseline, output):
    queries=list(rows(baseline/'pilot/queries.jsonl'))
    corpus={page(r) for r in rows(baseline/'pilot/corpus_pages.jsonl')}
    qids={q['question_id'] for q in queries}
    assert len(qids)==len(queries)
    gold=defaultdict(set)
    for r in rows(baseline/'pilot/gold_evidence.jsonl'):
        if r['question_id'] in qids:gold[r['question_id']].add(page(r))
    if any(not gold[qid] or not gold[qid]<=corpus for qid in qids):raise ValueError('missing gold')
    metrics=['AP@3','AP@5','AP@10','AP_full','AP@3_minRK','AP@5_minRK','AP@10_minRK']
    mean=lambda xs:{m:sum(x[m] for x in xs)/len(xs) for m in metrics}
    results={};source_files=[baseline/'pilot'/n for n in ['queries.jsonl','corpus_pages.jsonl','gold_evidence.jsonl']]
    for arm in ARMS:
        f=baseline/'retrieval'/f'{arm}_scores.jsonl';source_files.append(f)
        scores=defaultdict(dict)
        for r in rows(f):
            qid=r['question_id'];pid=page(r);value=float(r['score'])
            if qid not in qids or pid not in corpus or not math.isfinite(value):raise ValueError('invalid score')
            if pid in scores[qid]:raise ValueError('duplicate page score')
            scores[qid][pid]=value
        per_query={};groups=defaultdict(list)
        for q in queries:
            qid=q['question_id']
            if set(scores[qid])!=corpus:raise ValueError('incomplete full-corpus ranking')
            ranked=sorted(corpus,key=lambda p:(-scores[qid][p],p))
            result={f'AP@{k}':average_precision(ranked,gold[qid],k) for k in [3,5,10]}
            result.update({f'AP@{k}_minRK':average_precision(ranked,gold[qid],k,True) for k in [3,5,10]})
            result['AP_full']=average_precision(ranked,gold[qid])
            per_query[qid]=result;groups[q['question_type']].append(result)
        if set(groups)!=set(TYPES):raise ValueError('incomplete question types')
        by_type={t:mean(v) for t,v in groups.items()}
        results[arm]=dict(macro_six_types=mean(list(by_type.values())),query_mean=mean(list(per_query.values())),
                          by_type=by_type,per_query=per_query)
    paired={}
    for control in ['parser_atoms_visual','page_windows','hybrid_text']:
        paired[control]={}
        for m in ['AP@5','AP_full']:
            delta=[results['hybrid_visual']['per_query'][q][m]-results[control]['per_query'][q][m] for q in sorted(qids)]
            paired[control][m]=dict(mean_delta=sum(delta)/len(delta),wins=sum(d>1e-12 for d in delta),
                losses=sum(d< -1e-12 for d in delta),ties=sum(abs(d)<=1e-12 for d in delta))
    report=dict(baseline_id=baseline.name,queries=len(queries),pages=len(corpus),
        gold_page_counts=dict(sorted((str(n),sum(len(gold[q])==n for q in qids)) for n in {len(gold[q]) for q in qids})),
        definition='AP@k=sum(P@r * rel_r, r=1..k)/R, R=total distinct gold pages. Full AP uses all 518 pages. Also report alternate denominator min(R,k) separately.',
        tie_policy='score descending, official (document_id, page_number-as-string) ascending; identical to frozen evaluator',
        scope='Same frozen 24-query selected-corpus pilot; not author full-corpus baseline, not edge evaluation.',
        results=results,paired_hybrid_visual_vs=paired)
    output.mkdir(parents=True,exist_ok=True)
    (output/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# Frozen VL-DocIR baseline: AP comparison','','24 queries, 518 pages; same saved rankings, no new model inference.',
        '',report['definition'],'','Six question-type macro means; main AP@k divides by all relevant pages R.','',
        '| Arm | mAP@3 | mAP@5 | mAP@10 | mAP full |','| --- | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        m=results[arm]['macro_six_types']
        lines.append('| '+arm+' | '+' | '.join(f'{100*m[k]:.2f}%' for k in ['AP@3','AP@5','AP@10','AP_full'])+' |')
    lines+=['','No frozen file was modified. AP compares question-to-page retrieval, not node-pair candidate coverage.',
            'References are official dataset evidence pages for this selected pilot; small score differences do not establish statistical significance.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    source_files.append(Path(__file__))
    (output/'manifest.json').write_text(json.dumps({str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in source_files},indent=2)+'\n')
    print('\n'.join(lines),flush=True)
    print('Paired:',json.dumps(paired),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,default=BASELINE);p.add_argument('--output',type=Path,default=OUTPUT)
    args=p.parse_args();evaluate(args.baseline,args.output)
