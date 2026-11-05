#!/usr/bin/env python3
"""Blind, gold-free Query–Edge utility review over frozen Phase-1 route traces.

prepare: deterministically sample oriented query–edge routes and emit blinded
         evidence packages + an empty human-label template.
evaluate: compare original R1/R2 selection behavior on the *reviewed subset*.

This tool does not construct edges, run retrieval, load gold, or certify edges.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
PHASE1 = ROOT / 'EvidenceNet/output/query_edge_utilization_replay_v1_20261105'
NODES = ROOT / 'migration/vldocir-edge-20261022/results/nodes.jsonl'
NAV = ROOT / 'EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl'
UNIVERSE = ROOT / 'EvidenceNet/output/kg_link_prediction_pilot_v2_20261102/candidate_universe.jsonl'
OUT = ROOT / 'EvidenceNet/output/query_edge_utility_manual_review_v1_20261105'
ARMS = ('R1_static', 'R2_target_only', 'R2_anchor_proxy')
CHOICES = {
    'relation_validity': {'valid', 'invalid', 'uncertain'},
    'query_applicability': {'yes', 'no', 'uncertain'},
    'marginal_utility': {'yes', 'no', 'uncertain'},
    'opportunity_cost': {'prefer_target', 'prefer_dense', 'equivalent',
                         'not_applicable', 'uncertain'},
}
SELECTED = {'inspect', 'link_existing'}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def write_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')


def digest(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def short(text, limit: int = 900) -> str:
    value = str(text or '')
    return value if len(value) <= limit else value[:limit] + ' …[truncated]'


def member_preview(node: dict, limit: int = 450) -> str:
    parts = [str(x.get('text', '')) for x in node.get('members', []) if x.get('text')]
    return short(' '.join(parts), limit)


def anchor_preview(node: dict, anchors: list[dict]) -> list[dict]:
    members = {str(m.get('id')): m for m in node.get('members', [])}
    result = []
    for anchor in anchors:
        member = members.get(str(anchor.get('member_id')), {})
        result.append({
            'anchor_quote': short(anchor.get('quote', ''), 900),
            'member_context': short(member.get('text', ''), 1600),
            'kind': anchor.get('kind'),
            'granularity': anchor.get('granularity'),
            'localizable': bool(anchor.get('localizable')),
            'bounding_boxes': anchor.get('boxes', []),
        })
    return result


def source_kind(route: dict) -> str:
    provenance = route.get('provenance') or []
    return str(provenance[0].get('source', 'unknown')) if provenance else 'unknown'


def stratum(row: dict) -> str:
    route = row['route']
    kind = source_kind(route)
    if route.get('eligibility') == 'denied':
        return 'denied_control'
    if kind == 'qwen_original' and row['novel_page']:
        return 'qwen_new_page'
    if kind == 'qwen_original' and row['outside_dense20']:
        return 'qwen_new_node'
    if kind == 'qwen_original':
        return 'qwen_existing'
    if kind.startswith('reading') or route.get('relation_type') in {'NEXT', 'PREVIOUS'}:
        return 'reading'
    return 'other'


def consolidate(decisions: list[dict], nav: list[dict], nodes: dict[str, dict],
                eligible: set[str]) -> list[dict]:
    """One record per (query, oriented route), preserving each arm's action."""
    contexts = {x['question_id']: x for x in nav}
    merged: dict[tuple[str, str], dict] = {}
    for item in decisions:
        qid = str(item['question_id'])
        route = item['route']
        route_id = str(route['route_id'])
        arm = str(item['arm'])
        if arm not in ARMS:
            raise ValueError('unexpected arm: ' + arm)
        key = (qid, route_id)
        if qid not in contexts:
            raise ValueError('missing navigation query ' + qid)
        if key not in merged:
            merged[key] = {
                'question_id': qid, 'question': item['question'],
                'route': route,
                'source_dense_rank': int(item['source_dense_rank']),
                'target_dense_rank': int(item['target_dense_rank']),
                'target_page': item.get('target_page'),
                'arm_actions': {},
            }
        record = merged[key]
        if record['route'] != route or record['question'] != item['question']:
            raise ValueError('conflicting route record ' + str(key))
        if arm in record['arm_actions']:
            raise ValueError('duplicate arm decision ' + str((key, arm)))
        record['arm_actions'][arm] = item['action']
    filtered_contexts: dict[str, list[str]] = {}
    for qid, context in contexts.items():
        filtered = [x for x in context['node_ranking'] if x in eligible]
        if len(filtered) != len(eligible) or len(set(filtered)) != len(eligible):
            raise ValueError('universe/ranking mismatch: ' + qid)
        filtered_contexts[qid] = filtered
    for row in merged.values():
        qid = row['question_id']
        ranked = filtered_contexts[qid]
        route = row['route']
        source = route['oriented_source_id']
        target = route['oriented_target_id']
        if source not in ranked[:10]:
            raise ValueError('source is not a frozen Top-10 seed: ' + source)
        if target not in eligible:
            raise ValueError('target outside frozen universe: ' + target)
        if row['target_dense_rank'] != ranked.index(target) + 1:
            raise ValueError('target rank changed: ' + qid)
        if row['source_dense_rank'] != ranked.index(source) + 1:
            raise ValueError('source rank changed: ' + qid)
        if not all(arm in row['arm_actions'] for arm in ARMS):
            raise ValueError('missing arm decisions: ' + str((qid, route['route_id'])))
        seed_pages = {(nodes[n]['document'], int(nodes[n]['page'])) for n in ranked[:10]}
        target_page = (nodes[target]['document'], int(nodes[target]['page']))
        row['novel_page'] = target_page not in seed_pages
        row['outside_dense20'] = row['target_dense_rank'] > 20
        row['dense_top10'] = ranked[:10]
        row['dense_rank20'] = ranked[19] if len(ranked) >= 20 else None
        row['stratum'] = stratum(row)
        row['sample_id'] = digest(qid + '\0' + route['route_id'])[:16]
    return list(merged.values())


