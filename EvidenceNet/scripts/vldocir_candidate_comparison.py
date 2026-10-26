"""Query-free sparse-selector versus every-node candidate generation.

The original selector sees exactly its original views. Every-node retrieval
also embeds nonempty eligible members of nodes omitted by the four-word filter.
Candidates are proposals only; both arms share one verifier over their union.
"""
from __future__ import annotations
import argparse
import copy
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import run_evidence_edge_pipeline as pipeline
import run_hierarchical_edge_retrieval as retrieval
import repair_edge_candidate_allocation as allocation
from run_node_context_edges import rows, read, write, jsonl, sha


def missing_views(nodes, policies, views):
    represented = {v['node_id'] for v in views}
    extra, excluded = [], []
    for n in sorted(nodes.values(), key=lambda n: n['id']):
        if n['id'] in represented:
            continue
        found = False
        for m in n['members']:
            if not allocation.allowed(policies[n['id']], m['id'], m['kind']) or not m['text'].strip():
                continue
            found = True
            extra.append(dict(view_id=f'ALL_NODE_SHORT_{len(extra):06d}', node_id=n['id'],
                article_id=n['article_id'], member_id=m['id'], member_kind=m['kind'],
                kind='short_or_formula_fallback', char_start=0, char_end=len(m['text']),
                quote=m['text'], retrieval_text=retrieval.clean(m['text']) or m['text'],
                source_status='ORIGINAL_TEXT' if m['kind']=='atom' else 'GENERATED_DESCRIPTION_FOR_RETRIEVAL_ONLY'))
        if not found:
            excluded.append(dict(node_id=n['id'], reason='no_nonempty_eligible_member'))
    return extra, excluded


def every_node(pool, views, vectors, nodes, k=1):
    """RRF top-k unique nodes; exact same-encoder fallback for uncovered nodes."""
    if k < 1:
        raise ValueError('positive per-node k required')
    by_node = defaultdict(dict)
    for p in pool.values():
        a, b = allocation.key(p)
        by_node[a][b] = p; by_node[b][a] = p
    indices = defaultdict(list)
    for i, v in enumerate(views): indices[v['node_id']].append(i)
    selected, decisions = {}, []
    for nid in sorted(nodes):
        choices = allocation.rank(list(by_node[nid].values()))[:k]
        if len(choices) < k and nid in indices:
            used = {p['target'] if p['source']==nid else p['source'] for p in choices}
            block = vectors[indices[nid]] @ vectors.T
            best = {}
            for j, v in enumerate(views):
                target = v['node_id']
                if target == nid or target in used: continue
                off = int(np.argmax(block[:, j])); score = float(block[off, j])
                candidate = (score, indices[nid][off], j)
                if target not in best or candidate[0] > best[target][0]: best[target] = candidate
            for target, (score, i, j) in sorted(best.items(), key=lambda x:(-x[1][0],x[0]))[:k-len(choices)]:
                a,b=sorted((nid,target)); direction='ab' if a==nid else 'ba'
                choices.append(dict(source=a,target=b,source_article=nodes[a]['article_id'],
                    target_article=nodes[b]['article_id'],retrieval_score=score,
                    routes=['all_node_dense_fallback'],signals={},best_views={direction:dict(
                        source_view=views[i]['view_id'],target_view=views[j]['view_id'],raw_score=score)}))
        for p in choices:
            key=allocation.key(p)
            if key not in selected:
                selected[key]={**copy.deepcopy(p),'selection_routes':['every_node_topk'],'proposed_by':[]}
            selected[key]['proposed_by'].append(nid)
        decisions.append(dict(node_id=nid, candidates=[list(allocation.key(p)) for p in choices],
            reason='selected' if choices else 'no_retrieval_view' if nid not in indices else 'no_other_node'))
    return sorted(selected.values(),key=allocation.key),decisions


