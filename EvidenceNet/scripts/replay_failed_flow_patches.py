#!/usr/bin/env python3
"""Replay frozen failed responses: isolate assignment repair from regeneration."""
import argparse
import hashlib
import json
from pathlib import Path

import run_relation_first_corpus_shadow as runner


def run(args):
    pages = sorted(args.baseline.glob('shard_*/*/*/summary.json'))
    results = []
    llm = None
    for summary_path in pages:
        page = summary_path.parent
        summary = runner.base.read(summary_path)
        if summary['status'] != 'flow_failed':
            continue
        rep = runner.base.read(page / 'input_representation.json')
        raw = runner.base.read(page / 'flow_attempt_0.json')['raw']
        flow = runner.base.extract_json(raw)
        target = args.output / rep['document_id'] / rep['page']
        fixed, plan = runner.flow_recovery.prepare_patch(flow, rep)
        if not runner.validate_flow(fixed, rep)['valid'] and llm is None:
            llm = runner.base.create_llm(runner.inference_config(args))
        row = {'document_id': rep['document_id'], 'page': rep['page'],
               'baseline': str(page.resolve()), 'experiment': 'frozen_failed_response_patch',
               'production_modified': False, 'inference_config': runner.inference_config(args),
               'source_image_sha256': hashlib.sha256(Path(rep['source_image']).read_bytes()).hexdigest(),
               'code_sha256': {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                               for module in (runner, runner.flow_recovery)},
               'input_sha256': hashlib.sha256((page / 'input_representation.json').read_bytes()).hexdigest(),
               'response_sha256': hashlib.sha256(raw.encode()).hexdigest()}
        runner.write(target / 'provenance.json', row)
        try:
            fixed = runner.repair_flow_patch(flow, rep, Path(rep['source_image']), llm, target)
            runner.write(target / 'flow.json', fixed)
            row.update(status='repaired', structural_valid=True, semantic_validated=False)
        except ValueError as exc:
            row.update(status='failed', error=str(exc), structural_valid=False)
        audit = runner.base.read(target / 'flow_recovery.json')
        row['additional_model_calls'] = audit['additional_model_calls']
        runner.write(target / 'summary.json', row)
        results.append(row)
        runner.write(args.output / 'summary.json', {'pages': results})
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--device', default='cuda', choices=['cpu', 'cuda'])
    run(parser.parse_args())
