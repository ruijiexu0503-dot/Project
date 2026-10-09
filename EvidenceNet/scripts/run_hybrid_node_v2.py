#!/usr/bin/env python3
"""Paired v2 EvidenceNode experiment; frozen descriptions, fresh boundary decisions.

Replay uses OLD model decisions and geometry-only assembly to test guards locally.
It is explicitly not a fresh-model or embedding-ablation quality measurement.
"""
import argparse
from collections import Counter
import gc
import json
from pathlib import Path
import shutil

import run_embedding_geometry_node_baseline as base
import run_hybrid_node_pilot as hybrid

ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT/'EvidenceNet/output/hybrid_49page_stress_prepared_20261007'
OLD = ROOT/'EvidenceNet/output/hybrid_49page_stress_run_20261007'


def audit(task, prepared, output):
    rep = base.read(prepared/task/'input_representation.json')
    nodes = hybrid.jsonl(output/task/'evidence_nodes.jsonl')
    side = base.read(output/task/'structural_and_unresolved.json')
    atoms = {a['atom_id']: a for a in rep['atoms']}
    side_ids = side['structural_atom_ids'] + side['unassigned_caption_atom_ids']
    source_atoms = Counter(a for n in nodes for a in n['source_atom_ids'])
    fragments = Counter(f for n in nodes for f in n['source_fragment_ids'])
    for aid in side_ids:
        fragments.update(f['fragment_id'] for f in atoms[aid]['text_fragments'])
    checks = {
        'atoms_once': source_atoms + Counter(side_ids) == Counter(atoms.keys()),
        'fragments_once': fragments == Counter(f['fragment_id'] for a in atoms.values() for f in a['text_fragments']),
        'tables_in_evidence': all(source_atoms[a['atom_id']] == 1 for a in atoms.values() if a['atom_type'] == 'table'),
        'structural_excluded': all(source_atoms[a['atom_id']] == 0 for a in atoms.values() if base.structural(a)),
        'visuals_once': Counter(v for n in nodes for v in n['source_visual_bundle_ids']) == Counter(v['visual_bundle_id'] for v in rep['visual_bundles']),
        'native_once': Counter(c['member_id'] for n in nodes for c in n['native_visual_components']) == Counter(c['member_id'] for v in rep['visual_bundles'] for c in v.get('native_components', [])),
    }
    return {'task': task, 'checks': checks, 'valid': all(checks.values()),
            'tables': sum(a['atom_type'] == 'table' for a in atoms.values()), 'nodes': len(nodes)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--batch', type=int)
    p.add_argument('--arm', choices=['embedding_geometry', 'geometry'], default='embedding_geometry')
    p.add_argument('--replay', action='store_true')
    a = p.parse_args()
    manifest = base.read(PREPARED/'manifest.json')
    batches = range(len(manifest['batches'])) if a.batch is None else [a.batch]
    embedding = ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B'
    model = ROOT/'external/models/Qwen3.5-35B-A3B'
    base.SOURCE = hybrid.SOURCE = PREPARED
    base.REVISION = hybrid.REVISION = True
    hybrid.PROMPT_REVISION = not a.replay
    base.GEOMETRY_ONLY = hybrid.GEOMETRY_ONLY = a.replay or a.arm == 'geometry'
    hybrid.POLICY_VERSION = 'hybrid-boundary-v2-' + a.arm
    reports = []
    for batch in batches:
        tasks = manifest['batches'][batch]
        old = OLD/f'batch_{batch}'
        for task in tasks:
            provenance = base.read(old/'hybrid'/task/'candidates.json')
            if (provenance['input_representation_sha256'] != base.sha(PREPARED/task/'input_representation.json')
                    or provenance['page_image_sha256'] != base.sha(PREPARED/task/'original.png')):
                raise ValueError(f'Frozen source changed: {task}')
        target = a.output/f'batch_{batch}'
        baseline = target/'baseline'; result = target/'hybrid'
        baseline.mkdir(parents=True, exist_ok=True)
        # Identical crop descriptions in both arms; retain original provenance.
        shutil.copy2(old/'embedding_geometry/visual_descriptions.jsonl', baseline/'visual_descriptions.jsonl')
        base.assemble(baseline, embedding, tasks)
        hybrid.BASELINE = baseline
        if a.replay:
            for task in tasks:
                dest = result/task
                dest.mkdir(parents=True, exist_ok=True)
                for name in ['candidates.json', 'prompt.txt', 'decisions.json']:
                    shutil.copy2(old/'hybrid'/task/name, dest/name)
                for path in (old/'hybrid'/task).glob('decision_chunk_*.txt'):
                    shutil.copy2(path, dest/path.name)
        else:
            hybrid.prepare(result, embedding, tasks)
            gc.collect()
            import torch
            torch.cuda.empty_cache()
            hybrid.decide(result, model, tasks)
        hybrid.assemble(result, tasks)
        rows = [audit(task, PREPARED, result) for task in tasks]
        decisions_valid = all(base.read(result/task/'decisions.json')['valid'] for task in tasks)
        report = {'mode': 'frozen_decision_guard_replay' if a.replay else 'fresh_qwen_v2',
                  'arm': 'geometry_replay' if a.replay else a.arm, 'batch': batch,
                  'pages': rows, 'decisions_valid': decisions_valid,
                  'valid': all(r['valid'] for r in rows) and decisions_valid,
                  'description_policy': 'frozen_unverified_retrieval_hints',
                  'source_code_sha256': {path.name: base.sha(path) for path in
                      [Path(__file__), Path(base.__file__), Path(hybrid.__file__),
                       Path(__file__).with_name('evidence_node_guards.py')]},
                  'independent_holdout': False, 'production_modified': False}
        base.write(target/'audit.json', report)
        reports.append(report)
        if not report['valid']: raise RuntimeError(f'Batch {batch} failed validation')
    base.write(a.output/(f'audit_batch_{a.batch}.json' if a.batch is not None else 'audit.json'), reports)


if __name__ == '__main__':
    main()
