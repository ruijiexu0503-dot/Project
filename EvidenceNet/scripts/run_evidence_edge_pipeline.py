#!/usr/bin/env python3
"""Reusable post-node edge pipeline; never rewrites source nodes or frozen experiments."""
from __future__ import annotations

import argparse
import copy
from collections import Counter
from pathlib import Path
import sys

import numpy as np

from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
import run_hierarchical_edge_retrieval as retrieval
import repair_edge_candidate_allocation as allocation
import compare_edge_embedding_models as encoders
import run_relatedness_pilot as broad
import run_all_node_multimodal_relatedness as multimodal
import run_routed_edge_context as verifier
import edge_source_roles

# These are the actual profiles used in the local matched encoder experiments.
# No query instruction: this is symmetric node-to-node retrieval, not query QA.
PROFILES = {
    'qwen3-8b': ('Qwen3-Embedding-8B', 'last_token', 'left', 6),
    'qwen3-4b': ('Qwen3-Embedding-4B', 'last_token', 'left', 6),
    'qwen3-0.6b': ('Qwen3-Embedding-0.6B', 'last_token', 'left', 8),
    'gte-large-en': ('gte-large-en-v1.5', 'cls', 'right', 32),
    'bge-large-en': ('bge-large-en-v1.5', 'cls', 'right', 32),
    'mxbai-large': ('mxbai-embed-large-v1', 'cls', 'right', 32),
    'gte-qwen2': ('gte-Qwen2-1.5B-instruct', 'last_token', 'left', 6),
    'bge-en-icl': ('bge-en-icl', 'last_token', 'left', 6),
}
CODE = [Path(__file__), Path(retrieval.__file__), Path(allocation.__file__),
        Path(edge_source_roles.__file__),
        Path(encoders.__file__), Path(broad.__file__), Path(multimodal.__file__),
        Path(verifier.__file__), Path(verifier.gate.__file__),
        Path(__file__).with_name('run_node_context_edges.py'),
        Path(__file__).with_name('dolphin_text.py'),
        Path(__file__).with_name('edge_text_views.py'),
        Path(__file__).with_name('postprocess_named_identity_gate.py'),
        ROOT/'EvidenceNet/evidence_graph/llm_client.py']


def model_identity(profile, path):
    _, pooling, padding, batch = PROFILES[profile]
    if not (path/'config.json').is_file() or not (path/'tokenizer.json').is_file():
        raise ValueError('Local encoder config/tokenizer missing: ' + str(path))
    return {'profile': profile, 'path': str(path.resolve()), 'pooling': pooling,
            'padding_side': padding, 'batch_size': batch, 'max_length': 512,
            'query_instruction': None, 'normalize': 'L2',
            'files_sha256': {p.name: sha(p) for p in sorted(path.glob('*.json'))}}


def resolved(node):
    article = node.get('article_id')
    return bool(article and not any(s in article.upper() for s in ('UNKNOWN', 'UNRESOLVED')))


def prepare(out, node_path, policy_path, profile, model_path=None,
            budget=1301, escape_budget=96, reference_budget=96):
    if out.exists():
        raise ValueError('Fresh output required; resume with the next stage, never overwrite')
    if min(budget, escape_budget, reference_budget) < 1 or escape_budget + reference_budget > budget:
        raise ValueError('Positive budgets required; escape + reference must fit total budget')
    records, policies = rows(node_path), read(policy_path)
    nodes = {n['id']: n for n in records}
    if len(nodes) != len(records) or any(i not in policies for i in nodes):
        raise ValueError('Duplicate IDs or missing eligibility policy')
    excluded, selected = [], {}
    for nid, n in nodes.items():
        if not policies[nid].get('eligible') or not resolved(n):
            excluded.append({'node_id': nid, 'reason': 'ineligible_or_unresolved_article'})
            continue
        if not n.get('document'):
            raise ValueError('Missing document identity: ' + nid)
        selected[nid] = n
    if not selected:
        raise ValueError('No eligible nodes with resolved article membership')
    # Article IDs must be globally scoped; do not silently group separate documents.
    ownership = {}
    for n in selected.values():
        if ownership.setdefault(n['article_id'], n['document']) != n['document']:
            raise ValueError('Article ID reused across documents: ' + n['article_id'])
    model_path = model_path or ROOT/'EvidenceNet/models'/PROFILES[profile][0]
    config = {'version': 'evidence-edge-pipeline-v1',
        'embedding': model_identity(profile, model_path),
        'selection': {'budget': budget, 'escape_budget': escape_budget,
                      'reference_budget': reference_budget},
        'verifier': 'matched_control_original_multimodal_no_scope_expansion_no_added_context',
        'export': 'undirected RELATED model proposals; no automatic evidence propagation',
        'experimental_disabled': ['text_scope', 'formula_context_expansion', 'resolved_citation_lane',
                                  'reference_context_lane', 'contiguous_reading_lane'],
        'labels_used': False, 'source_nodes_modified': False}
    views = retrieval.make_views(selected, policies)
    views, _ = allocation.eligible_views(views, policies)
    if not views:
        raise ValueError('No eligible textual/description retrieval views')
    jsonl(out/'nodes.jsonl', list(selected.values()))
    write(out/'policies.json', {i: policies[i] for i in selected})
    jsonl(out/'excluded_nodes.jsonl', excluded)
    jsonl(out/'views.jsonl', views)
    write(out/'config.json', config)
    write(out/'manifest.json', {
        'files': {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()},
        'code': {str(p.relative_to(ROOT)): sha(p) for p in CODE},
        'sources': {str(p.resolve()): sha(p) for p in [node_path, policy_path]}})
    return {'nodes': len(selected), 'excluded': len(excluded), 'views': len(views),
            'embedding': profile, 'status': 'PREPARED_NO_INFERENCE'}


