"""Cache-only shadow repairs: eligible views, unique escape and explicit references.

Selection never reads development labels. Original node IDs and source offsets
are preserved. An explicit reference produces a candidate, not a semantic edge.
"""
from collections import Counter, defaultdict
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

import numpy as np

import compare_node_dedup_edge_retrieval as dedup
import run_hierarchical_edge_retrieval as hierarchy
from compare_previous_edge_schemes import coverage
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha

BASE = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
LINE = ROOT / 'EvidenceNet/output/line_aware_edge_retrieval_v1_20261017'
OUT = ROOT / 'EvidenceNet/output/edge_candidate_allocation_repair_v2_20261017'
BUDGET = 1301
POINTER = re.compile(r'\b(?P<kind>fig(?:ure)?|table)\.?\s*(?P<number>\d+(?:\.\d+)*)\b', re.I)


def key(pair):
    return tuple(sorted((pair['source'], pair['target'])))


def rank(items):
    return sorted(items, key=lambda p: (-p.get('retrieval_score', 0), *key(p)))


def allowed(policy, member_id, kind):
    return policy.get('eligible', False) and any(
        m['member_id'] == member_id and m['kind'] == kind and m['eligible']
        for m in policy['members'])


def eligible_views(views, policies):
    result, indices = [], []
    for index, v in enumerate(views):
        if not allowed(policies[v['node_id']], v['member_id'], v['member_kind']):
            continue
        v = deepcopy(v)
        if v['member_kind'] == 'visual':
            v['source_status'] = 'GENERATED_DESCRIPTION_FOR_RETRIEVAL_ONLY'
        result.append(v)
        indices.append(index)
    return result, indices


def unique_escape(pool, native, budget=BUDGET, escape_budget=96):
    primary = [p for p in rank(native) if set(p['selection_routes']) & {'article_routed', 'intra_article'}]
    primary_keys = {key(p) for p in primary}
    escape, degree = [], Counter()
    for p in rank(pool):
        a, b = key(p)
        if p['source_article'] == p['target_article'] or (a, b) in primary_keys:
            continue
        if degree[a] >= 6 or degree[b] >= 6:
            continue
        escape.append({**p, 'selection_routes': ['unique_global_escape']})
        degree[a] += 1
        degree[b] += 1
        if len(escape) == min(escape_budget, budget):
            break
    selected = primary[:budget - len(escape)] + escape
    seen = {key(p) for p in selected}
    for p in rank(native):
        if len(selected) == budget:
            break
        if key(p) not in seen:
            selected.append(p)
            seen.add(key(p))
    return selected


def references(nodes, policies):
    """Only original captions give figure/table identity; document+article scoped."""
    captions, original = defaultdict(dict), []
    for node in nodes.values():
        if not node.get('article_id') or 'UNRESOLVED_PAGE_BUCKET' in node['article_id']:
            continue
        for m in node['members']:
            if m['kind'] != 'atom' or not allowed(policies[node['id']], m['id'], m['kind']):
                continue
            text = m.get('text', '')
            original.append((node, m))
            if m.get('type') != 'caption' and m.get('role') != 'cap':
                continue
            match = POINTER.match(text.lstrip())
            if match:
                kind = 'figure' if match['kind'].lower().startswith('fig') else 'table'
                k = (node['document'], node['article_id'], kind, match['number'])
                captions[k][node['id']] = m
    result = {}
    for node, m in original:
        if m.get('type') == 'caption' or m.get('role') == 'cap':
            continue
        for match in POINTER.finditer(m.get('text', '')):
            kind = 'figure' if match['kind'].lower().startswith('fig') else 'table'
            k = (node['document'], node['article_id'], kind, match['number'])
            targets = captions.get(k, {})
            if len(targets) != 1:
                continue
            target, caption = next(iter(targets.items()))
            if target == node['id']:
                continue
            a, b = sorted((node['id'], target))
            p = result.setdefault((a, b), dict(source=a, target=b,
                source_article=node['article_id'], target_article=node['article_id'],
                selection_routes=['explicit_reference_candidate'], reference_anchors=[]))
            p['reference_anchors'].append(dict(referring_node=node['id'], target_node=target,
                member_id=m['id'], char_start=match.start(), char_end=match.end(), quote=match.group(),
                target_caption_member=caption['id'], target_caption=caption['text'],
                reference_kind=kind, number=match['number']))
    return sorted(result.values(), key=lambda p: (p['source_article'], *key(p)))


def reserve_references(current, refs, budget=BUDGET, reference_budget=96):
    # Round-robin articles prevents one long article from consuming the lane.
    buckets = defaultdict(list)
    for p in refs:
        buckets[p['source_article']].append(p)
    protected = []
    for offset in range(max((len(v) for v in buckets.values()), default=0)):
        for article in sorted(buckets):
            if offset < len(buckets[article]) and len(protected) < min(reference_budget, budget):
                protected.append(buckets[article][offset])
    seen = {key(p) for p in protected}
    # Preserve escape slots too; otherwise filling from primary+escape would
    # silently truncate the escape tail whenever reference candidates are new.
    for p in current:
        if len(protected) == budget:
            break
        if 'unique_global_escape' in p['selection_routes'] and key(p) not in seen:
            protected.append(p)
            seen.add(key(p))
    for p in current:
        if len(protected) == budget:
            break
        if key(p) not in seen:
            protected.append(p)
            seen.add(key(p))
    return protected


