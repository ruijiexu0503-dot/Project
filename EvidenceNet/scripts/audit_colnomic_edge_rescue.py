"""Baseline-only failure selection and frozen-graph reachability, not a rescue score.

No generation, query splitting, new edges or changes to official gold. Page
adjacency is reported separately and must not be called a verified NEXT edge.
"""
import argparse
from collections import defaultdict
import hashlib
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'EvidenceNet/output/vldocir_colnomic_7b_20261016'
FROZEN = ROOT / 'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/pilot'
GRAPH = ROOT / 'migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/edge_records.jsonl'


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def page(row):
    return str(row['document_id']), str(row['page_number'])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_paths(graph, seeds):
    """All one-hop page paths from seeds, with no gold input or path ranking."""
    paths = defaultdict(list)
    for edge in graph:
        a, b = (page(edge['endpoints'][s]) for s in ('A', 'B'))
        if a == b:
            continue
        for source, target in ((a, b), (b, a)):
            if source in seeds:
                paths[target].append({'edge_id': edge['edge_id'], 'seed_page': source,
                                      'seed_rank': seeds.index(source) + 1})
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT/'EvidenceNet/output/vldocir_colnomic_edge_rescue_audit_20261028')
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError('fresh output required')
    manifest = json.loads((BASE/'manifest.json').read_text())['files']
    results = json.loads((BASE/'result_manifest.json').read_text())
    sources = [BASE/'scores.jsonl', BASE/'queries.jsonl', BASE/'pages.jsonl',
               FROZEN/'gold_evidence.jsonl', GRAPH]
    for p in sources:
        expected = manifest.get(str(p)) or results.get(str(p.relative_to(ROOT)))
        if p != GRAPH and (not expected or sha(p) != expected):
            raise ValueError('unverified baseline input: '+str(p))
    queries = rows(BASE/'queries.jsonl')
    corpus = {page(p) for p in rows(BASE/'pages.jsonl')}
    scores = defaultdict(dict)
    for r in rows(BASE/'scores.jsonl'):
        if page(r) in scores[r['question_id']] or not math.isfinite(r['score']):
            raise ValueError('duplicate/nonfinite score')
        scores[r['question_id']][page(r)] = r['score']
    assert len(queries) == 24 and len(corpus) == 518
    assert set(scores) == {q['question_id'] for q in queries}
    assert all(set(v) == corpus for v in scores.values())
    graph = rows(GRAPH)
    assert len(graph) == 187
    assert all(page(e['endpoints'][s]) in corpus for e in graph for s in ('A', 'B'))
    # Freeze ranks and all-seed paths for every query BEFORE reading gold.
    rankings = {q: sorted(v, key=lambda p: (-v[p], p)) for q, v in scores.items()}
    paths = {(q,k): graph_paths(graph, r[:k]) for q,r in rankings.items() for k in (5,10,20)}
    gold = defaultdict(set)
    gold_rows = rows(FROZEN/'gold_evidence.jsonl')
    for r in gold_rows:
        gold[r['question_id']].add(page(r))
    misses = []
    edge_map = {e['edge_id']: e for e in graph}
    for q in queries:
        qid = q['question_id']; ranking = rankings[qid]
        for target in sorted(gold[qid]):
            rank = ranking.index(target) + 1
            if rank <= 5:
                continue
            reachable = {str(k): paths[qid,k].get(target, []) for k in (5,10,20)}
            incident = [e for e in graph if target in [page(e['endpoints'][s]) for s in ('A','B')]]
            adjacency = [dict(seed_page=p, seed_rank=i+1) for i,p in enumerate(ranking[:5])
                         if p[0] == target[0] and abs(int(p[1])-int(target[1])) == 1]
            misses.append(dict(question_id=qid, question=q['question'], question_type=q['question_type'],
                target_page=target, baseline_rank=rank, outside_top20=rank>20,
                one_hop_paths=reachable, incident_edges=incident,
                page_adjacency_from_top5=adjacency,
                caveat='Reachability only; no evidence validity or rescued final rank established.'))
    summary = dict(queries=24,pages=518,gold_query_page_pairs=sum(map(len,gold.values())),
        missed_top5_pairs=len(misses),queries_with_top5_miss=len({x['question_id'] for x in misses}),
        missed_top20_pairs=sum(x['outside_top20'] for x in misses),
        top5_misses_one_hop_reachable={str(k):sum(bool(x['one_hop_paths'][str(k)]) for x in misses) for k in (5,10,20)},
        top20_misses_one_hop_from_top20=sum(x['outside_top20'] and bool(x['one_hop_paths']['20']) for x in misses),
        baseline='Our cached ColNomic-7B 24-query/518-page reproduction, NOT author full-corpus runs',
        actual_rescue_evaluation_complete=False,
        label_use='Only baseline failure selection/diagnostics, never graph/path generation',
        caveat='Existing development queries; failure-only subset cannot establish overall improvement.')
    output = dict(summary=summary, cases=misses, input_sha256={str(p.relative_to(ROOT)):sha(p) for p in sources},
                  code_sha256=sha(Path(__file__)))
    args.output.mkdir(parents=True)
    (args.output/'audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    esc=lambda x:html.escape(str(x))
    cards=[]
    for case in misses:
        evidence=''.join('<details><summary>'+esc(e['edge_id'])+'</summary>'+''.join(
            '<h4>'+s+' '+esc(page(e['endpoints'][s]))+'</h4><pre>'+esc('\n'.join(t['text'] for t in e['endpoints'][s]['spans']))+'</pre>'
            for s in ('A','B'))+'</details>' for e in case['incident_edges'])
        cards.append('<section><h2>'+esc(case['question'])+'</h2><p>标注页 '+esc(case['target_page'])+
            '；ColNomic 排名 '+str(case['baseline_rank'])+'</p><p>前5/10/20页出发的一跳路径数：'+
            esc([len(case['one_hop_paths'][str(k)]) for k in (5,10,20)])+'</p><pre>'+esc(json.dumps(case['one_hop_paths'],ensure_ascii=False,indent=2))+
            '</pre><p>前5页的页码相邻线索（不是已验证NEXT边）：'+esc(case['page_adjacency_from_top5'])+'</p>'+evidence+'</section>')
    (args.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>ColNomic失败与edge可达性</title>'
        '<style>body{font:16px system-ui;max-width:1100px;margin:30px auto;background:#f4f6fa}section{background:white;padding:22px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style>'
        '<h1>ColNomic失败样本与现有edge可达性</h1><p>这是本地同库模型复现，不是作者官方全集失败清单；可达不等于已救回。没有修改gold或按gold补边。</p><pre>'+
        esc(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(cards))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print(args.output/'index.html')


if __name__ == '__main__':
    main()