def check(out):
    manifest = read(out/'manifest.json')
    for relative, digest in manifest['files'].items():
        if sha(out/relative) != digest:
            raise ValueError('Changed pipeline snapshot: ' + relative)
    for relative, digest in manifest['code'].items():
        if sha(ROOT/relative) != digest:
            raise ValueError('Changed pipeline code: ' + relative)
    return read(out/'config.json')


def check_artifact(out, filename):
    record = read(out/(filename + '.sha256.json'))
    if sha(out/filename) != record['sha256']:
        raise ValueError('Changed artifact: ' + filename)


def artifact(out, filename, values):
    jsonl(out/filename, values)
    write(out/(filename + '.sha256.json'), {'sha256': sha(out/filename)})


def validate_vectors(vectors, count):
    if vectors.ndim != 2 or vectors.shape[0] != count or not vectors.shape[1]:
        raise ValueError('Embedding row/dimension mismatch')
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-3):
        raise ValueError('Expected finite L2-normalized vectors')


def embed(out, device='cuda'):
    config = check(out)
    profile = config['embedding']
    if profile != model_identity(profile['profile'], Path(profile['path'])):
        raise ValueError('Encoder profile/tokenizer changed')
    signature = {'embedding': profile, 'views_sha256': sha(out/'views.jsonl'), 'device': device}
    vector_path = out/'view_vectors.npy'
    if vector_path.exists() or (out/'embedding_manifest.json').exists():
        cached = read(out/'embedding_manifest.json')
        if cached['signature'] != signature or cached['vectors_sha256'] != sha(vector_path):
            raise ValueError('Stale embedding cache; do not mix model profiles or view rows')
        validate_vectors(np.load(vector_path, allow_pickle=False), len(rows(out/'views.jsonl')))
        return cached
    views = rows(out/'views.jsonl')
    vectors, execution = encoders.embed([v['retrieval_text'] for v in views], Path(profile['path']),
        profile['batch_size'], profile['max_length'], device, profile['pooling'], profile['padding_side'])
    validate_vectors(vectors, len(views))
    np.save(vector_path, vectors)
    record = {'signature': signature, 'vectors_sha256': sha(vector_path), 'execution': execution}
    write(out/'embedding_manifest.json', record)
    return record


def select(nodes, policies, views, vectors, settings):
    validate_vectors(vectors, len(views))
    pool = retrieval.retrieve(views, vectors)
    articles, native = retrieval.route_and_select(nodes, pool)
    escape = allocation.unique_escape(list(pool.values()), native,
        budget=settings['budget'], escape_budget=settings['escape_budget'])
    refs = allocation.references(nodes, policies)
    pairs = allocation.reserve_references(escape, refs,
        budget=settings['budget'], reference_budget=settings['reference_budget'])
    if len(pairs) > settings['budget'] or len({allocation.key(p) for p in pairs}) != len(pairs):
        raise ValueError('Invalid unique-pair budget')
    return articles, pairs, refs


