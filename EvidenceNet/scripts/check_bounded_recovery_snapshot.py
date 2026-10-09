#!/usr/bin/env python3
"""Regression replay of integrated recovery against frozen flows and model replies."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import run_relation_first_corpus_shadow as runner


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--cached-decisions', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Use a new output directory')
    args.output.mkdir(parents=True)
    pages, anchors = [], []
    for path in sorted(args.source.glob('shard_*/*/*/summary.json')):
        source = path.parent
        summary = runner.base.read(path)
        rep = runner.base.read(source/'input_representation.json')
        original_flow = runner.base.read(source/'flow.json') if summary.get('structural_valid') else None
        raw = json.dumps(original_flow) if original_flow is not None else runner.base.read(source/'flow_attempt_0.json')['raw']
        target = args.output/rep['document_id']/rep['page']
        target.mkdir(parents=True)
        cache = next((root/rep['document_id']/rep['page']/'raw.json' for root in args.cached_decisions
                      if (root/rep['document_id']/rep['page']/'raw.json').exists()), None)
        class Replay:
            calls = 0
            def generate_raw_with_images(self, *unused):
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(raw=raw)
                if self.calls == 2 and cache:
                    return SimpleNamespace(raw=runner.base.read(cache)['raw'])
                raise ValueError('No saved model response for this repair')
        row = {'document_id': rep['document_id'], 'page': rep['page'], 'original_status': summary['status'],
               'replay_not_fresh_inference': True, 'semantic_validated': False,
               'baseline_response_sha256': hashlib.sha256(raw.encode()).hexdigest(),
               'cached_decision_path': str(cache) if cache else None,
               'cached_decision_sha256': hashlib.sha256(cache.read_bytes()).hexdigest() if cache else None}
        try:
            flow = runner.make_flow(rep, Path(rep['source_image']), Replay(), target, False, recovery_policy='bounded-v1')
            row.update(structural_valid=runner.validate_flow(flow, rep)['valid'],
                       recovery=runner.base.read(target/'flow_recovery.json'))
            if original_flow is not None:
                assert flow == original_flow, 'previously valid flow changed'
            runner.write(target/'flow.json', flow)
        except ValueError as exc:
            row.update(structural_valid=False, error=str(exc))
        pages.append(row)
        ledger = runner.base.read(source/'candidate_ledger.json') if (source/'candidate_ledger.json').exists() else {}
        for raw_path in sorted(source.glob('*_edge_attempt_0.json')):
            vid = raw_path.name.split('_edge_attempt_')[0]
            candidates = {r['unit_id']: r for r in ledger[vid]['selected']}
            record = {'source_file': str(raw_path)}
            try:
                response = runner.base.extract_json(runner.base.read(raw_path)['raw'])
                strict, _ = runner.validate_edges_individually(response, response['visual_label'], candidates)
                partial, rejected = runner.validate_edges_individually(response, response['visual_label'], candidates, True)
                key = lambda e: (e['text_unit_id'],e['relation'],e['source_char_start'],e['source_char_end'])
                assert {key(e) for e in strict['edges']} <= {key(e) for e in partial['edges']}
                record.update(before=len(strict['edges']), after=len(partial['edges']), rejected=rejected)
            except (ValueError, KeyError, TypeError) as exc:
                record.update(error=str(exc), before=0, after=0)
            anchors.append(record)
    result = {'mode': 'frozen_response_regression_not_semantic_evaluation', 'pages': pages,
              'structural_valid': sum(r['structural_valid'] for r in pages),
              'flow_failed': sum(not r['structural_valid'] for r in pages),
              'previously_valid_unchanged': sum(r['original_status'] != 'flow_failed' and r['structural_valid'] for r in pages),
              'duplicate_repaired': sum(r.get('recovery', {}).get('status') == 'repaired' for r in pages),
              'visual_only': sum(r.get('recovery', {}).get('status') == 'visual_only' for r in pages),
              'local_relations_before': sum(r['before'] for r in anchors),
              'local_relations_after': sum(r['after'] for r in anchors),
              'production_modified': False}
    runner.write(args.output/'summary.json', result)
    runner.write(args.output/'anchor_regression.json', anchors)
    print(json.dumps({k:v for k,v in result.items() if k != 'pages'}, indent=2))


if __name__ == '__main__':
    main()
