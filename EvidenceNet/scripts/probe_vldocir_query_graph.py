"""CPU diagnostic: frozen graph, cached query scores, no graph bonus or re-encoding."""
from pathlib import Path
from collections import defaultdict
import json
from evaluate_vldocir_ap import average_precision

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'migration/vldocir-edge-20261022/results'
INPUT = ROOT / 'migration/vldocir_trace_inputs_20261023'
OUT = ROOT / 'EvidenceNet/output/vldocir_query_graph_probe_20261023'

def rows(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

def main():
    scores = defaultdict(dict)
    for r in rows(SOURCE/'search/no_edge_scores.jsonl'):
        scores[r['question_id']][(r['document_id'], str(r['page_number']))] = r['score']
    nodes = {n['id']: n for n in rows(SOURCE/'nodes.jsonl')}
    adj = defaultdict(list)
    for e in rows(SOURCE/'graph/related.jsonl'):
        adj[e['source']].append((e['target'], e['task_id']))
        adj[e['target']].append((e['source'], e['task_id']))
    records = []
    # Freeze selection before reading gold. Same 20-page budget, same top-10 core.
    for t in rows(SOURCE/'search/search_traces.jsonl'):
        qid = t['question_id']; direct = scores[qid]
        rank = sorted(direct, key=lambda p: (-direct[p], p))
        core = set(rank[:10]); paths = []; reached = set()
        for seed in t['seeds']:
            for target, eid in adj[seed['node_id']]:
                n = nodes[target]; pid = (n['document'], str(n['page']))
                reached.add(pid)
                paths.append(dict(seed=seed['node_id'], edge=eid, target=target,
                                  target_page=pid, query_page_score=direct[pid]))
        extra = sorted(reached-core, key=lambda p: (-direct[p], p))[:10]
        selected = core | set(extra)
        for pid in rank:
            if len(selected) >= 20: break
            selected.add(pid)
        graph_rank = sorted(selected, key=lambda p: (-direct[p], p))
        assert len(selected) == 20
        assert graph_rank[:10] == rank[:10]
        records.append(dict(question_id=qid, question=t['question'],
                            direct_candidates=rank[:20], graph_candidates=graph_rank,
                            graph_extra=extra, paths=paths))
    gold = defaultdict(set)
    for r in rows(INPUT/'gold_evidence.jsonl'):
        gold[r['question_id']].add((r['document_id'], str(r['page_number'])))
    reports = {}
    for arm in ['direct_candidates', 'graph_candidates']:
        per = []
        for r in records:
            g=gold[r['question_id']]; ranked=r[arm]
            per.append(dict(question_id=r['question_id'],
                            AP5=average_precision(ranked,g,5),
                            R5=len(set(ranked[:5])&g)/len(g),
                            candidate_recall=len(set(ranked)&g)/len(g)))
        reports[arm] = dict(mean={k:sum(x[k] for x in per)/len(per)
                                 for k in ['AP5','R5','candidate_recall']}, per_query=per)
    report=dict(protocol='Frozen 213 edges; cached query/page scores; existing seeds; '
                'top10 direct core + up to10 graph pages, dense fill; deduplicate; '
                'all candidates sorted by original query score; no edge bonus; budget20.',
                limitation='Top10 equality follows mathematically from retained direct core and '
                'identical scores. This is a plumbing/control diagnostic, NOT evidence of improved '
                'query understanding. No query-anchor semantic gate or learned reranker yet.',
                online_document_embeddings=0, new_inference_calls=0, reports=reports)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (OUT/'paths.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    print(json.dumps({a:r['mean'] for a,r in reports.items()},indent=2))

if __name__ == '__main__': main()