def prepare(out):
    if out.exists():
        raise ValueError('fresh_output_required')
    out.mkdir(parents=True)
    policies = read(BASE / 'corpus_policies.json')
    views = rows(BASE / 'views.jsonl') + rows(LINE / 'line_views.jsonl')
    cleaned, indices = eligible_views(views, policies)
    jsonl(out / 'views.jsonl', cleaned)
    write(out / 'vector_indices.json', indices)
    write(out / 'protocol.json', dict(
        views_before=len(views), views_after=len(cleaned), removed_views=len(views)-len(cleaned),
        candidate_budget=BUDGET, escape_budget=96, reference_budget=96,
        design='Sequential controls: frozen line; eligible-only replay; unique-new escape; protected original-caption reference lane.',
        reference_policy='Original eligible prose points to unique original caption identity in the same known article/document. Whole figure target retained even for subfigure pointers; no panel inference.',
        generated_descriptions='retrieval only; never original reference anchors',
        labels_used_for_selection=False, qwen_calls=0, new_embeddings=0,
        caveat='Development regression diagnosis; not held-out quality and not semantic edge export. Frozen original experiment remains unchanged.'))
    files = [Path(__file__), Path(dedup.__file__), Path(hierarchy.__file__),
             Path(hierarchy.__file__).with_name('compare_previous_edge_schemes.py'),
             Path(hierarchy.__file__).with_name('run_node_context_edges.py'),
             BASE / 'evaluation/cases.jsonl',
             BASE / 'corpus_nodes.jsonl', BASE / 'corpus_policies.json', BASE / 'views.jsonl', BASE / 'view_vectors.npy',
             LINE / 'line_views.jsonl', LINE / 'line_vectors.npy', LINE / 'node_candidates.jsonl',
             out / 'views.jsonl', out / 'vector_indices.json', out / 'protocol.json']
    write(out / 'manifest.json', {str(p): sha(p) for p in files})
    print(json.dumps(read(out / 'protocol.json')), flush=True)


def run(out):
    for path, digest in read(out / 'manifest.json').items():
        if sha(path) != digest:
            raise ValueError('changed frozen input: ' + path)
    nodes = {n['id']: n for n in rows(BASE / 'corpus_nodes.jsonl')}
    views = rows(out / 'views.jsonl')
    vectors = np.concatenate([np.load(BASE / 'view_vectors.npy'), np.load(LINE / 'line_vectors.npy')])
    vectors = vectors[read(out / 'vector_indices.json')]
    assert len(vectors) == len(views)
    if (out / 'initial_pool.jsonl').exists():
        if sha(out / 'initial_pool.jsonl') != read(out / 'pool_checkpoint.json')['sha256']:
            raise ValueError('pool checkpoint changed')
        pool = {key(p): p for p in rows(out / 'initial_pool.jsonl')}
    else:
        pool = dedup.retrieve(views, vectors)
        jsonl(out / 'initial_pool.jsonl', pool.values())
        write(out / 'pool_checkpoint.json', {'sha256': sha(out / 'initial_pool.jsonl')})
    articles, native = hierarchy.route_and_select(nodes, pool)
    jsonl(out / 'article_candidates.jsonl', articles)
    jsonl(out / 'native_candidates.jsonl', native)
    escape = unique_escape(list(pool.values()), native)
    refs = references(nodes, read(BASE / 'corpus_policies.json'))
    jsonl(out / 'reference_candidates.jsonl', refs)
    arms = {'frozen_line': rows(LINE / 'node_candidates.jsonl')[:BUDGET],
            'eligible_only': native[:BUDGET], 'unique_escape': escape,
            'protected_references': reserve_references(escape, refs)}
    for name, pairs in arms.items():
        assert len(pairs) == len({key(p) for p in pairs}) == BUDGET, name
        jsonl(out / (name + '_candidates.jsonl'), pairs)
    write(out / 'selection_manifest.json', {name: sha(out / (name + '_candidates.jsonl')) for name in arms})
    # Candidate lists are frozen before opening development labels.
    cases = rows(BASE / 'evaluation/cases.jsonl')
    results, details = {}, {}
    for name, pairs in arms.items():
        results[name], details[name] = coverage(cases, pairs)
    write(out / 'summary.json', dict(complete=True, initial_pairs=len(pool),
        reference_candidates=len(refs), native_pairs=len(native), budget=BUDGET, results=results,
        escape_pairs_preserved_in_reference_arm=sum('unique_global_escape' in p['selection_routes']
            or key(p) in {key(q) for q in escape if 'unique_global_escape' in q['selection_routes']}
            for p in arms['protected_references']),
        interpretation='Candidate inclusion only; reference lane does not establish semantic relation. Development set, labels read after selection.'))
    write(out / 'case_coverage.json', details)
    print(json.dumps(read(out / 'summary.json')), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.stage](args.output.resolve())
