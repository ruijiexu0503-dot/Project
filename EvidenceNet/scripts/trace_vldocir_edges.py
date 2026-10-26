#!/usr/bin/env python3
"""Record query -> window/node -> edge -> page -> reranking paths."""
from __future__ import annotations
import argparse
from collections import defaultdict
import html
import json
from pathlib import Path
import numpy as np
from run_node_context_edges import rows, read, write, jsonl, sha
from evaluate_vldocir import evaluate, page

def encode(source, output, model_path):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True,padding_side='left')
    model=AutoModel.from_pretrained(model_path,local_files_only=True,torch_dtype=torch.bfloat16).cuda().eval()
    def vectors(records):
        result=[]
        for start in range(0,len(records),16):
            batch=tokenizer.pad({'input_ids':[r['input_ids'] for r in records[start:start+16]]},padding=True,return_tensors='pt').to('cuda')
            with torch.inference_mode():
                v=model(**batch).last_hidden_state[:,-1].float()
                result.append(torch.nn.functional.normalize(v,p=2,dim=1).cpu().numpy())
        return np.concatenate(result)
    q=rows(source/'query_tokens.jsonl'); windows=rows(source/'window_tokens.jsonl')
    qv=vectors(q); wv=vectors(windows)
    output.mkdir(parents=True,exist_ok=True)
    np.save(output/'query_window_scores.npy',qv@wv.T)
    write(output/'encoding.json',{'model':str(model_path),'model_config_sha256':sha(model_path/'config.json'),
        'windows':len(windows),'queries':len(q),'score_sha256':sha(output/'query_window_scores.npy'),
        'inputs_sha256':{p.name:sha(p) for p in sorted(source.glob('*')) if p.is_file()},
        'description':'Exact frozen unpadded input IDs; same 0.6B query retrieval encoder; node-edge encoder separately 8B.'})

def expand(qid, unit_hits, node_pages, edges, original):
    """One-hop, degree-capped navigation. No qrels/answers as arguments."""
    ranking=sorted(original,key=lambda p:(-original[p],p)); ranks={p:i+1 for i,p in enumerate(ranking)}
    scores={p:1/(60+ranks[p]) for p in ranking}; boosts=defaultdict(float)
    adjacency=defaultdict(list)
    for e in edges:
        adjacency[e['source']].append((e['target'],e)); adjacency[e['target']].append((e['source'],e))
    seeds=[]; per_page=defaultdict(int)
    for nid,hit in sorted(unit_hits.items(),key=lambda x:(-x[1]['score'],x[0])):
        if nid not in node_pages: continue
        pid=node_pages[nid]
        if ranks[pid]>10 or per_page[pid]>=2: continue
        seeds.append(nid);per_page[pid]+=1
        if len(seeds)>=20: break
    paths=[]; accepted=0
    for seed in seeds:
        options=sorted(adjacency[seed],key=lambda x:(-unit_hits.get(x[0],{'score':-1})['score'],x[0]))
        for index,(target,edge) in enumerate(options):
            sh=unit_hits[seed]; th=unit_hits.get(target)
            sp,tp=node_pages[seed],node_pages.get(target)
            reason='accepted';amount=0.0
            if index>=2: reason='per_seed_edge_budget'
            elif accepted>=20: reason='global_expansion_budget'
            elif th is None or tp is None: reason='target_missing_query_score_or_page'
            elif tp==sp: reason='same_page_no_new_page'
            elif ranks[tp]>100: reason='target_outside_query_top100_pages'
            elif th['score']<sh['score']-0.1: reason='target_query_similarity_too_low'
            else:
                amount=0.25/(60+ranks[sp])*max(0,min(1,th['score']))
                boosts[tp]=max(boosts[tp],amount);accepted+=1
            paths.append({'question_id':qid,'seed_node':seed,'seed_page':sp,'seed_page_rank':ranks[sp],
                'seed_hit':sh,'edge_id':edge['task_id'],'edge_source':edge['source'],'edge_target':edge['target'],
                'traversal':'undirected_navigation','target_node':target,'target_page':tp,'target_hit':th,
                'target_original_rank':ranks.get(tp),'decision':reason,'proposed_boost':amount,
                'edge_model_result':edge.get('model_result'),'evidence_propagation_allowed':False})
    scores={p:scores[p]+boosts[p] for p in ranking}
    final=sorted(scores,key=lambda p:(-scores[p],p));final_ranks={p:i+1 for i,p in enumerate(final)}
    for path in paths:
        tp=path['target_page'];path.update(target_final_rank=final_ranks.get(tp),applied_page_boost=boosts.get(tp,0))
    return scores, paths, [{'node_id':n,**unit_hits[n]} for n in seeds]

