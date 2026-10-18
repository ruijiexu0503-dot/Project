#!/usr/bin/env python3
"""Compare fixed regression cases; this is not an independent precision estimate."""
import argparse
from collections import Counter
from pathlib import Path
from run_node_context_edges import read, rows, write, jsonl


def compare(out, previous):
    audit=previous/'audit'
    pairs=rows(out/'candidate_pairs.jsonl') if (out/'candidate_pairs.jsonl').exists() else []
    edges=rows(out/'semantic_edges.jsonl')
    candidates={tuple(sorted((p['source'],p['target']))):p for p in pairs}
    accepted={tuple(sorted((e['source'],e['target']))) for e in edges}
    pending=set()
    for pair in rows(out/'verification_queue.jsonl') if (out/'verification_queue.jsonl').exists() else []:
        if not (out/'context_decisions'/f"{pair['pair_id']}.json").exists():pending.add(tuple(sorted((pair['source'],pair['target']))))
    cases=[]
    for old in rows(audit/'reviewed_edges.jsonl')+rows(audit/'omissions.jsonl'):
        key=tuple(sorted((old['source'],old['target'])));p=candidates.get(key)
        verdict=old.get('assistant_review',{}).get('status',old.get('review_status'))
        cases.append({'case_id':old.get('case_id',old.get('id')),'source':old['source'],'target':old['target'],
                      'previous_review':verdict,'candidate_present':p is not None,'accepted_edge_present':key in accepted,
                      'verification_pending':key in pending,'routes':p['routes'] if p else [],
                      'review_provenance':'previous assistant audit; not independent human ground truth'})
    rejects=[c for c in cases if c['previous_review'].startswith('REJECT')]
    result={'previous_summary':read(previous/'summary.json'),'current_summary':read(out/'summary.json'),
            'known_rejected_cases':len(rejects),'known_rejected_removed_from_candidates':sum(not c['candidate_present'] for c in rejects),
            'known_rejected_still_accepted':sum(c['accepted_edge_present'] for c in rejects),
            'known_rejected_verification_pending':sum(c['verification_pending'] for c in rejects),
            'omission_cases':sum(c['case_id'].startswith('OMISSION') for c in cases),
            'omissions_now_candidates':sum(c['candidate_present'] for c in cases if c['case_id'].startswith('OMISSION')),
            'omissions_now_edges':sum(c['accepted_edge_present'] for c in cases if c['case_id'].startswith('OMISSION')),
            'independent_precision_or_retrieval_gain_measured':False}
    jsonl(out/'regression_cases.jsonl',cases);write(out/'regression_summary.json',result)
    print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--previous',type=Path,default=Path('EvidenceNet/output/node_context_edges_v1_20261011'))
    args=p.parse_args();compare(args.output,args.previous)
