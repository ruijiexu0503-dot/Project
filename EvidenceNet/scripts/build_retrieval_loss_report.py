"""Render frozen 78100 candidate coverage as a standalone, source-linked report."""
import base64
import hashlib
import json
import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
BENCH = ROOT / 'data/benchmarks/evidence_edges_v1_20261014'
OUT = ROOT / 'EvidenceNet/output/retrieval_loss_report_20261016'


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    results = json.loads((SOURCE / 'retrieval_cases.json').read_text())
    summary = json.loads((SOURCE / 'retrieval_summary.json').read_text())
    cases = {c['suite_case_id']: c for c in rows(BENCH / 'cases.jsonl')}
    nodes = {n['id']: n for n in rows(BENCH / 'nodes.jsonl')}
    policies = ['hierarchical_76411_replay', 'whole_node_previous_policy',
                'global_cosine_equal_budget_control', 'initial_pool_upper_bound_not_final']
    lookup = {p: {c['suite_case_id']: c for c in results[p]} for p in policies}
    pair_key = lambda a, b: tuple(sorted((a, b)))
    pool = {pair_key(p['source'], p['target']): p for p in rows(SOURCE / 'initial_pool.jsonl')}
    article = {pair_key(p['source_article'], p['target_article']): p
               for p in rows(SOURCE / 'article_candidates.jsonl')}
    assets, records = {}, []
    for entry in results[policies[0]]:
        if entry['label'] != 'POSITIVE':
            continue
        cid = entry['suite_case_id']
        case = cases[cid]
        found = {p: lookup[p][cid]['retrieved'] for p in policies}
        initial = pool.get(pair_key(case['A']['node_id'], case['B']['node_id']))
        assert bool(initial) == found[policies[3]], cid
        status = 'kept' if found[policies[0]] else ('cut' if initial else 'absent')
        endpoints = []
        for side in ['A', 'B']:
            ref = case[side]
            node = nodes[ref['node_id']]
            images = []
            for member in node.get('members', []):
                crop = member.get('crop')
                if not crop:
                    continue
                path = BENCH / crop
                if crop not in assets:
                    assets[crop] = 'data:' + mimetypes.guess_type(path.name)[0] + ';base64,' + base64.b64encode(path.read_bytes()).decode()
                images.append({'asset': crop, 'description': member.get('text', '')})
            endpoints.append({'side': side, 'node_id': ref['node_id'],
                              'document': ref['document'], 'page': ref['original_pdf_page'],
                              'quote': ref['primary_anchor']['quote'],
                              'member_id': ref['primary_anchor']['member_id'],
                              'text': node.get('text', ''), 'images': images})
        routing = '初始池中没有该节点对，不能据此判断文章路由'
        route_record = None
        if initial:
            a, b = initial['source_article'], initial['target_article']
            if a == b:
                routing = '同一搜索组：无需跨组文章路由'
            else:
                route_record = article.get(pair_key(a, b))
                routing = ('文章/搜索组对已入选' if route_record and route_record['selected_for_node_search']
                           else '文章/搜索组对未入选；仍可能由全局通道保留')
        records.append({'id': cid, 'relation': case['relation'], 'rationale': case['rationale'],
                        'conditions': case.get('conditions', ''), 'status': status,
                        'found': found, 'endpoints': endpoints, 'routing': routing,
                        'routing_record': route_record, 'initial_candidate': initial})
    counts = {s: sum(r['status'] == s for r in records) for s in ['kept', 'cut', 'absent']}
    assert counts == {'kept': 10, 'cut': 14, 'absent': 2}, counts
    data = {'records': records, 'assets': assets, 'summary': summary['results'],
            'counts': counts, 'policies': policies, 'job': 78100, 'date': '2026-10-16'}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('retrieval_loss_report.html').read_text()
    (OUT / 'index.html').write_text(template.replace('__REPORT_DATA__', payload))
    sources = [SOURCE / x for x in ['retrieval_cases.json', 'retrieval_summary.json',
               'initial_pool.jsonl', 'article_candidates.jsonl']]
    sources += [BENCH / 'cases.jsonl', BENCH / 'nodes.jsonl', Path(__file__),
                Path(__file__).with_name('retrieval_loss_report.html')]
    (OUT / 'manifest.json').write_text(json.dumps({str(p.relative_to(ROOT)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, indent=2))
    print(json.dumps({'cases': len(records), 'counts': counts, 'assets': len(assets),
                      'output': str(OUT / 'index.html')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
