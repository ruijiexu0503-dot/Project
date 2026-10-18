#!/usr/bin/env python3
"""CPU execution adapter for the frozen traffic graph experiment.

Reuse its inputs, prompts, candidate policy and validators; record device and
precision explicitly. A smoke run never publishes a complete semantic graph.
"""
import argparse
import gc
import os
from pathlib import Path
import time

import run_traffic_relevance_graph as graph
import run_own_corpus_edges as models
from run_node_context_edges import read, rows, write, sha


def cpu_embed(texts, model_path):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True,
        trust_remote_code=True,padding_side='left')
    model=AutoModel.from_pretrained(model_path,local_files_only=True,
        trust_remote_code=True,torch_dtype=torch.float32).to('cpu').eval()
    vectors=[]
    for start in range(0,len(texts),8):
        batch=tokenizer(texts[start:start+8],padding=True,truncation=True,
            max_length=512,return_tensors='pt').to('cpu')
        with torch.inference_mode():
            hidden=model(**batch).last_hidden_state
            vec=torch.nn.functional.normalize(hidden[:,-1].float(),p=2,dim=1)
            vectors.extend(vec.cpu().numpy())
        print('cpu_embedding',min(start+8,len(texts)),len(texts),flush=True)
    del model
    gc.collect()
    return vectors


def select_smoke(queue,nodes,policies):
    def visual(pair):
        for key in ['source','target']:
            nid=pair[key]
            allowed={(m['kind'],m['member_id']) for m in policies[nid]['members'] if m['eligible']}
            if any(m['kind']=='visual' and m.get('crop') and (m['kind'],m['id']) in allowed for m in nodes[nid]['members']):
                return True
        return False
    chosen=[]
    for kind in [False,True]:
        pool=[p for p in queue if visual(p)==kind]
        if pool:chosen.append(pool[0])
    if len(chosen)<2:
        chosen.extend(p for p in queue if p not in chosen)
    return chosen[:2]


def verify(root,smoke=False,max_hours=48):
    out=root/'graph';queue=rows(out/'semantic_candidates.jsonl')
    nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'eligibility.json')
    selected=select_smoke(queue,nodes,policies) if smoke else queue
    if not selected:raise ValueError('empty_verification_queue')
    if not smoke:
        benchmark=read(out/'cpu_smoke.json')
        if benchmark['state']!='COMPLETE' or not benchmark['all_valid']:
            write(out/'cpu_full_status.json',{'state':'DEFERRED_SMOKE_FAILED','benchmark':benchmark})
            raise ValueError('CPU smoke did not yield valid model responses')
        estimate=benchmark['projected_full_hours_with_margin']
        if estimate>max_hours:
            write(out/'cpu_full_status.json',{'state':'DEFERRED_RUNTIME_ESTIMATE','estimated_hours':estimate,
                'limit_hours':max_hours,'note':'Only two sampled pairs; estimate is approximate. Completed decisions remain resumable.'})
            print('CPU verification deferred:',estimate,'hours exceeds',max_hours,flush=True)
            return
    import torch
    model_started=time.monotonic()
    model=models.create_llm({'provider':'transformers','model':str(models.MODEL),
        'dtype':'bfloat16','device_map':'cpu','require_cuda':False,'enable_thinking':False})
    loaded=time.monotonic()-model_started
    devices={str(p.device) for p in model.model.parameters()}
    if devices!={'cpu'}:raise ValueError('non_cpu_model_placement:'+str(devices))
    original_rows=graph.rows;original_jsonl=graph.jsonl;original_call=graph.call_json;original_llm=models.llm
    def filtered(path):
        return selected if Path(path)==out/'semantic_candidates.jsonl' else original_rows(path)
    def timed_call(*args,**kwargs):
        print('cpu_model_call_started',flush=True);started=time.monotonic()
        result=original_call(*args,**kwargs)
        result['execution']={'device':'cpu','dtype':'bfloat16','elapsed_seconds':time.monotonic()-started,
            'threads':torch.get_num_threads(),'adapter_sha256':sha(__file__)}
        print('cpu_model_call_finished',result['execution']['elapsed_seconds'],result['valid'],flush=True)
        return result
    def guarded_jsonl(path,values):
        if smoke and Path(path).name in {'semantic_decisions.jsonl','semantic_edges.jsonl'}:return
        original_jsonl(path,values)
    graph.rows=filtered;graph.jsonl=guarded_jsonl;graph.call_json=timed_call;models.llm=lambda:model
    try:graph.verify(root)
    finally:
        graph.rows=original_rows;graph.jsonl=original_jsonl;graph.call_json=original_call;models.llm=original_llm
    records=[read(out/'decisions'/(p['pair_id']+'.json')) for p in selected]
    if any(r['response'].get('execution',{}).get('device')!='cpu' for r in records):
        raise ValueError('CPU experiment mixed with unmarked/GPU decisions')
    if smoke:
        times=[r['response']['execution']['elapsed_seconds'] for r in records]
        write(out/'cpu_smoke.json',{'state':'COMPLETE','all_valid':all(r['response']['valid'] for r in records),
            'pair_ids':[p['pair_id'] for p in selected],'load_seconds':loaded,'pair_seconds':times,
            'queue_size':len(queue),'projected_full_hours_with_margin':(loaded+1.5*max(times)*len(queue))/3600,
            'note':'Two cases (text and visual when available), max observed time x 1.5; approximate, not a throughput guarantee.'})
        graph.report(root)
    else:
        write(out/'cpu_full_status.json',{'state':'COMPLETE_AWAITING_SOURCE_REVIEW','pairs':len(queue)})


