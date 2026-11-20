#!/usr/bin/env python3
"""Compare bounded evidence retrieval with article-gated retrieval, shadow only.

This diagnostic reuses the historical ANN pilot snapshot. Its paper units are
sections, not atomic EvidenceNodes; exported pairs must not become graph edges.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path

import faiss
import numpy as np
import torch

from run_ann_candidate_pilot import ROOT, normalize, read_rows, search_filtered, write_json, write_rows


def diversify(hits, owners, budget, per_article=2):
    selected, counts = [], Counter()
    for j, score in hits:
        if counts[owners[j]] >= per_article:
            continue
        selected.append((j, score))
        counts[owners[j]] += 1
        if len(selected) == budget:
            break
    return selected


def canonical_pairs(directed):
    return {tuple(sorted((i, j))) for i, j in directed if i != j}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', type=Path, default=ROOT / 'EdgeGeneration/output/ann_candidate_real_v3')
    ap.add_argument('--vectors', type=Path, default=ROOT / 'EdgeGeneration/output/typed_anchor_multimag_pilot_v1/all_bge_m3_vectors_cpu.pt')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--export-method', default='diverse_top10', help='Exploratory candidate view; not a production policy')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    faiss.omp_set_num_threads(1)
    torch.set_num_threads(1)
    units = read_rows(args.snapshot / 'index_units.jsonl')
    owners = [r['article_id'] for r in units]
    v = normalize(torch.load(args.vectors, map_location='cpu', weights_only=True).numpy())
    snapshot_summary = json.loads((args.snapshot / 'summary.json').read_text())
    expected = [h for path, h in snapshot_summary['input_sha256'].items() if path.endswith('all_bge_m3_vectors_cpu.pt')]
    if expected != [hashlib.sha256(args.vectors.read_bytes()).hexdigest()] or len(v) != len(units):
        raise ValueError('Vector cache does not match snapshot provenance')
    index = faiss.read_index(str(args.snapshot / 'evidence.hnsw'))
    if index.ntotal != len(units):
        raise ValueError('Index size mismatch')
    direct = search_filtered(index, v, owners, owners, 64)
    article_candidates = defaultdict(set)
    for row in read_rows(args.snapshot / 'union_candidates.jsonl'):
        if row['per_route_depth'] == 3:
            article_candidates[row['source_article']].add(row['target_article'])
    members = defaultdict(list)
    for i, a in enumerate(owners):
        members[a].append(i)
    # For each evidence query, recover evidence inside at most nine article
    # candidates. Per-article top two prevents one target article dominating.
    routed = []
    for i, a in enumerate(owners):
        hits = []
        for target in sorted(article_candidates[a]):
            ids = members[target]
            scores = v[ids] @ v[i]
            for local in np.argsort(-scores)[:2]:
                hits.append((ids[local], float(scores[local])))
        routed.append(sorted(hits, key=lambda x: (-x[1], x[0])))
    variants = {}
    for k in (5, 10, 20):
        variants[f'global_top{k}'] = {(i, j) for i, hits in enumerate(direct) for j, _ in hits[:k]}
        variants[f'diverse_top{k}'] = {(i, j) for i, hits in enumerate(direct) for j, _ in diversify(hits, owners, k)}
    # Fixed lane budgets, never condition the bypass on article-level relevance.
    variants['article_route_top10'] = {(i, j) for i, hits in enumerate(routed) for j, _ in hits[:10]}
    bypass = {(i, j) for i, hits in enumerate(direct) for j, _ in hits[:5]}
    variants['bypass5_plus_route5'] = bypass | {(i, j) for i, hits in enumerate(routed) for j, _ in hits[:5]}
    variants['bypass10_plus_route10'] = variants['global_top10'] | variants['article_route_top10']
    # Reverse retrieval contributes candidates, never determines edge direction.
    labels = json.loads((ROOT / 'EdgeGeneration/config/bge_open_set_neighbor_audit.json').read_text())['known_pair_audit']
    by_id = {r['unit_id']: i for i, r in enumerate(units)}
    metrics, audit = [], []
    possible = (len(units) ** 2 - sum(len(ids) ** 2 for ids in members.values())) // 2
    for name, directed in variants.items():
        pairs = canonical_pairs(directed)
        count = Counter()
        for label in labels:
            i, j = by_id[label['source']], by_id[label['target']]
            kept = tuple(sorted((i, j))) in pairs
            count[label['label']] += kept
            audit.append(dict(label, method=name, retained=kept, forward=(i, j) in directed, reverse=(j, i) in directed))
        metrics.append({'method': name, 'directed_queries_returned': len(directed), 'unique_evidence_pairs': len(pairs),
            'fraction_of_all_cross_article_pairs': len(pairs) / possible,
            'provisional_positive_pairs_retained': count['likely_related'], 'positive_total': 4,
            'provisional_negative_pairs_retained': count['likely_unrelated'], 'negative_total': 3})
    selected = args.export_method
    if selected not in variants:
        raise ValueError(f'Unknown export method: {selected}')
    directed = variants[selected]
    candidates = []
    for i, j in sorted(canonical_pairs(directed)):
        a, b = units[i], units[j]
        candidates.append({'candidate_id': hashlib.sha256(('\0'.join(sorted((a['unit_id'], b['unit_id'])))).encode()).hexdigest()[:24],
            'source_unit_id': a['unit_id'], 'target_unit_id': b['unit_id'],
            'source_article_id': owners[i], 'target_article_id': owners[j],
            'source_pages': a.get('page_ids', []), 'target_pages': b.get('page_ids', []),
            'source_member_node_ids': a.get('member_node_ids', []), 'target_member_node_ids': b.get('member_node_ids', []),
            'source_unit_kind': a['unit_kind'], 'target_unit_kind': b['unit_kind'],
            'source_text': a['text'], 'target_text': b['text'], 'cosine': float(v[i] @ v[j]),
            'retrieved_forward': (i,j) in directed, 'retrieved_reverse': (j,i) in directed,
            'in_global_top5': (i,j) in bypass or (j,i) in bypass,
            'edge_exists': None, 'relation_type': None, 'semantic_direction': None,
            'status': 'UNVERIFIED_RETRIEVAL_CANDIDATE',
            'requires_atomic_endpoint_resolution': len(a.get('member_node_ids', [])) != 1 or len(b.get('member_node_ids', [])) != 1})
    write_rows(args.output / 'evidence_candidates.jsonl', candidates)
    write_rows(args.output / 'known_pair_audit.jsonl', audit)
    summary = {'production_modified': False, 'units': len(units), 'all_cross_article_unit_pairs': possible,
        'metrics': metrics, 'exported_method': selected,
        'requires_atomic_endpoint_resolution': sum(r['requires_atomic_endpoint_resolution'] for r in candidates),
        'snapshot': str(args.snapshot), 'snapshot_cache_version': snapshot_summary['cache_version'],
        'limitations': ['Historical snapshot uses old CERN assignments and partial Qwen CLAD/DLR assignments.',
            'Paper targets are section/page retrieval units; no atomic evidence edge is asserted.',
            'Seven provisional labels do not measure corpus precision or general recall.',
            'No semantic verifier has run; reverse retrieval is not semantic direction.',
            'The fixed 64-hit pool and per-article caps may lose true neighbors.']}
    write_json(args.output / 'summary.json', summary)
    details = ''.join('<details><summary>' + html.escape(r['source_unit_id'] + ' ↔ ' + r['target_unit_id']) + '</summary><p>' + html.escape(r['source_text']) + '</p><p>' + html.escape(r['target_text']) + '</p></details>' for r in candidates if any(t in (r['source_text']+' '+r['target_text']).lower() for t in ['gravitational wave', 'gravitational-wave', 'ligo']))
    (args.output / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Cross-article evidence candidate audit</title><style>body{font:15px system-ui;max-width:1100px;margin:auto}pre{white-space:pre-wrap}details{padding:12px;border-bottom:1px solid #ccc}</style><h1>跨文章证据候选实验</h1><p>历史缓存诊断，未验证语义关系，论文端仍包含章节检索单元。</p><pre>' + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre><h2>引力波相关候选原文</h2>' + details)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