def sample_routes(rows: list[dict], n: int = 12, seed: int = 20261105) -> list[dict]:
    if n < 1:
        raise ValueError('sample size must be positive')
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row['stratum']].append(row)
    # No gold, model score, or utility label influences sample selection.
    for key, bucket in buckets.items():
        bucket.sort(key=lambda x: (digest(f"{seed}:{x['question_id']}:{x['route']['route_id']}"),
                                   x['sample_id']))
    priority = ['qwen_new_page', 'qwen_new_node', 'denied_control',
                'qwen_existing', 'reading', 'other']
    selected, used, seen_queries = [], set(), set()
    while len(selected) < n:
        changed = False
        for category in priority:
            available = [x for x in buckets.get(category, []) if x['sample_id'] not in used]
            if not available:
                continue
            distinct = [x for x in available if x['question_id'] not in seen_queries]
            chosen = (distinct or available)[0]
            selected.append(chosen)
            used.add(chosen['sample_id'])
            seen_queries.add(chosen['question_id'])
            changed = True
            if len(selected) >= n:
                break
        if not changed:
            break
    return selected


def review_card(row: dict, nodes: dict[str, dict]) -> dict:
    route = row['route']
    source = route['oriented_source_id']
    target = route['oriented_target_id']
    def node_card(nid: str, anchors: list[dict]) -> dict:
        node = nodes[nid]
        return {
            'node_id': nid,
            'document': node.get('document'),
            'page': node.get('page'),
            'node_type': node.get('node_type'),
            'anchors': anchor_preview(node, anchors),
            'node_excerpt': member_preview(node, 1000),
        }
    displaced = None
    if row['outside_dense20']:
        nid = row['dense_rank20']
        displaced = {'node_id': nid, 'document': nodes[nid].get('document'),
                     'page': nodes[nid].get('page'), 'excerpt': member_preview(nodes[nid], 900)}
    return {
        'sample_id': row['sample_id'], 'query': row['question'],
        'relation': {'type': route.get('relation_type'),
                     'claim': route.get('relation_text'),
                     'conditions': route.get('conditions'),
                     'limitations': route.get('limitations')},
        'source': node_card(source, route.get('source_anchors', [])),
        'target': node_card(target, route.get('target_anchors', [])),
        'current_dense_top10': [
            {'rank': i, 'node_id': nid, 'excerpt': member_preview(nodes[nid], 450)}
            for i, nid in enumerate(row['dense_top10'], 1)
        ],
        'dense_candidate_at_risk': displaced,
        'review_instructions': '不查看 Gold、模型动作或私有索引；分别判断关系真实度、Query 适用性、目标增量证据和预算机会成本。',
    }