def retrieve(out):
    config = check(out)
    meta = read(out/'embedding_manifest.json')
    if (meta['signature']['embedding'] != config['embedding'] or
        meta['signature']['views_sha256'] != sha(out/'views.jsonl') or
        meta['vectors_sha256'] != sha(out/'view_vectors.npy')):
        raise ValueError('Vector cache identity mismatch')
    if (out/'node_candidates.jsonl').exists():
        check_artifact(out, 'node_candidates.jsonl')
        check_artifact(out, 'reference_candidates.jsonl')
        return {'status': 'CANDIDATES_ALREADY_FROZEN'}
    nodes = {n['id']: n for n in rows(out/'nodes.jsonl')}
    articles, pairs, refs = select(nodes, read(out/'policies.json'), rows(out/'views.jsonl'),
        np.load(out/'view_vectors.npy', allow_pickle=False), config['selection'])
    artifact(out, 'article_candidates.jsonl', articles)
    artifact(out, 'reference_candidates.jsonl', refs)
    artifact(out, 'node_candidates.jsonl', pairs)
    return {'candidates': len(pairs), 'references': len(refs), 'semantic_edges': 0}


def prepare_verifier(out, model_path):
    check(out)
    check_artifact(out, 'node_candidates.jsonl')
    destination = out/'verifier'
    if destination.exists():
        verifier.verify(destination, model_path)
        return {'status': 'VERIFIER_ALREADY_FROZEN'}
    nodes = {n['id']: n for n in rows(out/'nodes.jsonl')}
    policies = read(out/'policies.json')
    entries, errors = [], []
    for pair in rows(out/'node_candidates.jsonl'):
        task = {'task_id': broad.task_id(allocation.key(pair))}
        entry = {'task': task, 'images': [], 'lookups': {}}
        try:
            for side, nid in zip(('A', 'B'), allocation.key(pair)):
                node = copy.deepcopy(nodes[nid])
                node['eligible_members'] = policies[nid]['members']
                task[side], entry['lookups'][side] = broad.catalog(node, side, destination, entry['images'])
                if not entry['lookups'][side]:
                    raise ValueError('No eligible endpoint evidence: ' + nid)
                crop = multimodal.node_crop(node, destination)
                if crop is None:
                    raise ValueError('Missing original node image: ' + nid)
                entry['images'].append(str(crop))
                task[side]['node_source_image_number'] = len(entry['images'])
            kinds = {s: verifier.modality(nodes[task[s]['node_id']], set()) for s in ('A','B')}
            group = 'visual_table' if 'visual_table' in kinds.values() else 'formula' if 'formula' in kinds.values() else 'prose'
            entry.update(routing={**kinds, 'group': group}, contexts={'A': [], 'B': []})
            entry['prompt'] = verifier.gate.prompt(task) + verifier.POLICY + '{"A": [], "B": []}'
            entry['image_sha256'] = [sha(p) for p in entry['images']]
            entry['inference_key'] = verifier.inference_key(entry)
            entries.append(entry)
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            errors.append({'source': pair['source'], 'target': pair['target'], 'error': str(exc)})
    jsonl(destination/'control/inputs.jsonl', entries)
    jsonl(destination/'preparation_errors.jsonl', errors)
    jsonl(destination/'reference.jsonl', [])  # No evaluation labels in operational input.
    write(destination/'protocol.json', {'source_root': str(ROOT),
        'model_config_sha256': sha(model_path/'config.json'), 'model': str(model_path),
        'arms': ['control'], 'system': verifier.SYSTEM, 'pairs': len(entries),
        'candidate_count': len(rows(out/'node_candidates.jsonl')), 'preparation_failures': len(errors),
        'input_manifest_sha256': sha(out/'manifest.json'),
        'inference': {'max_new_tokens': 700, 'attempts': 2, 'thinking': False, 'sampling': False}})
    verifier.freeze(destination)
    manifest = read(destination/'manifest.json')
    manifest['code'][str(Path(__file__).relative_to(ROOT))] = sha(__file__)
    write(destination/'manifest.json', manifest)
    return {'prepared_pairs': len(entries), 'preparation_failures': len(errors)}


def run_verifier(out, model_path, image_root, minutes):
    check(out)
    # Reuse the frozen GPU/checkpoint implementation with ONE control arm only.
    # No four-arm experiment or global monkey-patch survives this invocation.
    old = verifier.ARMS
    try:
        verifier.ARMS = ('control',)
        verifier.run(out/'verifier', model_path, image_root, minutes)
    finally:
        verifier.ARMS = old


