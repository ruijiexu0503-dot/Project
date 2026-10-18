"""CPU-only formula representation comparison. Does not publish semantic edges."""
import argparse
from pathlib import Path
import time
import numpy as np

import run_hierarchical_edge_retrieval as h
import formula_retrieval_views as formula
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha

SOURCE=ROOT/'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
OUT=ROOT/'EvidenceNet/output/formula_retrieval_v1_20261016'
READING=[ROOT/'EvidenceNet/output/paper_relevance_urban_traffic_20261013/graph/reading_edges.jsonl',
         ROOT/'EvidenceNet/output/article_bridge_expanded_v5_20261012/reading_edges.jsonl']
ARMS=('baseline','formula_raw','formula_context')


def check(out):
    for p,digest in read(out/'manifest.json')['files'].items():
        if sha(p)!=digest:raise ValueError('changed frozen input: '+p)


def prepare(out):
    if (out/'manifest.json').exists():check(out);return
    nodes={n['id']:n for n in rows(SOURCE/'corpus_nodes.jsonl')};policies=read(SOURCE/'corpus_policies.json')
    reading=[e for f in READING for e in rows(f)];stats={}
    for arm in ARMS:
        if arm=='baseline':views=h.make_views(nodes,policies);bindings=[]
        else:views,bindings=formula.build_formula_views(nodes,policies,reading,arm=='formula_context')
        jsonl(out/arm/'views.jsonl',views);jsonl(out/arm/'formula_bindings.jsonl',bindings)
        stats[arm]=dict(views=len(views),nodes=len({v['node_id'] for v in views}),
            formulas=len(bindings),formulas_with_context=sum(bool(b['context_spans']) for b in bindings),
            formula_context_views=sum(v['kind']=='formula_context' for v in views))
    write(out/'protocol.json',dict(arms=stats,source_nodes=len(nodes),generative_model_used=False,
        change='Only formula representations change. Explicit formula modality, original LaTex, deterministic notation tags, extractive original context. Ordinary text/table/visual views unchanged.',
        context='Known same-article provenance; same-page unique NEXT plus introduction/where cues, or unique equation-number reference in same article. No generated descriptions or inferred semantic edges.',
        comparison='Baseline vs formula_raw isolates representation/coverage restoration; formula_raw vs formula_context isolates extractive context.',
        budget='Unchanged hierarchy defaults; additionally common prefix K=min(1301, all native counts). Labels read after candidates.',
        limitations='Parser NEXT is not guaranteed reading order. Cue-based context is conservative but needs source review. Retrieval gains do not establish formula equivalence or semantic edge quality.'))
    files=[SOURCE/n for n in ['corpus_nodes.jsonl','corpus_policies.json','views.jsonl','view_vectors.npy','evaluation/cases.jsonl']]+READING
    files += [Path(__file__),Path(formula.__file__),Path(h.__file__),Path(formula.sentence_spans.__code__.co_filename),
              Path(h.__file__).with_name('run_traffic_relevance_cpu.py'),Path(h.__file__).with_name('run_node_context_edges.py'),
              Path(h.__file__).with_name('compare_previous_edge_schemes.py')]
    files += [out/a/f for a in ARMS for f in ['views.jsonl','formula_bindings.jsonl']]+[out/'protocol.json']
    files += list(h.ENCODER.glob('*.json'))+[h.ENCODER/'model.safetensors',h.ENCODER/'merges.txt',h.ENCODER/'vocab.json']
    write(out/'manifest.json',dict(files={str(p.resolve()):sha(p) for p in files}))
    print(stats,flush=True)