def prepare(decisions_path: Path, nodes_path: Path, nav_path: Path, universe_path: Path,
            out: Path, max_review: int = 12, seed: int = 20261105) -> dict:
    if out.exists():
        raise FileExistsError('refusing to overwrite: ' + str(out))
    # Hard boundary: this command intentionally has no gold input.
    input_paths = [decisions_path, nodes_path, nav_path, universe_path]
    nodes = {x['id']: x for x in read_jsonl(nodes_path)}
    navigation = read_jsonl(nav_path)
    eligible = {x['entity_id'] for x in read_jsonl(universe_path)
                if x.get('primary_eligible') is True}
    if not eligible <= set(nodes):
        raise ValueError('eligible node missing from nodes file')
    rows = consolidate(read_jsonl(decisions_path), navigation, nodes, eligible)
    chosen = sample_routes(rows, max_review, seed)
    out.mkdir(parents=True)
    (out / 'audit_only').mkdir()
    write_jsonl(out / 'review_cards.jsonl', (review_card(x, nodes) for x in chosen))
    write_jsonl(out / 'annotation_template.jsonl', (
        {'sample_id': x['sample_id'], 'relation_validity': None,
         'query_applicability': None, 'marginal_utility': None,
         'opportunity_cost': None, 'notes': ''} for x in chosen))
    write_jsonl(out / 'audit_only/private_index.jsonl', (
        {'sample_id': x['sample_id'], 'question_id': x['question_id'],
         'edge_id': x['route']['edge_id'], 'route_id': x['route']['route_id'],
         'source_id': x['route']['oriented_source_id'],
         'target_id': x['route']['oriented_target_id'],
         'source_dense_rank': x['source_dense_rank'],
         'target_dense_rank': x['target_dense_rank'],
         'novel_page': x['novel_page'], 'outside_dense20': x['outside_dense20'],
         'stratum': x['stratum'], 'source_kind': source_kind(x['route']),
         'eligibility': x['route']['eligibility'],
         'arm_actions': x['arm_actions']} for x in chosen))
    summary = {'version': 1, 'selected': len(chosen), 'available_routes': len(rows),
               'unique_queries': len({x['question_id'] for x in chosen}),
               'strata': dict(Counter(x['stratum'] for x in chosen)),
               'selection_seed': seed, 'max_review': max_review,
               'inputs_sha256': {str(p): file_hash(p) for p in input_paths},
               'gold_read': False, 'llm_calls': 0, 'gpu_used': False,
               'retrieval_or_production_modified': False,
               'label_status': 'NOT_REVIEWED',
               'metrics': 'not computed until independent human review'}
    write_json(out / 'selection_summary.json', summary)
    (out / 'README.md').write_text(
        '# Query–Edge 盲审\n\n'
        '1. 仅向审查者展示 `review_cards.jsonl` 和 `annotation_template.jsonl`。\n'
        '2. 复制模板为 `labels.jsonl` 并填写全部四个判断；无法判断用 `uncertain`。\n'
        '3. 关闭审查后再运行 `evaluate`，不要在审查前打开 `audit_only/`。\n'
        '4. `valid`/`yes` 不会自动将边升级为 navigation-allowed。\n'
        '5. 指标仅适用于抽中的、实际完成人工审查的路线，不是全图泛化指标。\n',
        encoding='utf-8')
    return summary


def utility_label(label: dict) -> str:
    """Three required dimensions; uncertain is not a negative."""
    vals = (label['relation_validity'], label['query_applicability'],
            label['marginal_utility'])
    if 'invalid' in vals or 'no' in vals:
        return 'negative'
    if vals == ('valid', 'yes', 'yes'):
        return 'positive'
    return 'unknown'


