"""Typed, source-grounded candidate lanes for three remaining failure modes.

This is a cache-only development replay. Candidate membership is not an edge.
Evaluation labels are opened only after every fixed-budget arm is frozen.
"""
from collections import defaultdict
import argparse
import json
from pathlib import Path
import re

from compare_previous_edge_schemes import coverage
from run_node_context_edges import ROOT, jsonl, read, rows, sha, write

BASE = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
SOURCE = ROOT / 'EvidenceNet/output/edge_candidate_allocation_repair_v2_20261017'
OUT = ROOT / 'EvidenceNet/output/remaining_edge_candidate_repair_v2_20261018'
BUDGET = 1301
GENERIC_ACRONYMS = {'AI', 'ML', 'DL', 'CNN', 'RNN', 'GNN', 'GCN', 'GPU', 'CPU', 'PDF'}
ACRONYM = re.compile(r'\b[A-Z][A-Z0-9-]{2,14}\b')
CITATION_BINDING = re.compile(r'\b(?P<alias>[A-Z][A-Z0-9-]{2,14})\s*\[(?P<number>\d+)\]')
NUMERIC_CITATION = re.compile(r'\[(?P<number>\d+)\]')


def pair_key(row):
    return tuple(sorted((row['source'], row['target'])))


def article_key(row, nodes):
    return tuple(sorted((nodes[row['source']]['article_id'], nodes[row['target']]['article_id'])))


def citation_entities(nodes):
    """Resolve article-local ``ACRONYM [n]`` aliases without external knowledge."""
    bindings = defaultdict(lambda: defaultdict(list))
    for node in nodes.values():
        for match in CITATION_BINDING.finditer(node.get('text', '')):
            alias = match['alias']
            if alias in GENERIC_ACRONYMS:
                continue
            bindings[node['article_id']][match['number']].append({
                'alias': alias, 'source_node': node['id'],
                'char_start': match.start('alias'), 'char_end': match.end('alias'),
                'quote': match.group(),
            })
    entities, provenance = {}, {}
    for node in nodes.values():
        direct = set(ACRONYM.findall(node.get('text', ''))) - GENERIC_ACRONYMS
        resolved = defaultdict(list)
        for match in NUMERIC_CITATION.finditer(node.get('text', '')):
            for record in bindings[node['article_id']].get(match['number'], []):
                resolved[record['alias']].append({**record,
                    'citation_node': node['id'], 'citation_number': match['number'],
                    'citation_char_start': match.start(), 'citation_char_end': match.end(),
                    'citation_quote': match.group()})
        entities[node['id']] = direct | set(resolved)
        provenance[node['id']] = dict(resolved)
    return entities, provenance


def resolved_entity_lane(pool, nodes, selected_articles, entities, provenance, per_endpoint=4):
    """Top local pairs per endpoint after article routing and citation resolution."""
    eligible = []
    for pair in pool:
        if pair['source'] == pair['target'] or article_key(pair, nodes) not in selected_articles:
            continue
        if nodes[pair['source']]['article_id'] == nodes[pair['target']]['article_id']:
            continue
        shared = sorted(entities[pair['source']] & entities[pair['target']])
        if not shared:
            continue
        item = {**pair, 'selection_routes': ['resolved_entity_local_candidate'],
                'shared_resolved_entities': shared,
                'citation_resolution': {side: {name: provenance[pair[side]].get(name, []) for name in shared}
                                        for side in ('source', 'target')}}
        eligible.append(item)
    by_endpoint = defaultdict(list)
    for pair in eligible:
        by_endpoint[pair['source']].append(pair)
        by_endpoint[pair['target']].append(pair)
    selected = {}
    for endpoint in sorted(by_endpoint):
        ranked = sorted(by_endpoint[endpoint],
                        key=lambda p: (-p['retrieval_score'], p['source'], p['target']))
        for pair in ranked[:per_endpoint]:
            selected[pair_key(pair)] = pair
    return [selected[key] for key in sorted(selected)]


def page_groups(nodes, policies):
    grouped = defaultdict(list)
    for node in nodes.values():
        article = node.get('article_id')
        if not article or 'UNRESOLVED_PAGE_BUCKET' in article or not policies[node['id']]['eligible']:
            continue
        if node.get('min_order') is None:
            continue
        grouped[(node['document'], article, str(node['page']))].append(node)
    return grouped


def reference_context_lane(reference_pairs, nodes, policies, previous_orders=6):
    """Expand an explicit pointer to bounded preceding source nodes on the same page."""
    grouped = page_groups(nodes, policies)
    selected = {}
    for pair in reference_pairs:
        for anchor in pair['reference_anchors']:
            referring = nodes[anchor['referring_node']]
            order = referring.get('min_order')
            if order is None:
                continue
            group = grouped[(referring['document'], referring['article_id'], str(referring['page']))]
            for node in group:
                candidate_order = node.get('min_order')
                if candidate_order is None or not 0 < order - candidate_order <= previous_orders:
                    continue
                if node['id'] in {anchor['referring_node'], anchor['target_node']}:
                    continue
                a, b = sorted((node['id'], anchor['target_node']))
                record = selected.setdefault((a, b), {
                    'source': a, 'target': b,
                    'source_article': nodes[a]['article_id'], 'target_article': nodes[b]['article_id'],
                    'selection_routes': ['reference_context_candidate'], 'context_anchors': []})
                record['context_anchors'].append({
                    'context_node': node['id'], 'referring_node': anchor['referring_node'],
                    'target_node': anchor['target_node'], 'reference_kind': anchor['reference_kind'],
                    'number': anchor['number'], 'pointer_quote': anchor['quote'],
                    'pointer_member_id': anchor['member_id'],
                    'order_distance': order - candidate_order,
                })
    return [selected[key] for key in sorted(selected)]


