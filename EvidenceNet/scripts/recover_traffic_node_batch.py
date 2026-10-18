#!/usr/bin/env python3
"""Recover one malformed boundary response in a separate traffic batch snapshot.

The original batch and frozen modules are never changed. Original prompt hashes
remain assembler compatibility fields; actual recovery requests have separate,
explicit provenance and are never represented as original-prompt model calls.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import shutil

import run_embedding_geometry_node_baseline as base
import run_hybrid_node_pilot as hybrid
from run_hybrid_node_v2 import audit
from run_traffic_relevance_graph import check

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'EvidenceNet/output/paper_relevance_urban_traffic_20261013'
MODEL = ROOT / 'external/models/Qwen3.5-35B-A3B'
SYSTEM = 'Return one short JSON object only. No deliberation, alternatives or markdown.'
POLICY = 'single_pair_short_json_recovery_v1'


def configure(root, target):
    base.SOURCE = hybrid.SOURCE = (root / 'prepared').resolve()
    hybrid.BASELINE = (target / 'baseline').resolve()
    base.REVISION = hybrid.REVISION = hybrid.PROMPT_REVISION = True
    base.GEOMETRY_ONLY = hybrid.GEOMETRY_ONLY = hybrid.BOUNDARY_V3 = False
    hybrid.POLICY_VERSION = 'hybrid-boundary-v2-embedding_geometry'


def tree_hashes(path):
    return {str(p.relative_to(path)): base.sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def assert_original(root, manifest):
    check(root)
    old = Path(manifest['original_batch'])
    if tree_hashes(old) != manifest['original_sha256']:
        raise ValueError('original_batch_changed')
    if base.sha(Path(__file__)) != manifest['recovery_code_sha256']:
        raise ValueError('recovery_code_changed')


def prepare(root, batch=5):
    check(root)
    old = root / 'nodes' / f'batch_{batch}'
    target = root / 'nodes' / f'batch_{batch}_recovery'
    if target.exists():
        manifest = base.read(target / 'recovery_manifest.json')
        assert_original(root, manifest)
        return target
    tasks = base.read(root / 'prepared/manifest.json')['batches'][batch]
    if list((old / 'hybrid').glob('**/evidence_nodes.jsonl')):
        raise ValueError('original_batch_already_assembled_would_duplicate_graph_nodes')
    failed = [t for t in tasks if not base.read(old / 'hybrid' / t / 'decisions.json')['valid']]
    if len(failed) != 1:
        raise ValueError('expected_exactly_one_failed_page')
    candidate = base.read(old / 'hybrid' / failed[0] / 'candidates.json')
    if len(candidate['pairs']) != 1 or candidate['roles']:
        raise ValueError('recovery_scoped_to_one_pair_and_no_roles')
    manifest = {'policy': POLICY, 'original_batch': str(old.resolve()), 'batch': batch,
                'tasks': tasks, 'failed_task': failed[0], 'model': str(MODEL.resolve()),
                'original_sha256': tree_hashes(old), 'recovery_code_sha256': base.sha(Path(__file__)),
                'original_outputs_modified': False,
                'scope': 'retry malformed response only; reuse every valid decision and all baseline inputs'}
    shutil.copytree(old, target)
    base.write(target / 'recovery_manifest.json', manifest)
    assert_original(root, manifest)
    return target


def request_for(candidate):
    if len(candidate['pairs']) != 1 or candidate['roles']:
        raise ValueError('single_pair_required')
    return (
        'Decide only whether the immediate left/right boundary continues the SAME SENTENCE. '
        'Shared topic or paragraph is insufficient. A non-null guard_reason requires SEPARATE. '
        'Never join a finished sentence or a colon-led list. Closing math delimiters do not '
        'cancel sentence-ending punctuation. Geometry and embedding are weak hints; '
        'grammatical continuity decides. Use only the supplied original source text. '
        'Return exactly {"pairs":[{"pair_id":"' + candidate['pairs'][0]['pair_id'] +
        '","decision":"CONTINUATION|SEPARATE","reason":"one short sentence, at most 40 words"}],'
        '"roles":[]}. No discussion, revisions or extra text.\n' +
        json.dumps({'task': candidate['task'], 'pairs': candidate['pairs']}, ensure_ascii=False))


def validate(raw, candidate):
    # Strict JSON prevents accepting a hand-picked fragment from a malformed answer.
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get('pairs'), list) or value.get('roles') != []:
        raise ValueError('required_pairs_and_empty_roles')
    if any(not isinstance(row, dict) for row in value['pairs']):
        raise ValueError('pair_not_object')
    errors = hybrid.validate_decisions(value, candidate)
    if errors:
        raise ValueError(','.join(errors))
    for row in value['pairs']:
        reason = row.get('reason')
        if not isinstance(reason, str) or not reason.strip() or len(reason.split()) > 40 or len(reason) > 300:
            raise ValueError('reason_must_be_short')
        if candidate['pairs'][0].get('guard_reason') and row['decision'] != 'SEPARATE':
            raise ValueError('guard_requires_separate')
    return value


def validate_reused(target, manifest):
    """All copied source inputs and successful model decisions remain byte-identical."""
    failed_prefix = 'hybrid/' + manifest['failed_task'] + '/'
    for relative, fingerprint in manifest['original_sha256'].items():
        if relative == failed_prefix + 'decisions.json':
            continue
        if base.sha(target / relative) != fingerprint:
            raise ValueError('reused_input_changed:' + relative)


def recover_decision(target, manifest, model=None):
    task = manifest['failed_task']; page = target / 'hybrid' / task
    candidate = base.read(page / 'candidates.json')
    original = base.read(Path(manifest['original_batch']) / 'hybrid' / task / 'decisions.json')
    current = base.read(page / 'decisions.json')
    if current['valid']:
        provenance = current.get('recovery_provenance', {})
        for kind in ['prompt', 'raw']:
            if base.sha(page / provenance[kind + '_file']) != provenance[kind + '_sha256']:
                raise ValueError('recovery_' + kind + '_changed')
        parsed = validate((page / provenance['raw_file']).read_text(), candidate)
        if current['pairs'] != parsed['pairs'] or current['roles'] != parsed['roles']:
            raise ValueError('recovery_decision_changed')
        return current
    if model is None:
        model = hybrid.create_llm({'provider': 'transformers', 'model': manifest['model'],
            'dtype': 'bfloat16', 'device_map': 'auto', 'require_cuda': True,
            'enable_thinking': False, 'max_new_tokens': 400})
    prompt = request_for(candidate)
    # A resumed invocation never overwrites earlier failed recovery attempts.
    start = len(list(page.glob('recovery_raw_*.txt'))) + 1
    for attempt in range(start, start + 2):
        prompt_file = f'recovery_prompt_{attempt:02d}.txt'
        raw_file = f'recovery_raw_{attempt:02d}.txt'
        (page / prompt_file).write_text(prompt)
        raw = model.generate_raw_with_images(SYSTEM, prompt, [], 400).raw
        (page / raw_file).write_text(raw)
        try:
            parsed = validate(raw, candidate)
        except (ValueError, TypeError, KeyError) as exc:
            base.write(page / f'recovery_validation_{attempt:02d}.json', {'valid': False, 'error': str(exc)})
            prompt = request_for(candidate) + '\nFORMAT REMINDER: return complete short JSON only. Validation: ' + str(exc)
            continue
        provenance = {'policy': POLICY, 'system': SYSTEM, 'prompt_file': prompt_file,
            'prompt_sha256': base.sha(page / prompt_file), 'raw_file': raw_file,
            'raw_sha256': base.sha(page / raw_file), 'model': manifest['model'],
            'generation': {'max_new_tokens': 400, 'do_sample': False, 'enable_thinking': False},
            'original_failed_decision_sha256': manifest['original_sha256']['hybrid/' + task + '/decisions.json'],
            'candidate_sha256': base.sha(page / 'candidates.json'),
            'original_prompt_used_for_generation': False,
            'compatibility_hashes': 'top-level prompt_sha256/chunk_prompts retain frozen assembly templates only; actual inference request is recovery_prompt_*'}
        result = {**original, 'valid': True, 'pairs': parsed['pairs'], 'roles': parsed['roles'],
                  'errors': [], 'fallback': None, 'recovery_provenance': provenance}
        base.write(page / f'recovery_validation_{attempt:02d}.json', {'valid': True})
        base.write(page / 'recovery_provenance.json', provenance)
        base.write(page / 'decisions.json', result)
        return result
    raise RuntimeError('recovery_response_invalid; original remains unchanged; no assembly')


def run(root, batch=5):
    target = prepare(root, batch); manifest = base.read(target / 'recovery_manifest.json')
    configure(root, target); validate_reused(target, manifest)
    recover_decision(target, manifest)
    if not all(base.read(target / 'hybrid' / t / 'decisions.json')['valid'] for t in manifest['tasks']):
        raise ValueError('invalid_decision_remains')
    hybrid.assemble(target / 'hybrid', manifest['tasks'])
    reports = [audit(t, root / 'prepared', target / 'hybrid') for t in manifest['tasks']]
    valid = all(r['valid'] and base.read(target / 'hybrid' / r['task'] / 'run_summary.json')['decision_valid'] for r in reports)
    report = {'valid': valid, 'pages': reports, 'batch': batch, 'recovery': POLICY,
              'reused_valid_pages': len(reports) - 1, 'retried_pages': 1,
              'node_policy': hybrid.POLICY_VERSION,
              'code_sha256': {Path(m.__file__).name: base.sha(Path(m.__file__)) for m in (base, hybrid)}}
    base.write(target / 'audit.json', report)
    validate_reused(target, manifest); assert_original(root, manifest)
    if not valid:
        raise RuntimeError('recovered_batch_coverage_failed')
    print(json.dumps({'recovery_batch': str(target), 'pages': len(reports), 'valid': valid}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--root', type=Path, default=DEFAULT)
    parser.add_argument('--batch', type=int, default=5)
    args = parser.parse_args()
    globals()[args.stage](args.root.resolve(), args.batch)