def run(stage,root,threads,max_hours):
    os.environ['CUDA_VISIBLE_DEVICES']=''
    import torch
    torch.set_num_threads(threads)
    graph.check(root)
    marker=root/'graph/cpu_execution_manifest.json'
    if stage=='prepare':
        if list((root/'graph/decisions').glob('*.json')):raise ValueError('existing_decisions_use_separate_experiment')
        write(marker,{'adapter_sha256':sha(__file__),'source_manifest_sha256':sha(root/'manifest.json'),
            'graph_script_sha256':sha(graph.__file__),'llm_client_sha256':sha(models.ROOT/'EvidenceNet/evidence_graph/llm_client.py'),
            'embedding_model':str(models.ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B'),
            'embedding_dtype':'float32','embedding_pooling':'last_token,left_padding,max_length_512,l2_norm',
            'verification_model':str(models.MODEL),'verification_dtype':'bfloat16','device':'cpu',
            'threads':threads,'note':'Same models/policy/prompts; CPU float32 embedding is not bitwise identical to GPU bfloat16.'})
        graph.assemble(root)
        import run_node_embedding_geometry_pilot as embeddings
        embeddings.embed=cpu_embed
        graph.candidates(root)
        write(root/'graph/cpu_candidate_sha256.json',{'sha256':sha(root/'graph/semantic_candidates.jsonl')})
        graph.report(root)
    else:
        m=read(marker)
        if m['adapter_sha256']!=sha(__file__) or m['source_manifest_sha256']!=sha(root/'manifest.json'):
            raise ValueError('changed_cpu_execution_code_or_input')
        if m['llm_client_sha256']!=sha(models.ROOT/'EvidenceNet/evidence_graph/llm_client.py'):
            raise ValueError('changed_llm_client')
        if read(root/'graph/cpu_candidate_sha256.json')['sha256']!=sha(root/'graph/semantic_candidates.jsonl'):
            raise ValueError('changed_cpu_candidates')
        verify(root,smoke=stage=='smoke',max_hours=max_hours)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','smoke','verify'])
    p.add_argument('--root',type=Path,default=graph.DEFAULT);p.add_argument('--threads',type=int,default=32)
    p.add_argument('--max-hours',type=float,default=48)
    a=p.parse_args();run(a.stage,a.root.resolve(),a.threads,a.max_hours)
