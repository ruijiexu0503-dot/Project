"""Frozen-score query-aware edge experiment; no document/edge embedding calls.

prepare is CPU-only; gate and the separate cached reranker need allocated GPUs.
Gold is read only by report, after all candidate decisions are frozen.
"""
from __future__ import annotations
import argparse
from collections import defaultdict, Counter
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
from time import monotonic
import numpy as np
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
from edge_source_roles import attach_source_roles, classify_node, audit_edge
import query_edge_gate as gate

SOURCE=ROOT/'migration/vldocir-edge-20261022/results'
TRACE=ROOT/'migration/vldocir_trace_inputs_20261023'
BASE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
OUT=ROOT/'EvidenceNet/output/query_edge_repair_v2_20261023'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def select_candidates(direct, paths, allowed=None, budget=20, core_size=10):
    """Keep a fixed dense core, reserve remainder for graph; never add a bonus."""
    if not 0 < core_size <= budget: raise ValueError('Invalid candidate budget')
    if len(direct)!=len(set(direct)):raise ValueError('Duplicate direct pages')
    core=list(direct[:core_size]); seen=set(core)
    rank={p:i for i,p in enumerate(direct)}
    extras={tuple(p['target_page']) for p in paths if allowed is None or p['id'] in allowed}
    if not extras<=set(rank):raise ValueError('Graph target outside frozen corpus')
    for page in sorted(extras-seen,key=lambda p:rank[p]):
        if len(core)>=budget: break
        core.append(page);seen.add(page)
    for page in direct:
        if len(core)>=budget: break
        if page not in seen: core.append(page);seen.add(page)
    return core