def report(source, output, edge_output):
    execution=read(output/'encoding.json')
    if sha(output/'query_window_scores.npy')!=execution['score_sha256']:raise ValueError('Score cache changed')
    for name,digest in execution['inputs_sha256'].items():
        if sha(source/name)!=digest:raise ValueError('Frozen query retrieval input changed')
    graph=read(edge_output/'graph/summary.json')
    if not graph['complete']:raise ValueError('Edge generation incomplete: preserve checkpoints; no final graph metrics yet')
    edges=rows(edge_output/'graph/related.jsonl'); nodes=rows(edge_output/'nodes.jsonl')
    npages={n['id']:(n['document'],str(n['page'])) for n in nodes}
    queries=rows(source/'queries.jsonl');gold=rows(source/'gold_evidence.jsonl')
    units=rows(source/'units.jsonl');wm=rows(source/'windows.jsonl');similarities=np.load(output/'query_window_scores.npy')
    by_query=defaultdict(dict)
    for r in rows(source/'baseline_scores.jsonl'):by_query[r['question_id']][page(r)]=r['score']
    base_rows=[];new_rows=[];traces=[];cards=[];maxdelta=0
    for qi,q in enumerate(queries):
        qid=q['question_id'];hits={};direct={}
        for wi,m in enumerate(wm):
            u=units[m['unit_input_line']-1];nid=u['unit_id'];pid=(u['document_id'],str(u['page_number']));score=float(similarities[qi,wi])
            if nid not in hits or score>hits[nid]['score']:
                hits[nid]={'score':score,'window_index':m['window_index'],'window_input_line':wi+1,'unit_input_line':m['unit_input_line']}
            direct[pid]=max(score,direct.get(pid,-1))
        if set(direct)!=set(by_query[qid]):raise ValueError('Baseline corpus mismatch')
        maxdelta=max(maxdelta,max(abs(direct[p]-by_query[qid][p]) for p in direct))
        augmented,paths,seeds=expand(qid,hits,npages,edges,direct)
        for pid,s in direct.items():base_rows.append({'question_id':qid,'document_id':pid[0],'page_number':int(pid[1]),'score':s})
        for pid,s in augmented.items():new_rows.append({'question_id':qid,'document_id':pid[0],'page_number':int(pid[1]),'score':s})
        before=sorted(direct,key=lambda p:(-direct[p],p));after=sorted(augmented,key=lambda p:(-augmented[p],p))
        trace={'question_id':qid,'question':q['question'],'seeds':seeds,'paths':paths,
               'before_top10':before[:10],'after_top10':after[:10]}
        traces.append(trace)
        cards.append('<article><h2>'+html.escape(q['question'])+'</h2><pre>'+html.escape(json.dumps(trace,ensure_ascii=False,indent=2))+'</pre></article>')
    corpus=set(by_query[queries[0]['question_id']])
    metrics={'recomputed_no_edge':evaluate(queries,gold,base_rows,corpus=corpus),
             'edge_navigation':evaluate(queries,gold,new_rows,corpus=corpus)}
    metrics.update(max_abs_score_difference_from_frozen=maxdelta,edge_count=len(edges),
        note='Compare matched recomputed no-edge and edge arms. Frozen scores separately audited; GPU batch shapes can change numerical results. Pilot 24 queries, not full-corpus. Navigation proposals only.')
    jsonl(output/'search_traces.jsonl',traces);jsonl(output/'edge_scores.jsonl',new_rows);jsonl(output/'no_edge_scores.jsonl',base_rows)
    write(output/'metrics.json',metrics)
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Edge 搜索路径</title><style>body{font:15px system-ui;margin:25px}pre{white-space:pre-wrap}article{border:1px solid #bbb;padding:15px;margin:20px 0}</style><h1>Query → Node → Edge → Page 搜索路径</h1>'+''.join(cards))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['encode','report']);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model',type=Path);p.add_argument('--edges',type=Path);a=p.parse_args()
    if a.stage=='encode':encode(a.source,a.output,a.model)
    else:report(a.source,a.output,a.edges)
