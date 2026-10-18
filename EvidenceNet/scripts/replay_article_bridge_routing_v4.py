#!/usr/bin/env python3
"""CPU routing comparison on frozen v3 bindings; no labels enter selection."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json

import run_article_bridge_binding_v2 as v2
from replay_article_bridge_identity_v3 import DEFAULT as SOURCE
from run_node_context_edges import ROOT, read, rows, write, jsonl, sha

DEFAULT = ROOT / 'EvidenceNet/output/article_bridge_routing_v4_20261012'


def select(rankings, mapping, bindings, protected=4, expansion=4):
    """Round-robin articles by dense rank, without fixed aspect preferences.

    Protected global slots remain intact; expansion only consumes NEW targets.
    Missing subject candidates fall back to the original global ranking.
    """
    subjects = defaultdict(set)
    for b in bindings:
        if v2.graph_binding(b):
            subjects[b['node_id']].add(b['subject_id'])
    result = []
    for nid, ranking in sorted(rankings.items()):
        ranked = [n for n in ranking if n != nid and mapping[n] != mapping[nid]]
        selected = ranked[:protected]
        pools = defaultdict(list)
        for n in ranked:
            if n not in selected and subjects[nid] & subjects[n]:
                pools[mapping[n]].append(n)
        # Insertion order is the rank of each article's best remaining node.
        guided = []
        while pools and len(guided) < expansion:
            for article in list(pools):
                guided.append(pools[article].pop(0))
                if not pools[article]:
                    del pools[article]
                if len(guided) == expansion:
                    break
        selected += guided
        limit = min(protected + expansion, len(ranked))
        for n in ranked:
            if len(selected) >= limit:
                break
            if n not in selected:
                selected.append(n)
        result.append({'source': nid, 'targets': selected, 'guided_new_targets': guided})
    return result


def pairs(routes):
    return {tuple(sorted((r['source'], n))) for r in routes for n in r['targets']}


def replay(out):
    if out.exists():
        raise ValueError('fresh_output_required')
    v2.checked(SOURCE)
    hashes = read(SOURCE / 'result_sha256.json')
    for name, fingerprint in hashes.items():
        if sha(SOURCE / name) != fingerprint:
            raise ValueError('changed_source:' + name)
    nodes = {n['id']: n for n in rows(SOURCE / 'units.jsonl')}
    policies = read(SOURCE / 'eligibility.json'); mapping = read(SOURCE / 'unit_article_map.json')
    bindings = rows(SOURCE / 'node_subject_bindings.jsonl')
    rankings = v2.full_rankings(nodes, policies)
    old = rows(SOURCE / 'routes_article_first.jsonl')
    global8 = rows(SOURCE / 'routes_global.jsonl')
    for r in global8:
        assert r['targets'] == [n for n in rankings[r['source']] if n != r['source'] and mapping[n] != mapping[r['source']]][:8]
    arms = {'global8': global8, 'v3_article8': old,
            'round_robin8': select(rankings, mapping, bindings, 4, 4),
            'global12': [{'source': n, 'targets': [t for t in ranking if t != n and mapping[t] != mapping[n]][:12]}
                         for n, ranking in sorted(rankings.items())],
            'protected8_plus4': select(rankings, mapping, bindings, 8, 4)}
    out.mkdir(parents=True)
    manifest = {'source': str(SOURCE), 'source_results_sha256': hashes,
        'runtime_sha256': {**read(SOURCE / 'manifest.json')['code_sha256'], str(Path(__file__).resolve()): sha(__file__)},
        'selection_inputs': ['frozen content bindings', 'article mapping', 'original dense/lexical rankings'],
        'development_labels_used_for_routing': False, 'new_model_calls': 0}
    write(out / 'manifest.json', manifest)
    dev = rows(SOURCE / 'development_decisions.jsonl')
    intra = {tuple(sorted((e['source'], e['target']))) for e in rows(SOURCE / 'intra_article_semantic_edges.jsonl')}
    old_keys = pairs(old); baseline_keys = pairs(global8)
    old_edges = {tuple(sorted((e['source'], e['target']))) for e in rows(SOURCE / 'cross_article_semantic_edges.jsonl')}
    summary = {}
    for name, routes in arms.items():
        keys = pairs(routes)
        derived = [v2.derive_pair({'pair_id': 'V4_' + v2.digest(key)[:12], 'source': key[0], 'target': key[1]}, bindings) for key in sorted(keys)]
        edges = [e for e in derived if e['paths']]
        edge_keys = {tuple(sorted((e['source'], e['target']))) for e in edges}
        reviews = [{**d, 'published': tuple(sorted((d['source'], d['target']))) in edge_keys | intra} for d in dev]
        jsonl(out / ('routes_' + name + '.jsonl'), routes)
        jsonl(out / ('edges_' + name + '.jsonl'), edges)
        jsonl(out / ('development_' + name + '.jsonl'), reviews)
        jsonl(out / ('deltas_' + name + '.jsonl'), [{'source': a, 'target': b, 'change': 'added' if (a,b) in keys else 'removed'} for a,b in sorted(keys ^ old_keys)])
        missing = [d['pair_id'] for d in reviews if d['paths'] and not d['published']]
        targets = Counter(n for r in routes for n in r.get('guided_new_targets', []))
        summary[name] = {'directed_budget': max(len(r['targets']) for r in routes), 'candidate_pairs': len(keys),
            'added_vs_v3': len(keys - old_keys), 'removed_vs_v3': len(old_keys - keys),
            'global8_candidates_lost': len(baseline_keys - keys),
            'derived_cross_edges': len(edges), 'v3_derived_edges_lost': len(old_edges - edge_keys),
            'development_published': sum(d['published'] for d in reviews), 'derivable_development_missing': missing,
            'most_frequent_guided_targets': targets.most_common(5)}
    result = {'arms': summary, 'new_model_calls': 0, 'retrieval_gain': 'NOT_EVALUATED',
        'limitations': ['development cases are not an independent test set',
        'derived edge count is not precision; identity gate remains necessary, not sufficient',
        '12-target arms cost 50% more directed candidates than 8-target arms',
        'intra-article edges and known density concern unchanged',
        'no automatic adoption or frozen baseline changes']}
    write(out / 'summary.json', result)
    (out / 'REPORT.md').write_text('# Routing v4 CPU replay\n\n```json\n' + json.dumps(result, indent=2) + '\n```\n')
    write(out / 'result_sha256.json', {p.name: sha(p) for p in out.iterdir() if p.is_file()})
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    replay(parser.parse_args().output.resolve())