def run(out):
    check(out)
    import torch
    from transformers import AutoTokenizer
    torch.set_num_threads(32);started=time.monotonic()
    nodes={n['id']:n for n in rows(SOURCE/'corpus_nodes.jsonl')}
    views={a:rows(out/a/'views.jsonl') for a in ARMS}
    base=rows(SOURCE/'views.jsonl');vectors=np.load(SOURCE/'view_vectors.npy')
    assert len(base)==len(vectors)
    cache={v['retrieval_text']:vectors[i] for i,v in enumerate(base)}
    newtexts=sorted({v['retrieval_text'] for vv in views.values() for v in vv}-cache.keys())
    if (out/'new_vectors.npy').exists():
        assert read(out/'new_texts.json')==newtexts
        newvec=np.load(out/'new_vectors.npy')
    else:
        write(out/'new_texts.json',newtexts)
        newvec=np.asarray(h.cpu_embed(newtexts,h.ENCODER),dtype=np.float32)
        np.save(out/'new_vectors.npy',newvec)
    assert len(newtexts)==len(newvec);cache.update(zip(newtexts,newvec))
    tokenizer=AutoTokenizer.from_pretrained(h.ENCODER,local_files_only=True)
    native={}
    for arm in ARMS:
        lengths=[len(tokenizer(v['retrieval_text'])['input_ids']) for v in views[arm]]
        write(out/arm/'token_lengths.json',dict(total=len(lengths),truncated=sum(n>512 for n in lengths),per_view=dict(zip([v['view_id'] for v in views[arm]],lengths))))
        vec=np.asarray([cache[v['retrieval_text']] for v in views[arm]],dtype=np.float32)
        np.save(out/arm/'vectors.npy',vec)
        pool=h.retrieve(views[arm],vec);articles,selected=h.route_and_select(nodes,pool)
        jsonl(out/arm/'initial_pool.jsonl',pool.values());jsonl(out/arm/'article_candidates.jsonl',articles)
        jsonl(out/arm/'native_candidates.jsonl',selected);native[arm]=selected
        print(arm,'retrieved',len(pool),'selected',len(selected),flush=True)
    # All candidates exist before evaluation labels are loaded.
    from compare_previous_edge_schemes import coverage
    cases=rows(SOURCE/'evaluation/cases.jsonl');budget=min(1301,*(len(native[a]) for a in ARMS))
    summary={};details={};case_diagnostics={}
    for arm in ARMS:
        summary[arm]={};details[arm]={}
        pool=rows(out/arm/'initial_pool.jsonl');matched=native[arm][:budget]
        jsonl(out/arm/'matched_candidates.jsonl',matched)
        for stage,candidates in [('initial',pool),('native',native[arm]),('matched',matched)]:
            summary[arm][stage],details[arm][stage]=coverage(cases,candidates)
        ordered=sorted(pool,key=lambda p:(-p['retrieval_score'],p['source'],p['target']))
        lookup={frozenset((p['source'],p['target'])):(i+1,p) for i,p in enumerate(ordered)}
        vv=views[arm];vec=np.load(out/arm/'vectors.npy')
        bynode={nid:[i for i,v in enumerate(vv) if v['node_id']==nid] for nid in
                {c[s]['node_id'] for c in cases for s in ['A','B']}}
        diagnostics=[]
        for c in cases:
            a,b=c['A']['node_id'],c['B']['node_id'];hit=lookup.get(frozenset((a,b)))
            record=dict(case_id=c['suite_case_id'],initial_rank=hit[0] if hit else None,candidate=hit[1] if hit else None)
            if bynode[a] and bynode[b]:
                scores=vec[bynode[a]]@vec[bynode[b]].T;i,j=np.unravel_index(scores.argmax(),scores.shape)
                record.update(cosine=float(scores[i,j]),best_a=vv[bynode[a][i]],best_b=vv[bynode[b][j]])
            else:record['missing_views']=True
            diagnostics.append(record)
        jsonl(out/arm/'case_diagnostics.jsonl',diagnostics);case_diagnostics[arm]=diagnostics
    write(out/'summary.json',dict(complete=True,matched_budget=budget,results=summary,
        new_embeddings=len(newtexts),elapsed_seconds=time.monotonic()-started))
    write(out/'case_coverage.json',details)
    lines=['# Formula retrieval comparison','','Candidate inclusion only; no verified semantic edges.','',
           '| Arm | Initial positive /26 | Matched positive /26 | Negative candidates /27 | Native pairs |',
           '| --- | ---: | ---: | ---: | ---: |']
    for a in ARMS:
        s=summary[a];lines.append(f"| {a} | {s['initial']['POSITIVE_retrieved']} | {s['matched']['POSITIVE_retrieved']} | {s['matched']['NEGATIVE_retrieved']} | {s['native']['candidate_pairs']} |")
    lines+=['',f'Matched candidate count per arm: {budget}. Original formula and context sources stay separate.',
            'Source review required: adjacency is navigation; added context cannot prove equivalent formulas or identical losses.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(read(out/'summary.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run']);p.add_argument('--output',type=Path,default=OUT)
    args=p.parse_args();(prepare if args.command=='prepare' else run)(args.output)
