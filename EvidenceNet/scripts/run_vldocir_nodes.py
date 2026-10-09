#!/usr/bin/env python3
"""Reusable hybrid-v2 stages for VL-DocIR, with strict source coverage auditing."""
import argparse
import json
from pathlib import Path

import run_embedding_geometry_node_baseline as base
import run_hybrid_node_pilot as hybrid
from run_hybrid_node_v2 import audit

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['describe', 'candidates', 'decide', 'assemble'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--batch', type=int, required=True)
    args = parser.parse_args()
    tasks = base.read(args.source / 'manifest.json')['batches'][args.batch]
    baseline = args.output / f'batch_{args.batch}' / 'baseline'
    result = args.output / f'batch_{args.batch}' / 'hybrid'
    base.SOURCE = hybrid.SOURCE = args.source.resolve()
    hybrid.BASELINE = baseline.resolve()
    base.REVISION = hybrid.REVISION = hybrid.PROMPT_REVISION = True
    base.GEOMETRY_ONLY = hybrid.GEOMETRY_ONLY = hybrid.BOUNDARY_V3 = False
    hybrid.POLICY_VERSION = 'hybrid-boundary-v2-embedding_geometry'
    embedding = ROOT / 'EvidenceNet/models/Qwen3-Embedding-0.6B'
    qwen = ROOT / 'external/models/Qwen3.5-35B-A3B'
    if args.stage == 'describe':
        base.describe(baseline, qwen, tasks)
    elif args.stage == 'candidates':
        base.assemble(baseline, embedding, tasks)
        hybrid.prepare(result, embedding, tasks)
    elif args.stage == 'decide':
        hybrid.decide(result, qwen, tasks)
        if not all(base.read(result / task / 'decisions.json')['valid'] for task in tasks):
            raise RuntimeError('Invalid Qwen decisions; do not accept fallback as hybrid results')
    else:
        hybrid.assemble(result, tasks)
        reports = [audit(task, args.source.resolve(), result) for task in tasks]
        valid = all(r['valid'] and base.read(result / r['task'] / 'run_summary.json')['decision_valid'] for r in reports)
        report = {'valid': valid, 'pages': reports, 'batch': args.batch,
                  'code_sha256': {Path(module.__file__).name: base.sha(Path(module.__file__))
                                  for module in (base, hybrid)},
                  'node_policy': hybrid.POLICY_VERSION}
        base.write(args.output / f'batch_{args.batch}' / 'audit.json', report)
        print(json.dumps(report), flush=True)
        if not valid:
            raise RuntimeError('EvidenceNode coverage audit failed')


if __name__ == '__main__':
    main()
