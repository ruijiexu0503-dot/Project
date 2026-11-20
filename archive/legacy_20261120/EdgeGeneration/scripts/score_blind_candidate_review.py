#!/usr/bin/env python3
"""Estimate confirmed-pair yield only after all blind labels are supplied."""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from prepare_blind_candidate_review import ARMS, RELATIONS, read


def score(plan, labels, manifest):
    by_id = {r['task_id']:r for r in labels}
    if len(by_id) != len(labels) or set(by_id) != {r['task_id'] for r in plan}:
        raise ValueError('label task IDs must match the entire review package exactly')
    for key in plan:
        p = key['inclusion_probability']
        if not isinstance(p, (int,float)) or not math.isfinite(p) or not 0 < p <= 1:
            raise ValueError('invalid inclusion probability')
    completed = []
    for row in labels:
        if row.get('package_id') != manifest['tasks_sha256']:
            raise ValueError('labels belong to another review package')
        decision = row.get('relation_exists')
        if decision is None:
            continue
        if decision not in {'YES','NO','UNCERTAIN'}:
            raise ValueError('invalid relation_exists decision')
        if not str(row.get('reviewer','')).strip() or row.get('review_method') not in {'independent_human','model_assisted_human','model_only'}:
            raise ValueError('completed labels must identify reviewer and review method')
        if not isinstance(row.get('basis'),str) or not row['basis'].strip():
            raise ValueError('completed labels require a basis')
        relations = row.get('relations')
        if not isinstance(relations,list) or any(not isinstance(r,dict) for r in relations):
            raise ValueError('relations must be a list of type/direction records')
        if any(r.get('type') not in RELATIONS for r in relations) or len({r['type'] for r in relations}) != len(relations):
            raise ValueError('unknown or duplicate relation type')
        for r in relations:
            allowed = {'SYMMETRIC'} if r['type']=='CONTRASTS_WITH' else {'A_TO_B','B_TO_A'}
            if decision=='UNCERTAIN': allowed.add('UNRESOLVED')
            if r.get('direction') not in allowed:
                raise ValueError('invalid relation direction')
        if decision=='NO' and relations:
            raise ValueError('NO decision cannot assert relations')
        if decision=='YES' and (not relations or any(not isinstance(row.get(f),str) or not row[f].strip() for f in ('evidence_a','evidence_b'))):
            raise ValueError('YES needs typed relations and evidence at both endpoints')
        completed.append(row)
    summary = {'status':'INCOMPLETE_REVIEW','reviewed':len(completed),'tasks':len(plan),
               'review_methods':dict(Counter(r['review_method'] for r in completed)),
               'production_modified':False}
    if len(completed) != len(plan):
        return summary
    metrics = {}
    scopes = sorted({r['scope'] for r in plan})
    for arm in ARMS:
        metrics[arm] = {}
        for scope in ['all',*scopes]:
            rows = [r for r in plan if arm in r['arm_membership'] and (scope=='all' or r['scope']==scope)]
            if not rows:
                continue
            total = sum(1/r['inclusion_probability'] for r in rows)
            fractions = {state:sum(1/r['inclusion_probability'] for r in rows if by_id[r['task_id']]['relation_exists']==state)/total
                         for state in ('YES','NO','UNCERTAIN')}
            population = manifest['arm_population'][arm] if scope=='all' else manifest['lanes'][f'{arm}/{scope}']['population']
            metrics[arm][scope] = {'reviewed_pairs':len(rows),'candidate_budget':population,
                'estimated_confirmed_fraction':fractions['YES'], 'estimated_uncertain_fraction':fractions['UNCERTAIN'],
                'estimated_confirmed_pairs_at_budget':population*fractions['YES']}
    summary.update(status='REVIEW_COMPLETE',metrics=metrics,
                   estimator='self-normalized inverse union-inclusion weights (Hajek ratio)',
                   limitations=['Estimates of confirmed pair yield, not relation recall or prediction type/direction accuracy.',
                                'UNCERTAIN is reported separately and is not counted as confirmed.',
                                'Review methods are self-declared; model-only labels are not independent human ground truth.',
                                'No confidence intervals or significance claim; finite-sample ratio estimates may be biased.'])
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True)
    p.add_argument('--labels',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('choose a new output file')
    evaluator=a.package/'evaluation_only'
    manifest=json.loads((evaluator/'manifest.json').read_text())
    for path, expected in [(evaluator/'key.jsonl',manifest['key_sha256']),
                           (a.package/'reviewer/tasks.jsonl',manifest['tasks_sha256'])]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('review package changed')
    result=score(read(evaluator/'key.jsonl'),read(a.labels),manifest)
    result['labels_sha256']=hashlib.sha256(a.labels.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
