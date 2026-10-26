"""Run actual offline edge construction, reading flows and matched page retrieval.

Frozen Dolphin/hybrid nodes are upstream cache, not a new node-generation result.
prepare/worker/collect never read evaluation questions or relevance labels.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import copy
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
import vldocir_candidate_comparison as candidates
import vldocir_reading_backbone as backbone
import run_vldocir_edge_pipeline as adapter
import run_routed_edge_context as verifier
import edge_embedding_records as records

BASE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
SOURCE=ROOT/'migration/vldocir-edge-20261022/results'
TRACE=ROOT/'migration/vldocir_trace_inputs_20261023'
COL=ROOT/'EvidenceNet/output/vldocir_colnomic_7b_20261016'
ARMS=('node','reading','sparse_pipeline','all_node_pipeline','ColNomic_BGE')
QUERY_PREFIX='Instruct: Retrieve document-edge evidence useful for answering the query\nQuery: '


def prepare(out, model, encoder, shards=16):
    if (out/'plan.json').exists():
        validate_plan(out); return read(out/'plan.json')
    adapted=out/'adapted'
    if not adapted.exists():
        subprocess.run([sys.executable,str(Path(__file__).with_name('prepare_vldocir_edge_adapter.py')),
            '--nodes',str(BASE/'nodes'),'--prepared',str(BASE/'prepared'),
            '--pages',str(BASE/'pilot/image_pages.jsonl'),'--output',str(adapted)],check=True)
    candidates.build(SOURCE,adapted,out/'candidates',encoder,k=1)
    union=out/'union_pipeline'
    if not union.exists(): adapter.edge.prepare(union,adapted/'nodes.jsonl',adapted/'policies.json','qwen3-8b',encoder)
    adapter.edge.artifact(union,'node_candidates.jsonl',rows(out/'candidates/union.jsonl'))
    adapter.edge.artifact(union,'reference_candidates.jsonl',rows(out/'candidates/reference_candidates.jsonl'))
    adapter.edge.prepare_verifier(union,model)
    if rows(union/'verifier/preparation_errors.jsonl'):
        raise ValueError('verifier preparation failed; inspect errors before scoring')
    entries=rows(union/'verifier/control/inputs.jsonl')
    # Historical responses are NOT silently reused after changing the source-role adapter.
    for i in range(shards):
        dest=out/'verifier_shards'/str(i)
        jsonl(dest/'control/inputs.jsonl',entries[i::shards])
        jsonl(dest/'reference.jsonl',[])
        protocol=read(union/'verifier/protocol.json')
        protocol.update(pairs=len(entries[i::shards]),shard=i,shards=shards)
        write(dest/'protocol.json',protocol); verifier.freeze(dest)
    docs=sorted({n['document'] for n in rows(adapted/'nodes.jsonl')})
    plan={'shards':shards,'documents':docs,'worker_documents':{str(i):docs[i::shards] for i in range(shards)},
        'pairs':len(entries),'per_node_k':1,'scope':'inspected 24-query/518-page pilot',
        'upstream':'frozen source-audited Dolphin + hybrid-v2 node generation cache',
        'reading':'current Qwen article membership and reading flows, single-document profile',
        'edge_generation':'same current multimodal verifier on union of two candidate selectors',
        'edge_retrieval':'same 8B AB/BA pair embedding for sparse and every-node graphs',
        'forced_semantic_edges':False,'labels_visible_during_construction':False,
        'code':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),Path(candidates.__file__),Path(backbone.__file__),
             ROOT/'EvidenceNet/scripts/run_hybrid_article_clustering.py',ROOT/'EvidenceNet/evidence_graph/hybrid_article_clustering.py',
             *adapter.edge.CODE]},
        'inputs':{str(p.relative_to(ROOT)):sha(p) for p in [adapted/'nodes.jsonl',adapted/'policies.json',out/'candidates/manifest.json',
             BASE/'prepared/manifest.json',SOURCE/'embedding_manifest.json']}}
    write(out/'plan.json',plan); return plan


def validate_plan(out):
    plan=read(out/'plan.json')
    for collection in ('code','inputs'):
        for filename,h in plan[collection].items():
            if sha(ROOT/filename)!=h: raise ValueError('changed plan '+filename)
    return plan


def reading_run(out, model, document, task=None):
    """Current prompts/materializer; tested four-GPU placement for this cluster."""
    validate_plan(out)
    import run_hybrid_article_clustering as article
    from evidence_graph.llm_client import create_llm
    dest=out/'smoke_articles' if task else out/'articles'/document
    command=['run','--source',str(BASE/'prepared'),'--nodes',str(BASE/'nodes'),
        '--output',str(dest),'--model',str(model),'--device','cuda','--single-document',document]
    command+=['--include-task',task] if task else ['--include-document',document]
    args=article.parser().parse_args(command);article.prepare(args);article.check(dest)
    import torch
    if torch.cuda.device_count()<4: raise RuntimeError('four GPUs required for reading')
    llm=create_llm(dict(provider='transformers',model=str(model),dtype='bfloat16',
        device_map='balanced',max_memory={**{i:'26GiB' for i in range(4)},'cpu':'0GiB'},
        require_cuda=True,enable_thinking=False))
    write(dest/'execution_profile.json',{'placement':'balanced','per_gpu_weights_max':'26GiB',
        'model_config_sha256':sha(model/'config.json'),'article_code_sha256':sha(Path(article.__file__))})
    result=article.materialize(dest,llm)
    if not read(dest/'article_graph_manifest.json')['reading_ready']:
        raise RuntimeError('reading flow unresolved for '+document)
    return result


def worker(out, model, index, minutes=420):
    plan=validate_plan(out)
    if not 0<=index<plan['shards']: raise ValueError('invalid worker index')
    shard=out/'verifier_shards'/str(index)
    original=verifier.ARMS
    try:
        verifier.ARMS=('control',)
        verifier.run(shard,model,ROOT,minutes)
    finally: verifier.ARMS=original
    if not read(shard/'summary.json')['complete']:
        raise RuntimeError('incomplete verifier shard; resume same worker, no partial metrics')
    import gc, torch
    gc.collect(); torch.cuda.empty_cache()
    # Each document has its own checkpoints; independent workers cannot collide.
    for doc in plan['worker_documents'][str(index)]:
        command=[sys.executable,str(Path(__file__)),'reading',
            '--output',str(out),'--model',str(model),'--document',doc]
        subprocess.run(command,check=True)
        if not read(out/'articles'/doc/'article_graph_manifest.json')['reading_ready']:
            raise RuntimeError('reading flow unresolved for '+doc)
    write(out/'workers'/f'{index}.json',{'complete':True,'shard':index,'documents':plan['worker_documents'][str(index)]})


def smoke(out,model):
    """Check one real verifier subset and one real reading page; never score this as a full run."""
    plan=validate_plan(out)
    dest=out/'smoke_verifier'
    if not (dest/'manifest.json').exists():
        entries=rows(out/'union_pipeline/verifier/control/inputs.jsonl')
        # Cover prose/formula/visual routes deterministically without labels.
        chosen=[]
        for group in ('prose','formula','visual_table'):
            chosen.extend([r for r in entries if r['routing']['group']==group][:4])
        jsonl(dest/'control/inputs.jsonl',chosen);jsonl(dest/'reference.jsonl',[])
        p=read(out/'union_pipeline/verifier/protocol.json');p.update(pairs=len(chosen),smoke=True)
        write(dest/'protocol.json',p);verifier.freeze(dest)
    original=verifier.ARMS
    try:
        verifier.ARMS=('control',);verifier.run(dest,model,ROOT,15)
    finally:verifier.ARMS=original
    if not read(dest/'summary.json')['complete']: raise RuntimeError('smoke verifier incomplete')
    import gc, torch
    gc.collect(); torch.cuda.empty_cache()
    doc=plan['documents'][0]
    task=sorted(t for t in read(BASE/'prepared/manifest.json')['tasks'] if doc in Path(t).parts)[0]
    subprocess.run([sys.executable,str(Path(__file__)),'reading',
        '--output',str(out),'--model',str(model),'--document',doc,'--task',task],check=True)
    if not read(out/'smoke_articles/article_graph_manifest.json')['reading_ready']:
        raise RuntimeError('smoke reading unresolved')
    write(out/'smoke_status.json',{'complete':True,'quality_evaluated':False})


def collect(out):
    plan=validate_plan(out); cache={}
    for i in range(plan['shards']):
        if not read(out/'workers'/f'{i}.json')['complete']: raise ValueError('unfinished worker')
        root=out/'verifier_shards'/str(i);verifier.verify(root)
        inputs=rows(root/'control/inputs.jsonl'); pp=verifier.checked_cache(root,{'control':inputs})
        if len(inputs)!=len(pp): raise ValueError('missing verifier predictions')
        if set(pp)&set(cache): raise ValueError('overlapping verifier shards')
        cache.update(pp)
    union=out/'union_pipeline'; entries=rows(union/'verifier/control/inputs.jsonl')
    if len(cache)!=len(entries): raise ValueError('union cache incomplete')
    jsonl(union/'verifier/cache.jsonl',[cache[e['inference_key']] for e in entries])
    adapter.edge.export(union)
    if not read(union/'graph/summary.json')['complete']: raise ValueError('graph incomplete')
    arm_keys={arm:{candidates.allocation.key(p) for p in rows(out/'candidates'/(arm+'.jsonl'))}
              for arm in ('current_sparse','all_node')}
    counts={}
    for arm,keys in arm_keys.items():
        counts[arm]={}
        for bucket in ('related','review','rejected'):
            selected=[p for p in rows(union/'graph'/(bucket+'.jsonl')) if candidates.allocation.key(p) in keys]
            jsonl(out/'graphs'/arm/(bucket+'.jsonl'),selected);counts[arm][bucket]=len(selected)
        if sum(counts[arm].values())!=len(keys): raise ValueError('lost arm decision')
    reading=backbone.build(out/'adapted/nodes.jsonl',[out/'articles'/doc for doc in plan['documents']],out/'graphs')
    write(out/'graph_summary.json',{'complete':True,'arms':counts,'reading':reading,'candidates':read(out/'candidates/coverage.json')})
    files=[out/'graphs/reading_edges.jsonl',out/'graph_summary.json']+[out/'graphs'/a/'related.jsonl' for a in arm_keys]
    write(out/'graph_manifest.json',{'files':{str(p.relative_to(out)):sha(p) for p in files}})


def check_graph(out):
    validate_plan(out)
    for name,h in read(out/'graph_manifest.json')['files'].items():
        if sha(out/name)!=h: raise ValueError('changed graph '+name)


def encode_edges(out,model):
    check_graph(out)
    from compare_edge_embedding_models import embed,load_tokenizer
    tokenizer=load_tokenizer(model,'left')
    nodes={n['id']:n for n in rows(out/'adapted/nodes.jsonl')}; graph={}
    for arm in ('current_sparse','all_node'):
        for edge in rows(out/'graphs'/arm/'related.jsonl'): graph[edge['task_id']]=edge
    texts=[]; encoded=[]
    for edge_id,edge in sorted(graph.items()):
        r=records.build_record(edge,nodes,'semantic'); sides={}
        for side in ('A','B'):
            raw='\n\n'.join(s['text'] for s in r['endpoints'][side]['spans'])
            ids=tokenizer.encode(raw,add_special_tokens=False)
            sides[side]=tokenizer.decode(ids[:192],skip_special_tokens=True)
        for order in ('AB','BA'):
            text='[ENDPOINT A]\n'+sides[order[0]]+'\n[ENDPOINT B]\n'+sides[order[1]]
            if len(tokenizer.encode(text,add_special_tokens=True))>512: raise ValueError('pair too long')
            texts.append(text);encoded.append({'edge_id':edge_id,'order':order,'text':text})
    jsonl(out/'pair_inputs.jsonl',encoded)
    if texts: vectors,execution=embed(texts,model,6,512,'cuda','last_token','left')
    else: vectors=np.empty((0,0),dtype=np.float32); execution={'empty_graph':True}
    np.save(out/'pair_vectors.npy',vectors)
    write(out/'pair_manifest.json',{'model_files':{p.name:sha(p) for p in model.glob('*.json')},
        'graph_manifest_sha256':sha(out/'graph_manifest.json'),'inputs_sha256':sha(out/'pair_inputs.jsonl'),
        'vectors_sha256':sha(out/'pair_vectors.npy'),'execution':execution})


def select_pages(direct, reading_pages, edge_pages, budget=20, core=10):
    selected=list(direct[:core]);seen=set(selected); decisions=[]
    for lane,items,limit in [('reading',reading_pages,core+3),('semantic',edge_pages,budget)]:
        for page,path in items:
            if page not in direct: raise ValueError('page outside corpus')
            reason='already_selected' if page in seen else 'budget_full' if len(selected)>=limit else 'added'
            if reason=='added':selected.append(page);seen.add(page)
            decisions.append(dict(path,lane=lane,target_page=page,decision=reason))
    for p in direct:
        if len(selected)>=budget:break
        if p not in seen:selected.append(p);seen.add(p)
    if len(selected)!=min(budget,len(direct)) or len(set(selected))!=len(selected): raise ValueError('page budget')
    return selected,decisions


def retrieve(out,model):
    check_graph(out)
    from compare_edge_embedding_models import embed
    from tokenizers import Tokenizer
    queries=rows(TRACE/'queries.jsonl'); units=rows(TRACE/'units.jsonl'); windows=rows(TRACE/'windows.jsonl')
    qm=lambda rr:{r['question_id']:r['question'] for r in rr}
    if qm(queries)!=qm(rows(COL/'queries.jsonl')): raise ValueError('ColNomic query mismatch')
    pages=lambda pp:{(p['document_id'],str(p['page_number'])):p['sha256'] for p in pp}
    corpus=pages(rows(BASE/'pilot/image_pages.jsonl'))
    if corpus!=pages(rows(COL/'pages.jsonl')): raise ValueError('ColNomic corpus mismatch')
    pm=read(out/'pair_manifest.json')
    if pm['graph_manifest_sha256']!=sha(out/'graph_manifest.json') or pm['inputs_sha256']!=sha(out/'pair_inputs.jsonl') or pm['vectors_sha256']!=sha(out/'pair_vectors.npy'):
        raise ValueError('pair cache mismatch')
    if pm['model_files']!={p.name:sha(p) for p in model.glob('*.json')}: raise ValueError('query/edge encoder mismatch')
    qvec,execution=embed([QUERY_PREFIX+q['question'] for q in queries],model,6,512,'cuda','last_token','left')
    np.save(out/'query_vectors.npy',qvec);write(out/'query_encoding.json',execution)
    pair_rows=rows(out/'pair_inputs.jsonl');edge_ids=[r['edge_id'] for r in pair_rows[::2]]
    pair=np.load(out/'pair_vectors.npy',allow_pickle=False)
    sims=np.load(SOURCE/'search/query_window_scores.npy',allow_pickle=False)
    encoding=read(SOURCE/'search/encoding.json')
    if sha(SOURCE/'search/query_window_scores.npy')!=encoding['score_sha256']: raise ValueError('dense score mismatch')
    for name,h in encoding['inputs_sha256'].items():
        if sha(TRACE/name)!=h: raise ValueError('dense inputs changed '+name)
    if sims.shape!=(len(queries),len(windows)): raise ValueError('dense score shape')
    nodes={n['id']:n for n in rows(out/'adapted/nodes.jsonl')}
    graph={};arm_ids={}
    for arm in ('current_sparse','all_node'):
        es=rows(out/'graphs'/arm/'related.jsonl');arm_ids[arm]={e['task_id'] for e in es};graph.update({e['task_id']:e for e in es})
    adjacency=defaultdict(list)
    for e in rows(out/'graphs/reading_edges.jsonl'):adjacency[e['source']].append(e)
    col=defaultdict(dict)
    for r in rows(COL/'scores.jsonl'):
        p=(r['document_id'],str(r['page_number']));qid=r['question_id']
        if p in col[qid] or p not in corpus: raise ValueError('ColNomic duplicate/unknown page')
        col[qid][p]=r['score']
    if set(col)!=set(qm(queries)) or any(set(s)!=set(corpus) for s in col.values()): raise ValueError('ColNomic incomplete scores')
    tokenizer=Tokenizer.from_file(str(ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B/tokenizer.json'))
    wt=rows(TRACE/'window_tokens.jsonl');selections=[];paths=[];tasks={};page_ids=[];contexts=[]
    for qi,q in enumerate(queries):
        qid=q['question_id'];per_page=defaultdict(list);hits={}
        for wi,w in enumerate(windows):
            u=units[w['unit_input_line']-1];p=(u['document_id'],str(u['page_number']));s=float(sims[qi,wi])
            per_page[p].append((s,wi));nid=u['unit_id']
            if nid not in hits or s>hits[nid][0]:hits[nid]=(s,wi,p)
        direct=sorted(per_page,key=lambda p:(-max(s for s,_ in per_page[p]),p))
        if set(direct)!=set(corpus):raise ValueError('dense corpus mismatch')
        seeds=[];count=Counter()
        for nid,(s,wi,p) in sorted(hits.items(),key=lambda x:(-x[1][0],x[0])):
            if nid in nodes and p in direct[:10] and count[p]<2:
                seeds.append(nid);count[p]+=1
        reading=[]
        for nid in seeds:
            for e in sorted(adjacency[nid],key=lambda e:(e['type'],e['target'])):
                t=nodes[e['target']];p=(t['document'],str(t['page']))
                reading.append((p,{'seed_node':nid,'target_node':e['target'],'edge_type':e['type'],'source_page':hits[nid][2]}))
        reading.sort(key=lambda x:(direct.index(x[0]),x[1]['seed_node'],x[1]['target_node']))
        scores=np.maximum(pair[::2]@qvec[qi],pair[1::2]@qvec[qi]) if edge_ids else []
        arms={'node':(direct[:20],[]),'reading':select_pages(direct,reading,[])}
        for target,arm in [('sparse_pipeline','current_sparse'),('all_node_pipeline','all_node')]:
            chosen=sorted((i for i,eid in enumerate(edge_ids) if eid in arm_ids[arm]),key=lambda i:(-float(scores[i]),edge_ids[i]))[:100]
            extra=[]
            for rank,i in enumerate(chosen,1):
                e=graph[edge_ids[i]]
                ep={(nodes[e[s]]['document'],str(nodes[e[s]]['page'])) for s in ('source','target')}
                for p in sorted(ep,key=lambda p:(direct.index(p),p)):
                    extra.append((p,{'edge_id':edge_ids[i],'edge_rank':rank,'edge_score':float(scores[i]),'edge_type':'RELATED','source_node':e['source'],'target_node':e['target']}))
            arms[target]=select_pages(direct,reading,extra)
        colrank=sorted(col[qid],key=lambda p:(-col[qid][p],p));arms['ColNomic_BGE']=(colrank[:20],[])
        union=set()
        for arm,(pp,trace) in arms.items():
            union.update(pp);selections.append({'question_id':qid,'arm':arm,'pages':pp})
            paths.append({'question_id':qid,'arm':arm,'seed_nodes':seeds,'selected_pages':pp,'paths':trace})
        mapping={}
        for p in sorted(union):
            ids=[]
            for _,wi in sorted(per_page[p],key=lambda x:(-x[0],x[1]))[:2]:
                rid=records.digest([qid,wi]);ids.append(rid)
                tasks[rid]={'id':rid,'query':q['question'],'text':tokenizer.decode(wt[wi]['input_ids'],skip_special_tokens=True)}
            mapping[json.dumps(p)]=ids
        page_ids.append({'question_id':qid,'pages':mapping})
        contexts.append({'question_id':qid,'direct':direct,'ColNomic':colrank})
    jsonl(out/'query_candidates.jsonl',selections);jsonl(out/'search_paths.jsonl',paths)
    jsonl(out/'reranker_inputs.jsonl',tasks.values());jsonl(out/'page_reranker_ids.jsonl',page_ids);jsonl(out/'ranking_contexts.jsonl',contexts)
    files=[out/n for n in ('query_candidates.jsonl','search_paths.jsonl','reranker_inputs.jsonl','page_reranker_ids.jsonl','ranking_contexts.jsonl')]
    write(out/'retrieval_manifest.json',{'files':{p.name:sha(p) for p in files},'queries_sha256':sha(TRACE/'queries.jsonl'),
        'ColNomic_scores_sha256':sha(COL/'scores.jsonl'),'corpus_images_equal':True,'query_text_equal':True,
        'budget':20,'core':10,'reading_extra_max':3,'semantic_edges_scanned':100,'reranker_tasks':len(tasks),
        'same_page_reading_limitation':'NEXT traces are retained even when page deduplication adds no page; shared page text is held fixed.'})


def report(out):
    from run_cached_query_reranker import load_inputs,load_scores
    from evaluate_vldocir import evaluate,page
    from evaluate_vldocir_ap import average_precision
    check_graph(out); rm=read(out/'retrieval_manifest.json')
    for name,h in rm['files'].items():
        if sha(out/name)!=h:raise ValueError('changed retrieval artifact')
    if sha(TRACE/'queries.jsonl')!=rm['queries_sha256']:raise ValueError('changed query text')
    tasks=load_inputs(out/'reranker_inputs.jsonl')
    scores={s['id']:s['score'] for s in load_scores(out/'reranker_scores.jsonl',tasks,require_complete=True)}
    queries=rows(TRACE/'queries.jsonl');gold=rows(TRACE/'gold_evidence.jsonl')
    corpus={page(p) for p in rows(BASE/'pilot/image_pages.jsonl')}
    contexts={r['question_id']:r for r in rows(out/'ranking_contexts.jsonl')}
    mapping={r['question_id']:r['pages'] for r in rows(out/'page_reranker_ids.jsonl')}
    runs=defaultdict(list);ranks=defaultdict(dict)
    for c in rows(out/'query_candidates.jsonl'):
        qid,arm=c['question_id'],c['arm'];pp=[tuple(p) for p in c['pages']]
        ordered=sorted(pp,key=lambda p:(-max(scores[i] for i in mapping[qid][json.dumps(p)]),p))
        tail=contexts[qid]['ColNomic' if arm=='ColNomic_BGE' else 'direct']
        ranks[arm][qid]=ordered+[tuple(p) for p in tail if tuple(p) not in set(ordered)]
    for q in queries:
        qid=q['question_id']
        ranks['ColNomic_raw'][qid]=[tuple(p) for p in contexts[qid]['ColNomic']]
        ranks['node_raw'][qid]=[tuple(p) for p in contexts[qid]['direct']]
    g=defaultdict(set)
    for r in gold:g[r['question_id']].add(page(r))
    metrics={};per_query={}
    for arm,qq in ranks.items():
        for qid,pp in qq.items():
            if len(pp)!=len(corpus) or set(pp)!=corpus:raise ValueError('incomplete final ranking')
            runs[arm].extend(dict(question_id=qid,document_id=p[0],page_number=int(p[1]),score=-i) for i,p in enumerate(pp))
        result=evaluate(queries,gold,runs[arm],corpus=corpus)
        for k in (3,5,10,None):
            key='AP@'+str(k) if k is not None else 'AP_full'; groups=defaultdict(list);values=[]
            for q in queries:
                value=average_precision(qq[q['question_id']],g[q['question_id']],k)
                result['per_query'][q['question_id']][key]=value;groups[q['question_type']].append(value);values.append(value)
            name='m'+key
            result['micro'][name]=sum(values)/len(values)
            result['macro_six_types'][name]=sum(sum(v)/len(v) for v in groups.values())/len(groups)
            for typ,values in groups.items():result['by_question_type'][typ][name]=sum(values)/len(values)
        per_query[arm]=result.pop('per_query');metrics[arm]=result
        jsonl(out/'runs'/(arm+'.jsonl'),runs[arm])
    paired={}
    for arm,control in [('reading','node'),('sparse_pipeline','reading'),('all_node_pipeline','sparse_pipeline'),('sparse_pipeline','ColNomic_BGE'),('all_node_pipeline','ColNomic_BGE')]:
        delta=[per_query[arm][q['question_id']]['AP@5']-per_query[control][q['question_id']]['AP@5'] for q in queries]
        paired[arm+'_vs_'+control]={'wins':sum(v>1e-12 for v in delta),'losses':sum(v< -1e-12 for v in delta),'ties':sum(abs(v)<=1e-12 for v in delta)}
    result={'complete':True,'scope':'24-query/518-page inspected pilot; not official full corpus',
        'metrics':metrics,'paired_AP5':paired,'per_query':per_query,'graph':read(out/'graph_summary.json'),
        'retrieval':rm,'gold_sha256':sha(TRACE/'gold_evidence.jsonl')}
    write(out/'results.json',result)
    keys=['Recall@5','nDCG@5','RecallAll@5','mAP@5']
    lines=['# Full pipeline construction comparison','',result['scope'],'','| Arm | '+' | '.join(keys)+' |','| --- | ---: | ---: | ---: | ---: |']
    table=[]
    for arm,m in metrics.items():
        vals=[f'{100*m["macro_six_types"][k]:.2f}%' for k in keys]
        lines.append('| '+arm+' | '+' | '.join(vals)+' |');table.append('<tr><td>'+html.escape(arm)+'</td>'+''.join('<td>'+v+'</td>' for v in vals)+'</tr>')
    lines.extend(['','Generated edges share a verifier. NEXT is from current Qwen flows. Same BGE, text windows and 20-page budget.',
        'ColNomic_raw is the cached local base-model reproduction; ColNomic_BGE adds the same text reranker.',
        'Some reading flows are page-local and add no page after deduplication. No forced semantic edges.'])
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    cards=[]
    for q in queries:
        qid=q['question_id'];cards.append('<details><summary>'+html.escape(q['question'])+'</summary><pre>'+html.escape(json.dumps(
            {a:{'AP@5':per_query[a][qid]['AP@5'],'top5':pp[qid][:5]} for a,pp in ranks.items()},ensure_ascii=False,indent=2))+'</pre></details>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Pipeline comparison</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto}td,th{padding:10px;border-bottom:1px solid #ddd}pre{white-space:pre-wrap}details{padding:12px}</style><h1>Pipeline comparison</h1><p>'+html.escape(result['scope'])+'</p><table><tr><th>Arm</th>'+''.join('<th>'+k+'</th>' for k in keys)+'</tr>'+''.join(table)+'</table><p><a href="search_paths.jsonl">Search paths</a> · <a href="results.json">Metrics and graph coverage</a></p>'+''.join(cards))
    return {'complete':True,'arms':list(metrics)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','smoke','worker','reading','collect','encode-edges','retrieve','report'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--model',type=Path);p.add_argument('--encoder',type=Path)
    p.add_argument('--shards',type=int,default=16);p.add_argument('--index',type=int,default=0);p.add_argument('--minutes',type=int,default=420)
    p.add_argument('--document');p.add_argument('--task')
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='prepare':r=prepare(out,a.model,a.encoder,a.shards)
    elif a.stage=='smoke':r=smoke(out,a.model)
    elif a.stage=='worker':r=worker(out,a.model,a.index,a.minutes)
    elif a.stage=='reading':r=reading_run(out,a.model,a.document,a.task)
    elif a.stage=='collect':r=collect(out)
    elif a.stage=='encode-edges':r=encode_edges(out,a.encoder)
    elif a.stage=='retrieve':r=retrieve(out,a.encoder)
    else:r=report(out)
    print(json.dumps(r,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
