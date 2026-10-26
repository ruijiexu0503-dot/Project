"""Compare cached runs against exactly the same queries, corpus and gold."""
from collections import defaultdict
from pathlib import Path
import json
from evaluate_vldocir import evaluate, page
from evaluate_vldocir_ap import average_precision
from run_node_context_edges import rows, read, write, sha

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
COL=ROOT/'EvidenceNet/output/vldocir_colnomic_7b_20261016'
SEARCH=ROOT/'migration/vldocir-edge-20261022/results/search'
TRACE=ROOT/'migration/vldocir_trace_inputs_20261023'
OUT=ROOT/'EvidenceNet/output/vldocir_matched_comparison_20261023'

def main():
    queries=rows(TRACE/'queries.jsonl'); gold=rows(TRACE/'gold_evidence.jsonl')
    qmap=lambda rr:{r['question_id']:r['question'] for r in rr}
    assert qmap(queries)==qmap(rows(COL/'queries.jsonl'))==qmap(rows(BASE/'pilot/queries.jsonl'))
    assert gold==rows(BASE/'pilot/gold_evidence.jsonl')
    images=lambda rr:{page(r):r['sha256'] for r in rr}
    assert images(rows(COL/'pages.jsonl'))==images(rows(BASE/'pilot/image_pages.jsonl'))
    corpus=set(images(rows(COL/'pages.jsonl'))); g=defaultdict(set)
    for r in gold:g[r['question_id']].add(page(r))
    sources={'ColNomic-7B':COL/'scores.jsonl','Hybrid no-edge (same round)':SEARCH/'no_edge_scores.jsonl',
             'Hybrid edge bonus':SEARCH/'edge_scores.jsonl'}
    results={}; per={}
    for name,path in sources.items():
        scores=rows(path); grouped=defaultdict(dict)
        for r in scores:
            assert page(r) not in grouped[r['question_id']]
            grouped[r['question_id']][page(r)]=r['score']
        assert set(grouped)==set(qmap(queries))
        assert all(set(v)==corpus for v in grouped.values())
        metrics=evaluate(queries,gold,scores,corpus=corpus)['macro_six_types']
        aps={}
        for q in queries:
            qid=q['question_id']; rank=sorted(grouped[qid],key=lambda p:(-grouped[qid][p],p))
            aps[qid]=average_precision(rank,g[qid],5)
        bytype=defaultdict(list)
        for q in queries:bytype[q['question_type']].append(aps[q['question_id']])
        metrics['mAP@5']=sum(sum(v)/len(v) for v in bytype.values())/len(bytype)
        results[name]=metrics; per[name]=aps
    probe=read(ROOT/'EvidenceNet/output/vldocir_query_graph_probe_20261023/report.json')
    assert abs(probe['reports']['graph_candidates']['mean']['AP5']-results['Hybrid no-edge (same round)']['mAP@5'])<1e-12
    control=per['ColNomic-7B']; current=per['Hybrid no-edge (same round)']
    delta=[current[q]-control[q] for q in control]
    report=dict(queries=len(queries),pages=len(corpus),query_texts_equal=True,page_image_hashes_equal=True,
                gold_equal=True,results=results,paired_AP5=dict(wins=sum(x>1e-12 for x in delta),
                losses=sum(x< -1e-12 for x in delta),ties=sum(abs(x)<=1e-12 for x in delta)),
                source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sources.values()},
                limitation='Local base ColNomic reproduction, not official ensemble/context/rerank. '
                'Query-graph probe Top10 equals current no-edge by construction. '
                'Previously inspected 24-query pilot; no independent generalization claim.')
    write(OUT/'comparison.json',report)
    keys=['Recall@5','nDCG@5','RecallAll@5','mAP@5']
    lines=['# Same-query / same-corpus cached comparison','',
           'Verified 24 identical query texts, 518 page identities and image hashes, identical gold.','',
           '| Method | '+' | '.join(keys)+' |','| --- | ---: | ---: | ---: | ---: |']
    for name,m in results.items():lines.append('| '+name+' | '+' | '.join(f'{100*m[k]:.2f}%' for k in keys)+' |')
    lines+=['',report['limitation'],'','Paired AP@5 against ColNomic: '+json.dumps(report['paired_AP5'])]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
