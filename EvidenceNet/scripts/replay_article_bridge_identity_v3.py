#!/usr/bin/env python3
"""Controlled CPU replay: original-source identity gate, then intra-article publication.

This gate is necessary provenance evidence, not sufficient semantic verification.
No model calls or candidate ranking changes; v2 results remain immutable.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations
from pathlib import Path
import re
import shutil

import run_article_bridge_binding_v2 as v2
from run_node_context_edges import ROOT, read, rows, write, jsonl, sha

DEFAULT = ROOT / 'EvidenceNet/output/article_bridge_identity_v3_20261012'


def name_span(text, names):
    for name in sorted(names, key=lambda n: (-len(n), n)):
        pattern = r'(?<!\w)' + r'\s+'.join(re.escape(w) for w in name.split()) + r'(?!\w)'
        match = re.search(pattern, text, re.I) if name.strip() else None
        if match:
            return {'quote': match.group(), 'start': match.start(), 'end': match.end()}
    return None


def original_anchor(anchor, nodes, mapping, owner):
    if anchor.get('kind') != 'TEXT' or anchor.get('node_id') != owner or anchor.get('article_id') != mapping[owner]:
        return False
    member = next((m for m in nodes[owner]['members'] if m['kind'] == 'atom' and m['id'] == anchor['member_id']), None)
    return member is not None and member.get('text', '')[anchor['char_start']:anchor['char_end']] == anchor['quote']


def identity_gate(binding, subject, nodes, mapping):
    result = deepcopy(binding)
    result['model_status'] = binding['status']
    proofs = []
    if binding['status'] == 'SUPPORTED':
        nid = binding['node_id']
        for anchor in binding['original_local_catalog']:
            if original_anchor(anchor, nodes, mapping, nid):
                span = name_span(anchor['quote'], subject['source_spellings'])
                if span:
                    proofs.append({'kind': 'LOCAL_LITERAL', 'anchor': anchor, 'identity_span': span})
        for ctx in binding['decision']['context_sources']:
            source = ctx['source_node']; ref = ctx['reference']; anchor = ctx['anchor']
            if ctx['target_node'] != nid or mapping[source] != mapping[nid] or ref['source'] != source or ref['target'] != nid:
                continue
            if not original_anchor(anchor, nodes, mapping, source):
                continue
            members = {m['id']: m for m in nodes[source]['members'] if m['kind'] == 'atom'}
            targets = {m['id']: m for m in nodes[nid]['members'] if m['kind'] == 'atom'}
            text = members.get(ref['source_member'], {}).get('text', '')
            if text[ref['source_start']:ref['source_end']] != ref['source_quote']:
                continue
            if targets.get(ref['target_member'], {}).get('text') != ref['target_quote']:
                continue
            # Frozen v1 verifies the unique figure/table marker. Keep that chain,
            # while rechecking ownership and exact source/target text here.
            if ref.get('verification') != 'unique marker within confirmed article identity':
                continue
            span = name_span(anchor['quote'], subject['source_spellings'])
            if span:
                proofs.append({'kind': 'EXPLICIT_REFERENCE', 'context': ctx, 'identity_span': span})
        if not proofs:
            result['status'] = 'UNRESOLVED'
            result['decision']['status'] = 'UNRESOLVED'
    result['identity_gate'] = {'status': 'SOURCE_IDENTITY_FOUND' if proofs else
        'IDENTITY_UNRESOLVED' if binding['status'] == 'SUPPORTED' else 'NOT_APPLICABLE',
        'proofs': proofs, 'scope': 'necessary provenance check; model semantic decision remains separately auditable'}
    return result


def publish_intra(bindings):
    groups = defaultdict(set)
    for b in bindings:
        if v2.graph_binding(b):
            groups[b['article_id'], b['subject_id']].add(b['node_id'])
    pairs = {pair for ids in groups.values() for pair in combinations(sorted(ids), 2)}
    return [v2.derive_pair({'pair_id': 'V3_INTRA_' + v2.digest([a, b])[:12],
        'source': a, 'target': b, 'scope': 'intra_article',
        'route': 'shared_verified_subject', 'budget': 'separate from cross-article top-8'}, bindings)
        for a, b in sorted(pairs)]


def replay(out, source=v2.DEFAULT):
    if out.exists():
        raise ValueError('fresh_output_required')
    v2.checked(source)
    for name, fingerprint in read(source / 'result_sha256.json').items():
        if sha(source / name) != fingerprint:
            raise ValueError('changed_v2_result:' + name)
    out.mkdir(parents=True)
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, out / path.name)
    (out / 'assets').symlink_to((source / 'assets').resolve(), target_is_directory=True)
    manifest = read(out / 'manifest.json')
    manifest.update(experiment='article_bridge_identity_v3_cpu_replay', source_experiment=str(source),
                    changes=['source_identity_gate', 'publish_same_article_subject_edges'],
                    new_model_calls=0)
    manifest['code_sha256'][str(Path(__file__).resolve())] = sha(__file__)
    write(out / 'manifest.json', manifest)
    (out / 'code').mkdir()
    for path in manifest['code_sha256']:
        shutil.copy2(path, out / 'code' / Path(path).name)
    nodes = {n['id']: n for n in rows(out / 'units.jsonl')}
    mapping = read(out / 'unit_article_map.json')
    subjects = {s['subject_id']: s for s in rows(out / 'canonical_subjects.jsonl')}
    original = rows(source / 'node_subject_bindings.jsonl')
    bindings = [identity_gate(b, subjects[b['subject_id']], nodes, mapping) for b in original]
    jsonl(out / 'node_subject_bindings.jsonl', bindings)
    # Keep ranking fixed: this experiment isolates gate and publication effects.
    candidates = [p for p in rows(out / 'node_candidates.jsonl') if 'article_first' in p['arms']]
    cross = [v2.derive_pair(p, bindings) for p in candidates]
    cross = [e for e in cross if e['paths']]
    intra = publish_intra(bindings)
    jsonl(out / 'cross_article_semantic_edges.jsonl', cross)
    jsonl(out / 'intra_article_semantic_edges.jsonl', intra)
    jsonl(out / 'semantic_edges.jsonl', cross + intra)
    jsonl(out / 'article_navigation_edges.jsonl', v2.navigation(bindings))
    edge_keys = {frozenset((e['source'], e['target'])) for e in cross + intra}
    dev = [{**v2.derive_pair(p, bindings), 'published': frozenset((p['source'], p['target'])) in edge_keys}
           for p in rows(out / 'development_pairs.jsonl')]
    jsonl(out / 'development_decisions.jsonl', dev)
    jsonl(out / 'fresh_review_queue.jsonl', [v2.derive_pair(p, bindings) for p in rows(source / 'fresh_review_queue.jsonl')])
    v2.report(out)
    summary = {'experiment': manifest['experiment'], 'new_model_calls': 0,
        'binding_statuses': dict(Counter(b['status'] for b in bindings)),
        'changed_bindings': [{'node_id': b['node_id'], 'before': b['model_status'], 'after': b['status']} for b in bindings if b['model_status'] != b['status']],
        'cross_edges_before': len(rows(source / 'semantic_edges.jsonl')), 'cross_edges_after': len(cross),
        'intra_edges': len(intra), 'development_published': sum(d['published'] for d in dev),
        'development_derivable': sum(bool(d['paths']) for d in dev),
        'remaining_unpublished': [d['pair_id'] for d in dev if d['paths'] and not d['published']],
        'retrieval_gain': 'NOT_EVALUATED',
        'limitations': ['frozen model replay, not independent evaluation', 'literal identity alone does not prove substantive content',
                       'cross-article ranking unchanged; known routing losses remain',
                       'intra-article same-subject pairs may be dense; no retrieval utility claim']}
    write(out / 'replay_summary.json', summary)
    (out / 'REPORT.md').write_text('# V3 identity gate CPU replay\n\n```json\n' + __import__('json').dumps(summary, indent=2) + '\n```\n')
    write(out / 'result_sha256.json', {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name not in {'result_sha256.json', 'jobs.json'}})
    print(__import__('json').dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    args = parser.parse_args()
    replay(args.output.resolve())