def export_record(entry, prediction, reference_keys, nodes=None):
    a, b = (entry['task'][s]['node_id'] for s in ('A','B'))
    record = {'task_id': entry['task']['task_id'], 'source': a, 'target': b,
              'direction': 'UNDIRECTED', 'evidence_propagation_allowed': False}
    if prediction is None or not prediction['valid']:
        return 'review', {**record, 'status': 'MISSING' if prediction is None else 'INVALID'}
    result = prediction['result']
    record['model_result'] = result
    if result['decision'] in {'NO_LINK', 'UNCERTAIN'}:
        return ('rejected' if result['decision'] == 'NO_LINK' else 'review'), record
    reasons = []
    if nodes is not None:
        audit = edge_source_roles.audit_edge(record, nodes)
        record['source_role_audit'] = audit
        if audit['route'] != 'semantic':
            reasons.append('bibliography_or_unresolved_source_requires_reference_review'
                           if audit['route'] == 'reference_review'
                           else 'administrative_boilerplate_requires_separate_review')
    if result['discovery_level'] < 2:
        reasons.append('link_with_low_discovery_level')
    if result['decision'] == 'NAVIGATION_LINK' and result['shared_identity'] is None:
        reasons.append('navigation_missing_checked_identity')
    if result['basis'] == 'DIRECT_COMPLEMENT' and tuple(sorted((a,b))) not in reference_keys:
        reasons.append('direct_complement_without_verified_source_pointer_requires_review')
    if result['basis'] == 'CLAIM_CORRESPONDENCE' and not result['matched_claim'].strip():
        reasons.append('empty_corresponding_claim')
    if any(not any(x.get('kind') in verifier.gate.ORIGINAL_KINDS for x in result['anchors'][s]) for s in ('A','B')):
        reasons.append('no_original_text_or_caption_anchor_on_both_sides')
    if reasons:
        return 'review', {**record, 'review_reasons': reasons}
    return 'related', {**record, 'edge_type': 'RELATED', 'status': 'MODEL_PROPOSED_NOT_HUMAN_VERIFIED'}


def export(out):
    check(out)
    verifier.verify(out/'verifier')
    check_artifact(out, 'reference_candidates.jsonl')
    entries = rows(out/'verifier/control/inputs.jsonl')
    nodes = {n['id']: n for n in rows(out/'nodes.jsonl')}
    cache = verifier.checked_cache(out/'verifier', {'control': entries})
    references = {allocation.key(p) for p in rows(out/'reference_candidates.jsonl')}
    buckets = {'related': [], 'review': [], 'rejected': []}
    for entry in entries:
        prediction = cache.get(entry['inference_key'])
        # Revalidate recorded output from its original raw response before exporting.
        if prediction and prediction['valid']:
            raw = verifier.extract_json(prediction['attempts'][-1]['raw'])
            raw, repairs = verifier.repair_optional_metadata(raw, entry)
            checked = verifier.gate.validate(raw, entry)
            if checked != prediction['result'] or repairs != prediction['metadata_repairs']:
                raise ValueError('Prediction/raw audit mismatch')
        bucket, record = export_record(entry, prediction, references, nodes)
        buckets[bucket].append(record)
    errors = rows(out/'verifier/preparation_errors.jsonl')
    buckets['review'].extend({**e, 'status': 'PREPARATION_FAILED', 'evidence_propagation_allowed': False} for e in errors)
    for name, records in buckets.items():
        jsonl(out/'graph'/(name + '.jsonl'), records)
    summary = {'counts': {k: len(v) for k,v in buckets.items()},
        'candidate_count': len(rows(out/'node_candidates.jsonl')), 'processed': len(cache),
        'inference_complete': len(cache) == len(entries), 'preparation_failures': len(errors),
        'complete': len(cache) == len(entries) and not errors,
        'automatic_evidence_propagation': False, 'source_graph_modified': False}
    write(out/'graph/summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare','embed','retrieve','prepare-verifier','verify','export','check'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--nodes', type=Path)
    parser.add_argument('--policies', type=Path)
    parser.add_argument('--embedding-profile', choices=PROFILES, default='qwen3-8b')
    parser.add_argument('--embedding-model', type=Path)
    parser.add_argument('--device', choices=['cpu','cuda'], default='cuda')
    parser.add_argument('--model', type=Path, default=verifier.gate.MODEL)
    parser.add_argument('--image-root', type=Path, default=ROOT)
    parser.add_argument('--minutes', type=int, default=52)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == 'prepare':
        if args.nodes is None or args.policies is None:
            parser.error('prepare requires --nodes and --policies')
        result = prepare(out,args.nodes,args.policies,args.embedding_profile,args.embedding_model)
    elif args.stage == 'embed': result = embed(out,args.device)
    elif args.stage == 'retrieve': result = retrieve(out)
    elif args.stage == 'prepare-verifier': result = prepare_verifier(out,args.model)
    elif args.stage == 'verify': result = run_verifier(out,args.model,args.image_root,args.minutes)
    elif args.stage == 'export': result = export(out)
    else: result = check(out)
    import json
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