def prepare(out):
    if out.exists(): raise ValueError('Fresh output required')
    from tokenizers import Tokenizer
    tok_path=ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B/tokenizer.json'
    tokenizer=Tokenizer.from_file(str(tok_path))
    window_tokens=rows(TRACE/'window_tokens.jsonl'); windows=rows(TRACE/'windows.jsonl')
    units=rows(TRACE/'units.jsonl'); queries=rows(TRACE/'queries.jsonl')
    similarities=np.load(SOURCE/'search/query_window_scores.npy')
    if similarities.shape!=(len(queries),len(windows)) or not np.isfinite(similarities).all(): raise ValueError('Invalid score matrix')
    encoding=read(SOURCE/'search/encoding.json')
    if sha(SOURCE/'search/query_window_scores.npy')!=encoding['score_sha256']: raise ValueError('Changed cache')
    for name,h in encoding['inputs_sha256'].items():
        if sha(TRACE/name)!=h: raise ValueError('Changed query inputs: '+name)
    nodes={}; reps={}
    for n in rows(SOURCE/'nodes.jsonl'):
        key=(n['document'],n['page'])
        if key not in reps:reps[key]=read(BASE/'prepared'/key[0]/f'page_{int(key[1]):04d}'/'input_representation.json')
        nodes[n['id']]=attach_source_roles(n,reps[key])
    edges=rows(SOURCE/'graph/related.jsonl'); adj=defaultdict(list)
    audits={e['task_id']:audit_edge(e,nodes) for e in edges}
    for e in edges:
        adj[e['source']].append((e['target'],e));adj[e['target']].append((e['source'],e))
    traces={t['question_id']:t for t in rows(SOURCE/'search/search_traces.jsonl')}
    decoded={}
    def text(wi):
        if wi not in decoded:decoded[wi]=tokenizer.decode(window_tokens[wi]['input_ids'],skip_special_tokens=True)
        return decoded[wi]
    records=[]; contexts=[]; rerank={}
    for qi,q in enumerate(queries):
        qid=q['question_id']; hits={}; page_hits=defaultdict(list)
        for wi,w in enumerate(windows):
            u=units[w['unit_input_line']-1]; nid=u['unit_id']; score=float(similarities[qi,wi])
            if nid not in hits or score>hits[nid]['score']:
                hits[nid]={'score':score,'wi':wi,'page':(u['document_id'],str(u['page_number']))}
        for nid,h in hits.items():page_hits[h['page']].append((h['score'],nid,h['wi']))
        direct=sorted(page_hits,key=lambda p:(-max(h[0] for h in page_hits[p]),p))
        direct_scores={p:max(h[0] for h in page_hits[p]) for p in direct}
        paths=[]
        for seed in traces[qid]['seeds']:
            nid=seed['node_id']; sh=hits[nid]
            if sh['wi']+1!=seed['window_input_line']:raise ValueError('Seed window mismatch')
            options=sorted(adj[nid],key=lambda p:(-hits[p[0]]['score'],p[0]))[:2]
            for target,e in options:
                th=hits[target]
                if th['page']==sh['page']:continue
                side='A' if e['source']==nid else 'B'; other='B' if side=='A' else 'A'
                anchors=e['model_result']['anchors']
                anchor=lambda s:'\n\n'.join(x['quote'] for x in anchors[s] if x['kind'] in {'ORIGINAL_TEXT','ORIGINAL_TABLE_ROW'})
                source_role=classify_node(nodes[nid]);target_role=classify_node(nodes[target])
                record={'query':q['question'],'seed_hit':{'text':text(sh['wi'])},
                    'source':{'anchor':anchor(side),'role':'BIBLIOGRAPHY' if source_role['route']=='reference_review' else 'UNKNOWN'},
                    'target':{'anchor':anchor(other),'role':'BIBLIOGRAPHY' if target_role['route']=='reference_review' else 'UNKNOWN'}}
                rid=digest([qid,e['task_id'],nid,target])
                path={'id':rid,'question_id':qid,'edge_id':e['task_id'],'seed_node':nid,'target_node':target,
                      'seed_page':sh['page'],'target_page':th['page'],'seed_window_line':sh['wi']+1,
                      'source_role_route':audits[e['task_id']]['route'],'input':record,
                      'prompt_sha256':digest(gate.make_prompt(record))}
                paths.append(path);records.append(path)
        candidates=select_candidates(direct,paths)
        # Include dense top20 for fill after filtering and ALL possible graph targets.
        pool=set(direct[:20])|{tuple(p['target_page']) for p in paths}
        evidence={}
        for pid in sorted(pool):
            evidence[json.dumps(pid)]=[]
            for _,nid,wi in sorted(page_hits[pid],key=lambda x:(-x[0],x[1]))[:2]:
                rid=digest([qid,wi]);evidence[json.dumps(pid)].append(rid)
                rerank[rid]={'id':rid,'query':q['question'],'text':text(wi)}
        contexts.append({'question_id':qid,'question':q['question'],'direct_ranking':direct,
                         'direct_scores':[direct_scores[p] for p in direct],
                         'path_ids':[p['id'] for p in paths],'page_reranker_ids':evidence,
                         'raw_graph_candidates':candidates})
    jsonl(out/'gate_inputs.jsonl',records);jsonl(out/'query_contexts.jsonl',contexts)
    jsonl(out/'reranker_inputs.jsonl',list(rerank.values()))
    write(out/'role_audit.json',{'counts':dict(Counter(a['route'] for a in audits.values())), 'edges':audits})
    write(out/'protocol.json',{'candidate_budget':20,'direct_core':10,'per_seed_edges':2,'page_windows':2,
        'online_document_embedding_calls':0,'edge_bonus':0,'new_graph_edges':0,
        'reranker':'bge-reranker-v2-m3 text cross-encoder; same cached window text for all arms',
        'gate':'Qwen original text/table anchors; omitted visual-only evidence must abstain',
        'arms':['cached_dense','dense_rerank','graph_rerank','role_clean_graph_rerank','query_gate_graph_rerank'],
        'limits':'Diagnostic inspected 24-query pilot; source-role review is not semantic correctness. '
                 'Bridge allowed only for bounded one-hop candidate discovery. No claims of support.',
        'gate_tasks':len(records),'reranker_tasks':len(rerank)})
    # Evaluation snapshots are never passed to either model or candidate selection.
    for name in ('queries.jsonl','gold_evidence.jsonl'):
        shutil.copyfile(TRACE/name,out/('eval_'+name))
    files=['gate_inputs.jsonl','query_contexts.jsonl','reranker_inputs.jsonl','role_audit.json','protocol.json',
           'eval_queries.jsonl','eval_gold_evidence.jsonl']
    code=[Path(__file__).with_name(name) for name in ('run_query_edge_repair.py','query_edge_gate.py',
          'edge_source_roles.py','run_cached_query_reranker.py','evaluate_vldocir.py','evaluate_vldocir_ap.py',
          'run_node_context_edges.py','dolphin_text.py')]
    write(out/'manifest.json',{'files':{n:sha(out/n) for n in files},
        'code':{p.name:sha(p) for p in code},
        'sources':{str(p.relative_to(ROOT)):sha(p) for p in [SOURCE/'graph/related.jsonl',SOURCE/'nodes.jsonl',tok_path]}})
    print(read(out/'protocol.json'))