def vertical_gap(a, b):
    if a[3] < b[1]:
        return b[1] - a[3]
    if b[3] < a[1]:
        return a[1] - b[3]
    return 0


def x_overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) / max(1, min(a[2]-a[0], b[2]-b[0]))


def contiguous_reading_lane(nodes, policies):
    """Same-column touching neighbors; useful for split explanations such as P24."""
    selected = {}
    for _, group in sorted(page_groups(nodes, policies).items()):
        ordered = sorted((n for n in group if n.get('bbox')),
                         key=lambda n: (n['min_order'], n['id']))
        for left, right in zip(ordered, ordered[1:]):
            if right['min_order'] - left['min_order'] > 2:
                continue
            if x_overlap(left['bbox'], right['bbox']) < .5 or vertical_gap(left['bbox'], right['bbox']) != 0:
                continue
            a, b = sorted((left['id'], right['id']))
            selected[(a, b)] = {
                'source': a, 'target': b,
                'source_article': left['article_id'], 'target_article': right['article_id'],
                'selection_routes': ['contiguous_reading_candidate'],
                'reading_anchor': {'first_node': left['id'], 'second_node': right['id'],
                                   'order_distance': right['min_order']-left['min_order'],
                                   'x_overlap': x_overlap(left['bbox'], right['bbox']),
                                   'vertical_gap': vertical_gap(left['bbox'], right['bbox'])}}
    return [selected[key] for key in sorted(selected)]


def fixed_budget(lanes, fallback, budget=BUDGET):
    result, seen = [], set()
    for lane in lanes + [fallback]:
        for pair in lane:
            key = pair_key(pair)
            if key in seen:
                continue
            result.append(pair); seen.add(key)
            if len(result) == budget:
                return result
    raise ValueError(f'Only {len(result)} unique candidates for budget {budget}')


def run(out):
    if out.exists():
        raise ValueError('fresh_output_required')
    out.mkdir(parents=True)
    nodes = {n['id']: n for n in rows(BASE/'corpus_nodes.jsonl')}
    policies = read(BASE/'corpus_policies.json')
    pool = rows(SOURCE/'initial_pool.jsonl')
    base = rows(SOURCE/'protected_references_candidates.jsonl')
    references = rows(SOURCE/'reference_candidates.jsonl')
    articles = rows(SOURCE/'article_candidates.jsonl')
    selected_articles = {tuple(sorted((a['source_article'], a['target_article'])))
                         for a in articles if a['selected_for_node_search']}
    entities, provenance = citation_entities(nodes)
    entity_lane = resolved_entity_lane(pool, nodes, selected_articles, entities, provenance)
    context_lane = reference_context_lane(references, nodes, policies)
    reading_lane = contiguous_reading_lane(nodes, policies)
    jsonl(out/'resolved_entity_candidates.jsonl', entity_lane)
    jsonl(out/'reference_context_candidates.jsonl', context_lane)
    jsonl(out/'contiguous_reading_candidates.jsonl', reading_lane)
    arms = {
        'v2_control': base,
        'resolved_entity': fixed_budget([entity_lane], base),
        'entity_plus_reference_context': fixed_budget([context_lane, entity_lane], base),
        'all_three_lanes': fixed_budget([reading_lane, context_lane, entity_lane], base),
    }
    for name, candidates in arms.items():
        if len(candidates) != BUDGET or len({pair_key(p) for p in candidates}) != BUDGET:
            raise ValueError('fixed budget/uniqueness failed: '+name)
        jsonl(out/(name+'_candidates.jsonl'), candidates)
    # Freeze candidates before labels are opened for reporting.
    write(out/'selection_manifest.json', {name: sha(out/(name+'_candidates.jsonl')) for name in arms})
    cases = rows(BASE/'evaluation/cases.jsonl')
    results, details = {}, {}
    for name, candidates in arms.items():
        results[name], details[name] = coverage(cases, candidates)
    write(out/'case_coverage.json', details)
    write(out/'summary.json', {
        'complete': True, 'budget': BUDGET,
        'lane_sizes': {'resolved_entity': len(entity_lane), 'reference_context': len(context_lane),
                       'contiguous_reading': len(reading_lane)},
        'results': results,
        'interpretation': 'Candidate coverage only. No semantic edge was accepted; labels opened after fixed candidate files.',
        'development_warning': 'The lane policies were designed after inspecting P08/P23/P24 and require held-out evaluation.',
    })
    files = [Path(__file__), Path(__file__).with_name('compare_previous_edge_schemes.py'),
             Path(__file__).with_name('run_node_context_edges.py'),
             Path(__file__).with_name('repair_edge_candidate_allocation.py'),
             BASE/'corpus_nodes.jsonl', BASE/'corpus_policies.json',
             BASE/'evaluation/cases.jsonl', SOURCE/'initial_pool.jsonl',
             SOURCE/'protected_references_candidates.jsonl', SOURCE/'reference_candidates.jsonl',
             SOURCE/'article_candidates.jsonl', out/'selection_manifest.json']
    write(out/'manifest.json', {str(path): sha(path) for path in files})
    print(json.dumps(read(out/'summary.json'), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['run'])
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    run(args.output.resolve())