def evaluate(index_path: Path, labels_path: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError('refusing to overwrite: ' + str(out))
    index = {x['sample_id']: x for x in read_jsonl(index_path)}
    labels: dict[str, dict] = {}
    for label in read_jsonl(labels_path):
        sid = label['sample_id']
        if sid in labels or sid not in index:
            raise ValueError('duplicate or unknown sample_id: ' + sid)
        for key, choices in CHOICES.items():
            if label.get(key) not in choices:
                raise ValueError(f'incomplete or invalid {key} for {sid}')
        labels[sid] = label
    if not labels:
        raise ValueError('no completed human labels')
    per_route = []
    for sid, label in sorted(labels.items()):
        meta = index[sid]
        per_route.append({'sample_id': sid, 'judgement': utility_label(label),
                          'opportunity_cost': label['opportunity_cost'],
                          'source_kind': meta['source_kind'],
                          'outside_dense20': meta['outside_dense20'],
                          'arm_selected': {arm: meta['arm_actions'][arm] in SELECTED
                                           for arm in ARMS}})
    metrics = {}
    known = [r for r in per_route if r['judgement'] != 'unknown']
    for arm in ARMS:
        tp = sum(r['judgement'] == 'positive' and r['arm_selected'][arm] for r in known)
        fp = sum(r['judgement'] == 'negative' and r['arm_selected'][arm] for r in known)
        fn = sum(r['judgement'] == 'positive' and not r['arm_selected'][arm] for r in known)
        tn = sum(r['judgement'] == 'negative' and not r['arm_selected'][arm] for r in known)
        metrics[arm] = {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                        'precision_reviewed': tp / (tp + fp) if tp + fp else None,
                        'recall_reviewed': tp / (tp + fn) if tp + fn else None,
                        'selected_reviewed': sum(r['arm_selected'][arm] for r in per_route),
                        'selected_unknown': sum(r['judgement'] == 'unknown' and r['arm_selected'][arm]
                                                for r in per_route)}
    summary = {'scope': 'selected human-reviewed sample only', 'n_sampled': len(index),
               'n_reviewed': len(labels), 'n_determinate': len(known),
               'n_unknown': len(per_route) - len(known),
               'n_positive': sum(r['judgement'] == 'positive' for r in known),
               'n_negative': sum(r['judgement'] == 'negative' for r in known),
               'metrics': metrics,
               'caution': 'No full-graph precision/recall, gold recall or production admission is inferred.'}
    out.mkdir(parents=True)
    write_json(out / 'summary.json', summary)
    write_jsonl(out / 'reviewed_route_outcomes.jsonl', per_route)
    table = ['# Query–Edge Utility 人工审查结果', '',
             f"完成标注 {len(labels)}/{len(index)}；明确正例 {summary['n_positive']}，明确负例 {summary['n_negative']}，未定 {summary['n_unknown']}。", '',
             '| Arm | TP | FP | FN | TN | Reviewed Precision | Reviewed Recall |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for arm, m in metrics.items():
        fmt = lambda v: 'N/A' if v is None else f'{v:.3f}'
        table.append(f"| {arm} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | {fmt(m['precision_reviewed'])} | {fmt(m['recall_reviewed'])} |")
    table += ['', '**注意：** 仅对盲审子集进行探索性比较；无独立 Gold 或证据状态标签，不推断全图检索收益。',
              '人工正例不会自动变成 `allowed_for_navigation=true`，仍需要独立的安全审核。']
    (out / 'REPORT.md').write_text('\n'.join(table) + '\n', encoding='utf-8')
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--decisions', type=Path, default=PHASE1 / 'route_decisions.jsonl')
    prep.add_argument('--nodes', type=Path, default=NODES)
    prep.add_argument('--navigation', type=Path, default=NAV)
    prep.add_argument('--universe', type=Path, default=UNIVERSE)
    prep.add_argument('--out', type=Path, default=OUT)
    prep.add_argument('--max-review', type=int, default=12)
    prep.add_argument('--seed', type=int, default=20261105)
    ev = sub.add_parser('evaluate')
    ev.add_argument('--index', type=Path, default=OUT / 'audit_only/private_index.jsonl')
    ev.add_argument('--labels', type=Path, required=True)
    ev.add_argument('--out', type=Path, default=OUT.parent / (OUT.name + '_evaluation'))
    args = p.parse_args()
    if args.command == 'prepare':
        result = prepare(args.decisions, args.nodes, args.navigation, args.universe,
                         args.out, args.max_review, args.seed)
    else:
        result = evaluate(args.index, args.labels, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()