def check(out):
    m=read(out/'manifest.json')
    for n,h in m['files'].items():
        if sha(out/n)!=h:raise ValueError('Changed input '+n)
    for n,h in m['code'].items():
        if sha(Path(__file__).with_name(n))!=h:raise ValueError('Changed code '+n)

def run_gate(out,model,minutes):
    if minutes<=0:raise ValueError('Positive time budget required')
    with (out/'.gate.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run_gate_locked(out,model,minutes)

def run_gate_locked(out,model,minutes):
    check(out)
    entries=rows(out/'gate_inputs.jsonl'); dest=out/'gate_predictions.jsonl'
    existing=rows(dest) if dest.exists() else []
    if len({x['id'] for x in existing})!=len(existing):raise ValueError('Duplicate predictions')
    lookup={e['id']:e for e in entries}
    for p in existing:
        if p['id'] not in lookup or p['prompt_sha256']!=lookup[p['id']]['prompt_sha256']:raise ValueError('Stale prediction')
        if p['valid']:gate.validate(p['result'],lookup[p['id']]['input'])
    if len(existing)==len(entries):print('Gate already complete');return
    from evidence_graph.llm_client import create_llm
    model_config=sha(model/'config.json')
    execution=out/'gate_execution.json'
    if execution.exists() and (read(execution)['model_config_sha256']!=model_config or
                              read(execution)['input_manifest']!=sha(out/'manifest.json')):raise ValueError('Changed model/input')
    write(execution,{'model':str(model),'model_config_sha256':model_config,'input_manifest':sha(out/'manifest.json'),
                     'max_new_tokens':700,'sampling':False,'thinking':False})
    started=monotonic(); llm=create_llm({'provider':'transformers','model':str(model),'dtype':'bfloat16',
                         'require_cuda':True,'enable_thinking':False,'max_new_tokens':700,
                         'device_map':'balanced','max_memory':{i:'26GiB' for i in range(4)}})
    done={p['id'] for p in existing}
    for e in entries:
        if e['id'] in done:continue
        if monotonic()-started>minutes*60:break
        attempts=[];result=None
        for _ in range(2):
            raw=None
            try:
                generation=llm.generate_raw_with_images('Judge source-grounded query navigation. JSON only.',gate.make_prompt(e['input']),[],700)
                raw=generation.raw
                from evidence_graph.llm_client import extract_json
                result=gate.validate(extract_json(raw),e['input']);attempts.append({'raw':raw});break
            except (ValueError,TypeError,KeyError) as error:attempts.append({'raw':raw,'error':str(error)})
        existing.append({'id':e['id'],'prompt_sha256':e['prompt_sha256'],'valid':result is not None,'result':result,'attempts':attempts})
        jsonl(dest,existing);print(f'Gate {len(existing)}/{len(entries)}',flush=True)

def report(out):
    check(out)
    from evaluate_vldocir import evaluate
    from evaluate_vldocir_ap import average_precision
    from run_cached_query_reranker import load_inputs, load_scores
    paths=rows(out/'gate_inputs.jsonl'); context=rows(out/'query_contexts.jsonl')
    predictions=rows(out/'gate_predictions.jsonl') if (out/'gate_predictions.jsonl').exists() else []
    reranker_inputs=load_inputs(out/'reranker_inputs.jsonl')
    reranked=load_scores(out/'reranker_scores.jsonl',reranker_inputs)
    if len(predictions)!=len(paths) or len(reranked)!=len(reranker_inputs):
        status={'complete':False,'gate_processed':len(predictions),'gate_total':len(paths),'reranker_processed':len(reranked),
                'reranker_total':len(reranker_inputs)};write(out/'status.json',status);print(status);return
    pred={p['id']:p for p in predictions};pathmap={p['id']:p for p in paths}
    if len(pred)!=len(paths) or set(pred)!=set(pathmap):raise ValueError('Gate ID mismatch')
    for rid,p in pred.items():
        if p['prompt_sha256']!=pathmap[rid]['prompt_sha256']:raise ValueError('Gate hash mismatch')
        if p['valid']:gate.validate(p['result'],pathmap[rid]['input'])
    score={p['id']:p['score'] for p in reranked}
    expected={p['id'] for p in reranker_inputs}
    if len(score)!=len(reranked) or set(score)!=expected or not all(np.isfinite(v) for v in score.values()):raise ValueError('Reranker ID/score mismatch')
    all_rows=defaultdict(list); traces=[]; candidate_changes=Counter()
    # Candidate construction precedes gold loading.
    for q in context:
        direct=[tuple(p) for p in q['direct_ranking']]; pp=[pathmap[i] for i in q['path_ids']]
        clean={p['id'] for p in pp if p['source_role_route']=='semantic'}
        accepted={i for i in clean if pred[i]['valid'] and pred[i]['result']['role'] in gate.NAVIGATION_ROLES}
        candidates={'dense_rerank':direct[:20],'graph_rerank':select_candidates(direct,pp),
            'role_clean_graph_rerank':select_candidates(direct,pp,clean),
            'query_gate_graph_rerank':select_candidates(direct,pp,accepted)}
        rankings={'cached_dense':direct[:20]}
        all_rows['cached_dense'].extend({'question_id':q['question_id'],'document_id':p[0],
                                        'page_number':int(p[1]),'score':-i} for i,p in enumerate(direct))
        for arm,selected in candidates.items():
            candidate_changes[arm]+=int(set(selected)!=set(direct[:20]))
            rank=sorted(selected,key=lambda p:(-max(score[i] for i in q['page_reranker_ids'][json.dumps(p)]),p))
            rank+= [p for p in direct if p not in set(selected)]
            rankings[arm]=rank[:20]
            all_rows[arm].extend({'question_id':q['question_id'],'document_id':p[0],'page_number':int(p[1]),'score':-i}
                                for i,p in enumerate(rank))
        traces.append({'question_id':q['question_id'],'question':q['question'],'rankings':rankings,
                       'candidates':candidates,'accepted_path_ids':sorted(accepted),
                       'candidate_additions':{arm:[p for p in selected if p not in set(direct[:20])] for arm,selected in candidates.items()},
                       'paths':[{**p,'gate_prediction':pred[p['id']]} for p in pp]})
    queries=rows(out/'eval_queries.jsonl');gold=rows(out/'eval_gold_evidence.jsonl');g=defaultdict(set)
    for r in gold:g[r['question_id']].add((r['document_id'],str(r['page_number'])))
    metrics={};details={}
    for arm,records in all_rows.items():
        evaluated=evaluate(queries,gold,records)
        m=evaluated['macro_six_types']
        if m is None:raise ValueError('Expected all six question types')
        details[arm]=evaluated['per_query']
        groups=defaultdict(list)
        for q,t in zip(queries,traces):
            assert q['question_id']==t['question_id']
            ap=average_precision([tuple(p) for p in t['rankings'][arm]],g[q['question_id']],5)
            groups[q['question_type']].append(ap);details[arm][q['question_id']]['AP@5']=ap
        m['mAP@5']=sum(sum(v)/len(v) for v in groups.values())/len(groups);metrics[arm]=m
    jsonl(out/'search_paths.jsonl',traces)
    paired={}
    for arm in metrics:
        if arm=='cached_dense':continue
        control='cached_dense' if arm=='dense_rerank' else 'dense_rerank'
        deltas=[details[arm][qid]['AP@5']-details[control][qid]['AP@5'] for qid in details[arm]]
        paired[arm]={'control':control,'AP@5_wins':sum(d>1e-12 for d in deltas),
                     'AP@5_losses':sum(d< -1e-12 for d in deltas),'AP@5_ties':sum(abs(d)<=1e-12 for d in deltas),
                     'metric_deltas':{k:metrics[arm][k]-metrics[control][k] for k in metrics[arm]}}
    write(out/'results.json',{'complete':True,'metrics':metrics,'per_query':details,'paired':paired,
                             'candidate_set_changes_vs_dense20':dict(candidate_changes),
                             'gate_roles':dict(Counter(p['result']['role'] if p['valid'] else 'INVALID' for p in predictions)),
                             'gate_invalid':sum(not p['valid'] for p in predictions),
                             'protocol':read(out/'protocol.json')})
    write(out/'status.json',{'complete':True,'gate_processed':len(predictions),'reranker_processed':len(reranked)})
    print(metrics)

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','gate','report']);p.add_argument('--output',type=Path,default=OUT)
    p.add_argument('--model',type=Path,default=ROOT/'external/models/Qwen3.5-35B-A3B');p.add_argument('--minutes',type=int,default=45)
    a=p.parse_args()
    if a.stage=='prepare':prepare(a.output)
    elif a.stage=='gate':run_gate(a.output,a.model,a.minutes)
    else:report(a.output)

if __name__=='__main__':main()
