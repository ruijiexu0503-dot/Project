#!/usr/bin/env python3
"""Focused fresh-inference regression with frozen v2 EvidenceNode inputs."""
import argparse
from pathlib import Path
import shutil
import run_hybrid_node_pilot as h
from run_hybrid_node_v2 import audit, PREPARED, ROOT

TASKS = ['shard_1/entropy/page_0010', 'shard_1/gNtSaU-1511.05999v3/page_0006']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--arm', choices=['embedding_geometry', 'geometry'], required=True)
    a = p.parse_args()
    source = ROOT/'EvidenceNet/output/hybrid_node_v2_61078'/a.arm
    target = a.output/'batch_0'
    h.SOURCE = PREPARED; h.BASELINE = target/'baseline'
    h.REVISION = h.PROMPT_REVISION = h.BOUNDARY_V3 = True
    result = target/'hybrid'
    for task in TASKS:
        matches = list(source.glob(f'batch_*/hybrid/{task}/candidates.json'))
        if len(matches) != 1: raise ValueError(f'Ambiguous source: {task}')
        old = matches[0]
        c = h.read(old)
        if c['input_representation_sha256'] != h.sha(PREPARED/task/'input_representation.json') or c['page_image_sha256'] != h.sha(PREPARED/task/'original.png'):
            raise ValueError(f'Changed frozen source: {task}')
        batch = old.parents[4]
        shutil.copytree(batch/'baseline'/task, h.BASELINE/task, dirs_exist_ok=True)
        c['policy_version'] = 'hybrid-boundary-v3-' + a.arm
        c['parent_candidate_sha256'] = h.sha(old)
        h.write(result/task/'candidates.json', c)
        (result/task/'prompt.txt').write_text(h.prompt(task,c['pairs'],c['roles']))
    h.decide(result, ROOT/'external/models/Qwen3.5-35B-A3B', TASKS)
    h.assemble(result, TASKS)
    rows = [audit(task,PREPARED,result) for task in TASKS]
    valid = all(h.read(result/task/'decisions.json')['valid'] for task in TASKS)
    h.write(target/'audit.json', {'mode':'fresh_qwen_v3_focused', 'arm':a.arm,
        'pages':rows,'decisions_valid':valid,'independent_holdout':False,'production_modified':False})
    if not valid or not all(r['valid'] for r in rows): raise SystemExit(2)
    from evaluate_hybrid_node_v2 import evaluate
    evaluate(a.output)


if __name__ == '__main__': main()
