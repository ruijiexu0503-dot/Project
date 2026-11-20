"""Deterministic, untrained QKV Query-Edge Attention Probe.

No-cluster QK logits are algebraically equivalent to the existing C scorer;
softmax and NO_EXPAND expose routing weights but add no learned capacity.
"""
from __future__ import annotations
import argparse, collections, math, time
import numpy as np
from common import load_config, load_embeddings, read_jsonl, repo_path, run_dir, write_json, write_jsonl
from run_query_conditioned_edge_retrieval import BASELINE, evaluate, norm, page, query_vectors

def unit(x): return x / max(float(np.linalg.norm(x)), 1e-12)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--config',required=True); p.add_argument('--seed-pages',type=int,default=10); p.add_argument('--graph-weight',type=float,default=.25); p.add_argument('--context-weight',type=float,default=.10); p.add_argument('--variants',nargs='+',choices=('none','node','edge','node_edge'),default=('none','node','edge','node_edge')); p.add_argument('--page-aggregation',choices=('legacy_max_qk','attention_value_mass'),default='legacy_max_qk'); p.add_argument('--allow-cpu',action='store_true'); a=p.parse_args()
    if not 0<=a.context_weight<=1: raise ValueError('context-weight must be in [0,1]')
    config=load_config(a.config); out=run_dir(config); suffix='' if a.page_aggregation=='legacy_max_qk' else '_value_aware'; root=out/f'qkv_attention_probe{suffix}'; root.mkdir(parents=True,exist_ok=True); base=repo_path(BASELINE)
    queries=list(read_jsonl(base/'pilot/queries.jsonl')); qids=[str(x['question_id']) for x in queries]
    gold=collections.defaultdict(set)
    for r in read_jsonl(base/'pilot/gold_evidence.jsonl'): gold[str(r['question_id'])].add(page(r))
    frozen=collections.defaultdict(dict)
    for r in read_jsonl(base/'retrieval/hybrid_visual_scores.jsonl'): frozen[str(r['question_id'])][page(r)]=float(r['score'])
    node_page={}; page_nodes=collections.defaultdict(list)
    for r in read_jsonl(base/'retrieval/node_pages.jsonl'):
        if len(r['source_pages'])!=1: raise ValueError('ambiguous Pilot node page')
        node_page[r['node_id']]=page(r['source_pages'][0]); page_nodes[node_page[r['node_id']]].append(r['node_id'])
    vectors,ids=load_embeddings(config); vectors=np.asarray([norm(x) for x in np.asarray(vectors,dtype=np.float32)]); index={n:i for i,n in enumerate(ids)}
    query=query_vectors(queries,root,a.allow_cpu)
    initial={}; seeds={}
    for qi,qid in enumerate(qids):
        rank=sorted(frozen[qid],key=lambda x:(-frozen[qid][x],x)); initial[qid]=rank; seeds[qid]=[]
        for pid in rank[:a.seed_pages]:
            choices=[n for n in page_nodes[pid] if n in index]
            if choices: seeds[qid].append(max(choices,key=lambda n:(float(query[qi]@vectors[index[n]]),n)))
    all_seeds=set().union(*map(set,seeds.values())); adjacency=collections.defaultdict(list); scanned=0
    for r in read_jsonl(repo_path(config['candidate_union_path'])):
        left,right=r['source_id'],r['target_id']; scanned+=1
        if left in all_seeds and right in index: adjacency[left].append(right)
        if right in all_seeds and left in index: adjacency[right].append(left)
    node_centers=np.asarray(np.load(out/'node_clustering/centroids.npy'),dtype=np.float32); edge_centers=np.asarray(np.load(out/'clustering/middiff_k32_seed17/centroids.npy'),dtype=np.float32)
    sqrt=np.sqrt; dim=vectors.shape[1]
    summary={}
    for variant in a.variants:
        started=time.perf_counter(); rankings={}; traces=[]; outputs=[]; count=0; edge_usage=collections.Counter(); node_usage=collections.Counter()
        for qi,qid in enumerate(qids):
            candidate=[]; seed_pages={node_page[x] for x in seeds[qid]}
            for source_id in seeds[qid]:
                source=vectors[index[source_id]]; q_shared=query[qi]
                if variant in ('node','node_edge'):
                    nk=int(np.argmax(source@node_centers.T)); q_shared=unit(query[qi]+a.context_weight*node_centers[nk]); node_usage[nk]+=1
                residual=unit(q_shared-source)
                qkey=np.concatenate((sqrt(.50)*q_shared,sqrt(.35)*residual,sqrt(.15)*q_shared))
                # V has midpoint/difference in the opposite two channels from K.
                # qvalue is fixed, has no fitted parameters, and lets page aggregation
                # consume the attended target/edge evidence rather than merely log it.
                qvalue=np.concatenate((sqrt(.50)*q_shared,sqrt(.15)*residual,sqrt(.35)*q_shared))
                for target_id in adjacency[source_id]:
                    target=vectors[index[target_id]]; pid=node_page[target_id]
                    if pid in seed_pages: continue
                    midpoint=unit((source+target)/2); difference=unit(target-source); ek=None
                    if variant in ('edge','node_edge'):
                        raw=unit(np.concatenate(((source+target)/2,target-source))); ek=int(np.argmax(raw@edge_centers.T)); edge_usage[ek]+=1
                        pm,pd=np.split(edge_centers[ek],2); midpoint=unit(midpoint+a.context_weight*unit(pm)); difference=unit(difference+a.context_weight*unit(pd))
                    key=np.concatenate((sqrt(.50)*target,sqrt(.35)*difference,sqrt(.15)*midpoint))
                    logit=float(qkey@key); score=.5+.5*logit
                    value=np.concatenate((target,midpoint,difference))
                    value_logit=float(qvalue@value)
                    candidate.append((logit,score,value_logit,source_id,target_id,pid,ek,value))
                    count+=1
            logits=np.asarray([x[0] for x in candidate]+[0.0],dtype=np.float64); logits-=logits.max(); weights=np.exp(logits); weights/=weights.sum(); no_expand=float(weights[-1])
            page_scores={}; page_mass=collections.defaultdict(float); page_value_mass=collections.defaultdict(float); weighted_value=np.zeros(3*dim,dtype=np.float64)
            for item,weight in zip(candidate,weights[:-1]):
                logit,score,value_logit,src,tgt,pid,ek,value=item; weighted_value+=weight*value
                page_mass[pid]+=float(weight)
                # Cosine-like fixed V compatibility is bounded after the affine map.
                page_value_mass[pid]+=float(weight)*(.5+.5*value_logit)
                if pid not in page_scores or score>page_scores[pid][0]: page_scores[pid]=(score,src,tgt,logit,weight,ek)
            if a.page_aggregation=='attention_value_mass' and page_value_mass:
                # This is a page posterior/evidence rule, not a fitted mixture: a page
                # is rewarded only when it receives QK attention and carries compatible V.
                # Divide by the query maximum solely to retain the frozen [0,1] fusion scale.
                denom=max(page_value_mass.values())
                page_scores={pid:(mass/denom,None,None,None,page_mass[pid],None) for pid,mass in page_value_mass.items()}
            raw=frozen[qid]; lo,hi=min(raw.values()),max(raw.values()); span=hi-lo or 1.0; final={pid:(s-lo)/span for pid,s in raw.items()}
            for pid,(score,*_) in page_scores.items(): final[pid]+=a.graph_weight*score
            rankings[qid]=sorted(final,key=lambda pid:(-final[pid],pid))
            outputs.append({'question_id':qid,'variant':variant,'no_expand_attention':no_expand,'attention_value_l2':float(np.linalg.norm(weighted_value)),'candidate_edges':len(candidate),'candidate_pages':len(page_scores)})
            traces.extend({'question_id':qid,'variant':variant,'source_node_id':src,'target_node_id':tgt,'target_page':list(pid),'qk_logit':logit,'value_logit':value_logit,'attention_weight':float(weight),'page_score':score,'edge_cluster':ek,'no_expand_attention':no_expand} for logit,score,value_logit,src,tgt,pid,ek,_ in candidate)
        metrics=evaluate(queries,gold,rankings,initial); metrics['cost']={'candidate_pairs_scanned_once':scanned,'actual_directed_edges_attended':count,'elapsed_seconds':time.perf_counter()-started,'attention_pairs':count,'candidate_budget':'all legal one-hop edges from fixed seeds','node_cluster_usage':dict(node_usage) if variant in ('node','node_edge') else None,'edge_cluster_usage':dict(edge_usage) if variant in ('edge','node_edge') else None}; metrics['probe_contract']='Untrained deterministic QKV feature probe. QK is fixed directional alignment; attention is over legal candidates plus NO_EXPAND. In attention_value_mass, page score is normalized sum(attention * (0.5 + 0.5 * Qvalue·V)); there are no fitted weights or Gold-derived choices.'
        target=root/variant; target.mkdir(exist_ok=True); write_json(target/'metrics.json',metrics); write_jsonl(target/'edge_attention_trace.jsonl',traces); write_jsonl(target/'query_attention_summary.jsonl',outputs); summary[variant]=metrics['macro_six_types']
    write_json(root/'manifest.json',{'kind':'untrained deterministic Query-Edge QKV probe','Q':'[query, normalize(query-source), query]','K':'[target, directed_difference, midpoint]','V':'[target, midpoint, directed_difference]','Q_for_V':'[query, 0.15 normalize(query-source), 0.35 query] with matching fixed channel weights','dimension':3*dim,'page_aggregation':a.page_aggregation,'no_expand_logit':0.0,'variants':list(a.variants),'context_weight':a.context_weight,'candidate_pairs_scanned':scanned,'query_or_gold_used_to_build_graph':False,'gold_used_only_for':'post-hoc evaluation','summary':summary})
    print(root)
if __name__=='__main__': main()