def build(source: Path, adapted: Path, out: Path, model: Path, k=1, device='cuda'):
    if (out/'manifest.json').exists():
        m=read(out/'manifest.json')
        for p,h in m['inputs'].items():
            if sha(Path(p))!=h: raise ValueError('changed candidate input '+p)
        for n,h in m['outputs'].items():
            if sha(out/n)!=h: raise ValueError('changed candidate output '+n)
        if m['code']!=sha(Path(__file__)) or m['per_node_k']!=k:
            raise ValueError('changed candidate protocol')
        return read(out/'coverage.json')
    nodes={n['id']:n for n in rows(adapted/'nodes.jsonl')}; policies=read(adapted/'policies.json')
    views=rows(source/'views.jsonl'); vectors=np.load(source/'view_vectors.npy',allow_pickle=False)
    em=read(source/'embedding_manifest.json')
    if sha(source/'views.jsonl')!=em['signature']['views_sha256'] or sha(source/'view_vectors.npy')!=em['vectors_sha256']:
        raise ValueError('cached view identity mismatch')
    for filename,h in em['signature']['embedding']['files_sha256'].items():
        if sha(model/filename)!=h: raise ValueError('different encoder '+filename)
    generated,_=allocation.eligible_views(retrieval.make_views(nodes,policies),policies)
    if generated!=views: raise ValueError('current node text/views differ from cached encoder inputs')
    pipeline.validate_vectors(vectors,len(views))
    pool=retrieval.retrieve(views,vectors)
    articles,native=retrieval.route_and_select(nodes,pool)
    settings=read(source/'config.json')['selection']
    escaped=allocation.unique_escape(list(pool.values()),native,budget=settings['budget'],escape_budget=settings['escape_budget'])
    refs=allocation.references(nodes,policies)
    sparse=allocation.reserve_references(escaped,refs,budget=settings['budget'],reference_budget=settings['reference_budget'])
    extras,excluded=missing_views(nodes,policies,views)
    if extras:
        from compare_edge_embedding_models import embed
        ev,execution=embed([v['retrieval_text'] for v in extras],model,6,512,device,'last_token','left')
        vectors=np.concatenate([vectors,ev]); views=views+extras
    else: execution={'inference_required':False}
    all_pairs,decisions=every_node(pool,views,vectors,nodes,k)
    arms={'current_sparse':sparse,'all_node':all_pairs}; union={}
    for arm,pp in arms.items():
        for p in pp:
            key=allocation.key(p)
            if key not in union: union[key]=dict(p,comparison_arms=[])
            union[key]['comparison_arms'].append(arm)
        jsonl(out/(arm+'.jsonl'),pp)
    jsonl(out/'union.jsonl',sorted(union.values(),key=allocation.key))
    jsonl(out/'reference_candidates.jsonl',refs); jsonl(out/'article_candidates.jsonl',articles)
    jsonl(out/'extra_views.jsonl',extras); jsonl(out/'node_decisions.jsonl',decisions)
    jsonl(out/'excluded_nodes.jsonl',excluded)
    coverage={'nodes':len(nodes),'original_view_nodes':len({v['node_id'] for v in views if v['kind']!='short_or_formula_fallback'}),
        'extra_view_nodes':len({v['node_id'] for v in extras}),'per_node_k':k,'union_pairs':len(union),
        'no_candidate_nodes':[r['node_id'] for r in decisions if not r['candidates']],
        'arms':{arm:{'pairs':len(pp),'endpoint_nodes':len({n for p in pp for n in allocation.key(p)})} for arm,pp in arms.items()},
        'shared_pairs':len(set(map(allocation.key,sparse))&set(map(allocation.key,all_pairs))),
        'labels_used':False,'edges_verified':False,'extra_encoding':execution,
        'limitation':'Blocked exact retrieval for 518-page pilot; official scale requires ANN. No forced accepted edge.'}
    write(out/'coverage.json',coverage)
    inputs=[adapted/'nodes.jsonl',adapted/'policies.json',source/'views.jsonl',source/'view_vectors.npy',source/'embedding_manifest.json',source/'config.json']
    write(out/'manifest.json',{'inputs':{str(p.resolve()):sha(p) for p in inputs},'code':sha(Path(__file__)),
        'per_node_k':k,'outputs':{p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}})
    return coverage


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','adapted','output','model'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--per-node-k',type=int,default=1); p.add_argument('--device',default='cuda')
    a=p.parse_args(); print(build(a.source,a.adapted,a.output,a.model,a.per_node_k,a.device))
