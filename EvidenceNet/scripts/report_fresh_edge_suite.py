#!/usr/bin/env python3
"""Strict three-way scoring, separate from historical broad RELATED metrics."""
import argparse
from collections import Counter
from pathlib import Path
from run_node_context_edges import rows, write
from run_routed_edge_context import ARMS

def score(references, predictions):
    by_id = {p['task_id']:p for p in predictions}
    assert len(by_id) == len(predictions)
    stats, confusion = Counter(), Counter()
    for ref in references:
        if not ref['decision_evaluable']:
            stats['boundary_excluded'] += 1
            continue
        expected, = ref['allowed_decisions']
        stats['scored_total'] += 1
        stats['expected_' + expected] += 1
        p = by_id.get(ref['task_id'])
        actual = 'MISSING' if p is None else 'INVALID' if not p['valid'] else p['result']['decision']
        confusion[(expected, actual)] += 1
        stats['exact_correct'] += actual == expected
        stats['missing'] += actual == 'MISSING'
        stats['invalid'] += actual == 'INVALID'
        # Missing/invalid are retained in denominators, never treated as correct NO_LINK.
        stats['evidence_tp'] += expected == actual == 'EVIDENCE_LINK'
        stats['evidence_overpromotion'] += actual == 'EVIDENCE_LINK' and expected != actual
        stats['navigation_overpromotion'] += actual == 'EVIDENCE_LINK' and expected == 'NAVIGATION_LINK'
        stats['negative_false_link'] += expected == 'NO_LINK' and actual in {'NAVIGATION_LINK','EVIDENCE_LINK'}
    return {**dict(stats), 'exact_accuracy_all_scored':stats['exact_correct']/stats['scored_total'] if stats['scored_total'] else None,
        'evidence_recall_all_expected':stats['evidence_tp']/stats['expected_EVIDENCE_LINK'] if stats['expected_EVIDENCE_LINK'] else None,
        'confusion':[{'expected':e,'actual':a,'count':n} for (e,a),n in sorted(confusion.items())]}

def report(out):
    refs = rows(out/'reference.jsonl')
    result = {'scope':'Provisional fresh challenge labels; correlated cases; fixed-pair verification, not retrieval.', 'arms':{}}
    for arm in ARMS:
        p = out/arm/'predictions.jsonl'
        predictions = rows(p) if p.exists() else []
        entries = rows(out/arm/'inputs.jsonl')
        groups = {e['task']['task_id']:e['routing']['group'] for e in entries}
        result['arms'][arm] = {g:score([r for r in refs if g=='all' or groups[r['task_id']]==g],predictions)
                               for g in ['all','prose','visual_table','formula']}
    write(out/'strict_summary.json',result)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    report(args.output)
