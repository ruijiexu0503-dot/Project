"""Replay frozen candidate selection and explain losses; never construct edges."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
LINE = ROOT / 'EvidenceNet/output/line_aware_edge_retrieval_v1_20261017'
VERIFY = ROOT / 'EvidenceNet/output/layered_edge_verifier_v1_20261016'
OUT = ROOT / 'EvidenceNet/output/missed_edge_stage_audit_20261017'


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def key(row):
    return tuple(sorted((row['source'], row['target'])))


def ordered(items):
    return sorted(items, key=lambda p: (-p['retrieval_score'], p['source'], p['target']))


def replay(pool, articles):
    groups = defaultdict(list)
    for pair in pool:
        groups[tuple(sorted((pair['source_article'], pair['target_article'])))].append(pair)
    routed = {tuple(sorted((p['source_article'], p['target_article'])))
              for p in articles if p['selected_for_node_search']}
    selected, traces = defaultdict(set), defaultdict(dict)

    def take(items, limit, lane, cap):
        degree = Counter()
        taken = 0
        for rank, pair in enumerate(ordered(items), 1):
            a, b = key(pair)
            if taken >= limit:
                reason = 'quota_exhausted'
            elif degree[a] >= cap or degree[b] >= cap:
                reason = 'endpoint_degree_cap'
            else:
                reason = 'selected'
            traces[(a, b)][lane] = dict(rank=rank, reason=reason, limit=limit,
                degree_cap=cap, prior_selected=taken, endpoint_degrees=[degree[a], degree[b]])
            if reason == 'selected':
                selected[(a, b)].add(lane)
                degree[a] += 1
                degree[b] += 1
                taken += 1

    for article_pair in sorted(routed):
        take(groups[article_pair], 16, 'article_routed', 4)
    take([p for p in pool if p['source_article'] != p['target_article']], 96, 'global_escape', 6)
    for article_pair, items in groups.items():
        if article_pair[0] == article_pair[1]:
            take(items, 8, 'intra_article', 3)
    return selected, traces, routed


def main():
    pool = rows(LINE / 'initial_pool.jsonl')
    articles = rows(LINE / 'article_candidates.jsonl')
    frozen = rows(LINE / 'node_candidates.jsonl')
    selected, traces, routed = replay(pool, articles)
    assert set(selected) == {key(p) for p in frozen}, 'replay differs from frozen selector'
    for pair in frozen:
        assert selected[key(pair)] == set(pair['selection_routes']), 'lane mismatch'
    lookup = {key(p): p for p in pool}
    nodes = {n['id']: n for n in rows(BASE / 'corpus_nodes.jsonl')}
    inputs = {p['task']['task_id']: p['task'] for p in rows(VERIFY / 'inputs.jsonl')}
    predictions = {p['task_id']: p for p in rows(VERIFY / 'predictions.jsonl')}
    references = {r['suite_case_id']: r for r in rows(VERIFY / 'evaluation/reference.jsonl')}
    # Labels are consulted only after the exact, label-blind selector replay.
    records = []
    for case in rows(BASE / 'evaluation/cases.jsonl'):
        pair_key = tuple(sorted((case['A']['node_id'], case['B']['node_id'])))
        pair = lookup.get(pair_key)
        article_key = tuple(sorted(nodes[n]['article_id'] for n in pair_key))
        same_article = article_key[0] == article_key[1]
        if pair_key in selected:
            stage = 'selected_candidate'
        elif pair is None:
            stage = 'absent_from_initial_pool'
        elif not same_article and article_key not in routed:
            stage = 'article_route_not_selected'
        else:
            lane = 'intra_article' if same_article else 'article_routed'
            stage = lane + '_' + traces[pair_key][lane]['reason']
        reference = references.get(case['suite_case_id'])
        result = None
        if reference:
            task_id = reference['task_id']
            task = inputs[task_id]
            assert tuple(sorted((task['A']['node_id'], task['B']['node_id']))) == pair_key
            prediction = predictions.get(task_id)
            if prediction and prediction['valid']:
                p = prediction['result']
                result = {field: p[field] for field in ('decision', 'basis', 'relation', 'matched_claim', 'reason')}
        records.append(dict(case_id=case['suite_case_id'], label=case['label'],
            requested_relation=case['relation'], rationale=case['rationale'],
            source=pair_key[0], target=pair_key[1], articles=article_key,
            unresolved_article_bucket=any('UNRESOLVED_PAGE_BUCKET' in x for x in article_key),
            stage=stage, initial_pair_found=pair is not None,
            article_routed=not same_article and article_key in routed,
            lane_traces=traces.get(pair_key, {}),
            retrieval_score=pair and pair['retrieval_score'],
            signals=pair and pair['signals'], best_views=pair and pair['best_views'],
            fixed_pair_verifier=result,
            source_anchors={side: case[side]['primary_anchor'] for side in ('A', 'B')}))
    positives = [r for r in records if r['label'] == 'POSITIVE']
    counts = dict(Counter(r['stage'] for r in positives))
    summary = dict(total_initial_pairs=len(pool), total_selected_pairs=len(frozen),
        provisional_positives=len(positives), positive_stages=counts,
        caveat='Development-suite candidate coverage. Fixed-pair verifier predictions are from a separate frozen run, not an end-to-end run; original positive labels include navigation-only relations.',
        qwen_calls=0, production_graph_modified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'cases.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    paths = [Path(__file__), BASE / 'corpus_nodes.jsonl', BASE / 'evaluation/cases.jsonl',
             LINE / 'initial_pool.jsonl', LINE / 'article_candidates.jsonl', LINE / 'node_candidates.jsonl',
             VERIFY / 'inputs.jsonl', VERIFY / 'predictions.jsonl', VERIFY / 'evaluation/reference.jsonl']
    (OUT / 'manifest.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                                for p in paths}, indent=2) + '\n')
    text = ['# 漏连样本逐层审计（2026-10-17）', '',
        '对最新 line-aware 的全量候选重放原筛选器，校验选中的 pair 集合及通道与冻结结果完全一致。',
        '候选筛选后才读取标签；不运行模型、不修改生产图。', '',
        '| 淘汰/保留阶段 | 正例数 |', '|---|---:|']
    text += [f'| {stage} | {count} |' for stage, count in counts.items()]
    text += ['', '| 样本 | 去向 | 局部排名 / 配额 | 独立固定 pair 核验 |', '|---|---|---|---|']
    for r in positives:
        local = r['lane_traces'].get('intra_article', r['lane_traces'].get('article_routed'))
        ranking = f"{local['rank']} / {local['limit']}" if local else '未进入该通道'
        decision = r['fixed_pair_verifier']['decision'] if r['fixed_pair_verifier'] else '未测试'
        text.append(f"| {r['case_id']} | {r['stage']} | {ranking} | {decision} |")
    text += ['', '**解释边界：**最后一列仅说明同一 pair 被直接送入另一轮固定样本核验器时的判断，不能作为本次候选的端到端精度。',
        '26 个旧正例包含宽泛方法/公式对应；P11、P12、P26 被严格核验拒绝，不应为了提高这个旧标签分数而自动写成强证据边。',
        'P01 的独立核验接受了边，但 CONTRASTS_WITH 标签不对：两端是在认同训练后固定这一限制。',
        '完整原文、信号分数、各通道排名与拒绝原因见 cases.jsonl。', '']
    (OUT / 'REPORT.md').write_text('\n'.join(text))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
