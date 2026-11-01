#!/usr/bin/env python3
"""Top10 actual EvidenceNodes -> ALL one-hop neighbors -> common source scorer.

No heading seeds, global edge search, target-dense pruning, or gold-based paths.
Uses the frozen semantic graph only; unresolved reading proposals are not imported.
"""
import argparse
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path

import numpy as np
import run_query_evidence_selection as selection
from build_reader_anchor_ablation import ROOT, SOURCE, TRACE, DIAG, MODEL, BUDGETS, render, sha

OUT = ROOT / 'EvidenceNet/output/top10_node_navigation_20261029'
ARMS = ('seed10', 'dense_matched', 'seed10_neighbors', 'seed10_query_gated_neighbors')


def rows(path): return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
def filehash(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path, value): selection.save(path, value)
def jsonl(path, values): path.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in values))


def expand(ranking, graph, k=10):
    if len(ranking) != len(set(ranking)) or len(ranking) < k:
        raise ValueError('ranking requires unique nodes and at least k entries')
    ranks = {n:i+1 for i,n in enumerate(ranking)}
    seeds = ranking[:k]; paths=[]
    for edge in sorted(graph,key=lambda e:e['edge_id']):
        a,b=edge['source_node_id'],edge['target_node_id']
        if a not in ranks or b not in ranks or a == b:
            raise ValueError('invalid/unscored graph endpoint')
        for source,target,direction in ((a,b,'A_to_B'),(b,a,'B_to_A')):
            if source in seeds:
                paths.append({'edge_id':edge['edge_id'],'source_node':source,'source_rank':ranks[source],
                    'target_node':target,'target_initial_rank':ranks[target], 'direction':direction,
                    'outside_top10':ranks[target]>k,'outside_top20':ranks[target]>20,
                    'edge_layer':'semantic','hop':1})
    new = {p['target_node'] for p in paths}-set(seeds)
    # Sorting affects only deterministic serialization, never prunes a neighbor.
    candidates = seeds + sorted(new,key=lambda n:ranks[n])
    return {'seed_nodes':seeds,'graph_nodes':candidates,'dense_matched_nodes':ranking[:len(candidates)],'paths':paths}


def prepare(out, model):
    if out.exists(): raise ValueError('fresh output required')
    tok=selection.tokenizer(model)
    queries=rows(TRACE/'queries.jsonl'); units=rows(TRACE/'units.jsonl'); windows=rows(TRACE/'windows.jsonl')
    nodes={n['id']:n for n in rows(SOURCE/'nodes.jsonl')}
    graph=rows(DIAG/'edge_records.jsonl')
    scores=np.load(SOURCE/'search/query_window_scores.npy',allow_pickle=False)
    encoding=json.loads((SOURCE/'search/encoding.json').read_text())
    if filehash(SOURCE/'search/query_window_scores.npy') != encoding['score_sha256']:
        raise ValueError('score cache changed')
    for name in ('queries.jsonl','units.jsonl','windows.jsonl'):
        if filehash(TRACE/name) != encoding['inputs_sha256'][name]: raise ValueError('input order changed')
    if scores.shape != (len(queries),len(windows)) or not np.isfinite(scores).all(): raise ValueError('bad scores')
    tasks=[]; contexts=[]
    for qi,q in enumerate(queries):
        dense={}
        for wi,w in enumerate(windows):
            nid=units[w['unit_input_line']-1]['unit_id']
            if nid in nodes: dense[nid]=max(dense.get(nid,-float('inf')),float(scores[qi,wi]))
        ranking=sorted(dense,key=lambda n:(-dense[n],n)); ranks={n:i+1 for i,n in enumerate(ranking)}
        navigation=expand(ranking,graph)
        pool=set(navigation['graph_nodes'])|set(navigation['dense_matched_nodes'])
        packet_map={}; by_node=defaultdict(list); excluded=[]
        for nid in sorted(pool):
            node=nodes[nid]; allowed={m['member_id'] for m in node.get('eligible_members',[]) if m.get('eligible')}
            for m in node['members']:
                if m['id'] not in allowed or not m.get('text','').strip() or m.get('kind')=='visual':
                    excluded.append({'node_id':nid,'member_id':m['id'],'reason':'no_eligible_original_text'})
                    continue
                pid=f'P{len(packet_map):03d}'
                packet_map[pid]={'packet_id':sha(nid+':'+m['id']),'node_id':nid,'member_id':m['id'],
                    'page':[str(node['document']),str(node['page'])],'text':m['text'],
                    'member_sha256':sha(m['text']),'char_start':0,'char_end':len(m['text']),
                    'boxes':m.get('boxes',[]),'base_score':dense[nid],'initial_node_rank':ranks[nid],
                    'source_kind':'ORIGINAL_PARSER_MEMBER'}
                by_node[nid].append(pid)
        proposed=[]; seen_edges=set()
        for path in navigation['paths']:
            if path['edge_id'] in seen_edges: continue
            seen_edges.add(path['edge_id'])
            if by_node[path['source_node']] and by_node[path['target_node']]:
                proposed.append({'id':f'E{len(proposed):03d}','edge_id':path['edge_id'],
                    'source_packets':by_node[path['source_node']], 'target_packets':by_node[path['target_node']]})
        docs={}; prompt_packets=[]
        for pid,p in packet_map.items():
            doc=docs.setdefault(p['page'][0],f'D{len(docs)+1}')
            prompt_packets.append({'id':pid,'document':doc,'page':p['page'][1],'text':p['text']})
        prompt=selection.INSTRUCTION+'\nSOURCE DATA:\n'+json.dumps({'question':q['question'],'candidates':prompt_packets},ensure_ascii=False)
        endpoint_ids={pid for e in proposed for s in ('source_packets','target_packets') for pid in e[s]}
        edge_prompt=selection.EDGE_INSTRUCTION+'\nSOURCE DATA:\n'+json.dumps({'question':q['question'],
            'candidates':[p for p in prompt_packets if p['id'] in endpoint_ids],
            'proposed_edges':[{k:e[k] for k in ('id','source_packets','target_packets')} for e in proposed]},ensure_ascii=False)
        count=len(tok.apply_chat_template([{'role':'system','content':selection.SYSTEM},{'role':'user','content':prompt}],
            tokenize=True,add_generation_prompt=True,enable_thinking=False))
        if count>24576: raise ValueError('whole query over input budget; do not silently trim: '+q['question_id'])
        tasks.append({'question_id':q['question_id'],'question':q['question'],'prompt':prompt,'edge_prompt':edge_prompt,
            'prompt_sha256':sha(prompt+'\n'+edge_prompt),'input_tokens':count,'packets':packet_map,'edges':proposed})
        contexts.append({'question_id':q['question_id'],'question':q['question'], **navigation,
            'node_ranking':ranking,'node_pages':{nid:[str(nodes[nid]['document']),str(nodes[nid]['page'])] for nid in ranking},
            'excluded_members':excluded,'nodes_without_original_text':sorted(pool-{n for n,pp in by_node.items() if pp})})
    out.mkdir(parents=True)
    jsonl(out/'tasks.jsonl',tasks); jsonl(out/'navigation.jsonl',contexts)
    source_files=[SOURCE/'nodes.jsonl',SOURCE/'search/query_window_scores.npy',SOURCE/'search/encoding.json',
        TRACE/'queries.jsonl',TRACE/'units.jsonl',TRACE/'windows.jsonl',DIAG/'edge_records.jsonl']
    code=[Path(__file__),Path(selection.__file__),Path(__file__).with_name('build_reader_anchor_ablation.py')]
    token_files=[model/n for n in ('tokenizer.json','tokenizer_config.json','chat_template.jinja')]
    dump(out/'manifest.json',{'source_sha256':{str(p):filehash(p) for p in source_files+code+token_files},
        'tasks_sha256':filehash(out/'tasks.jsonl'),'navigation_sha256':filehash(out/'navigation.jsonl'),
        'queries':len(tasks),'arms':ARMS,'model':str(model),'seed_count':10,'hops':1,'graph_edges':len(graph),
        'edge_layer':'frozen_187_semantic_only','reading_layer':'not imported: upstream reading_ready=false',
        'candidate_policy':'all actual-node Top10 neighbors; no per-seed cap; equal node-count dense control',
        'scope':'existing 24-query development pilot; text-only scorer; no final answer generation',
        'candidate_scoring_cost':'shared union cached once; compare per-arm node and token cost, not only candidate count'})
    audit(out)
    print(json.dumps({'tasks':len(tasks),'packets':sum(len(t['packets']) for t in tasks),
        'max_input_tokens':max(t['input_tokens'] for t in tasks)},indent=2))


def check_navigation(out):
    manifest=json.loads((out/'manifest.json').read_text())
    if filehash(out/'navigation.jsonl') != manifest['navigation_sha256']: raise ValueError('navigation changed')
    if filehash(out/'tasks.jsonl') != manifest['tasks_sha256']: raise ValueError('tasks changed')


def audit(out):
    check_navigation(out)
    contexts=rows(out/'navigation.jsonl')
    summary={'queries':len(contexts),'seed_occurrences':sum(len(c['seed_nodes']) for c in contexts),
        'seeds_with_semantic_edges':sum(len({p['source_node'] for p in c['paths']}) for c in contexts),
        'queries_with_new_neighbors':sum(len(c['graph_nodes'])>10 for c in contexts),
        'new_node_occurrences_outside_top10':sum(len(set(c['graph_nodes'])-set(c['seed_nodes'])) for c in contexts),
        'new_node_occurrences_outside_top20':sum(len(set(c['graph_nodes'])-set(c['node_ranking'][:20])) for c in contexts),
        'actual_final_reranking_complete':False,
        'note':'Reachability only. A new node is not necessarily new useful evidence. Reading edges unavailable in this frozen layer.'}
    dump(out/'reachability.json',summary)
    cards=['<!doctype html><meta charset="utf-8"><style>body{font:16px system-ui;margin:24px}pre{white-space:pre-wrap}td,th{padding:8px;border-bottom:1px solid #ccc}summary{cursor:pointer}</style><h1>Top10 node → 现有语义边 → 一跳邻居</h1><p>仅可达性，不是最终排名或正确证据评测。阅读顺序层尚未导入。</p><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>']
    for c in contexts:
        cards.append('<details><summary>'+html.escape(c['question'])+f" — {len(c['graph_nodes'])-10} 新node</summary><table><tr><th>入口排名</th><th>edge</th><th>目标初始排名</th><th>目标node</th></tr>")
        for p in sorted(c['paths'],key=lambda p:(p['source_rank'],p['edge_id'])):
            cards.append(f"<tr><td>{p['source_rank']}</td><td>{html.escape(p['edge_id'])}</td><td>{p['target_initial_rank']}</td><td>{html.escape(p['target_node'])}</td></tr>")
        cards.append('</table></details>')
    (out/'paths.html').write_text('\n'.join(cards))
    print(json.dumps(summary,indent=2))


def report(out,model):
    check_navigation(out); selection.check_prepared(out,model)
    tok=selection.tokenizer(model); contexts={c['question_id']:c for c in rows(out/'navigation.jsonl')}
    records=[]; traces=[]; status=[]
    for t in rows(out/'tasks.jsonl'):
        qid=t['question_id']; c=contexts[qid]; path=out/'predictions'/(qid+'.json')
        pred=json.loads(path.read_text()) if path.exists() else None
        valid=pred is not None and pred.get('valid') is True
        status.append({'question_id':qid,'valid':valid})
        if not valid: continue
        if pred['prompt_sha256']!=t['prompt_sha256']: raise ValueError('stale model output')
        result=selection.validate(pred['result'],t)
        useful={e['id'] for e in result['edges'] if e['useful']}
        allowed_edges={e['edge_id'] for e in t['edges'] if e['id'] in useful}
        gated=set(c['seed_nodes'])|{p['target_node'] for p in c['paths'] if p['edge_id'] in allowed_edges}
        pools={'seed10':set(c['seed_nodes']),'dense_matched':set(c['dense_matched_nodes']),
            'seed10_neighbors':set(c['graph_nodes']),'seed10_query_gated_neighbors':gated}
        scores={p['id']:p for p in result['packets']}
        node_quality={}
        for nid in set().union(*pools.values()):
            pp=[pid for pid,p in t['packets'].items() if p['node_id']==nid]
            node_quality[nid]=(max((scores[pid]['score'] for pid in pp),default=-1),
                len({x['requirement'] for pid in pp for x in scores[pid]['covers']}))
        ranks={n:i+1 for i,n in enumerate(c['node_ranking'])}
        for arm,nids in pools.items():
            ranked=sorted(nids,key=lambda n:(-node_quality[n][0],-node_quality[n][1],ranks[n],n))
            kept={pid:p for pid,p in t['packets'].items() if p['node_id'] in nids}
            subset={**t,'packets':kept,'edges':[]}
            trace={'question_id':qid,'arm':arm,'node_ranking':ranked,'candidate_nodes':sorted(nids),
                'ranking_method':'max model support score, distinct predicted requirements, frozen dense rank tie-break',
                'original_text_tokens_to_score':sum(len(tok.encode(p['text'],add_special_tokens=False)) for p in kept.values()),
                'paths':[{**p,'target_prebudget_node_rank':ranked.index(p['target_node'])+1 if p['target_node'] in nids else None,
                    'query_edge_accepted':p['edge_id'] in allowed_edges} for p in c['paths']],
                'missing_original_text_nodes':[n for n in ranked if node_quality[n][0]<0], 'budget_packing':[]}
            traces.append(trace)
            for budget in BUDGETS:
                packed=selection.select(subset,result,'Q1_query_coverage',budget,tok)
                text=render(packed['packets'])
                input_nodes=list(dict.fromkeys(p['node_id'] for p in packed['packets']))
                trace['budget_packing'].append({'budget':budget,'selected_nodes_in_input_order':input_nodes,
                    'paths':[{'edge_id':p['edge_id'],'source_node':p['source_node'],'target_node':p['target_node'],
                        'target_in_final_input':p['target_node'] in input_nodes,
                        'target_input_order':input_nodes.index(p['target_node'])+1 if p['target_node'] in input_nodes else None}
                        for p in c['paths']]})
                records.append({'question_id':qid,'question':t['question'],'arm':arm,'budget':budget,
                    'evidence_text':text,'evidence_tokens':len(tok.encode(text,add_special_tokens=False)),
                    'requirements':result['requirements'],'coverage_is_model_estimate_not_gold':True,**packed})
    jsonl(out/'selected.jsonl',records); jsonl(out/'ranked_paths.jsonl',traces)
    dump(out/'status.json',{'total_queries':len(status),'valid_queries':sum(s['valid'] for s in status),
        'complete':all(s['valid'] for s in status),'queries':status,'answer_llm_run':False})
    print((out/'status.json').read_text())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','infer','audit','report'])
    parser.add_argument('--out',type=Path,default=OUT);parser.add_argument('--model',type=Path,default=MODEL)
    parser.add_argument('--minutes',type=float,default=150)
    args=parser.parse_args()
    if args.stage=='prepare':prepare(args.out,args.model)
    elif args.stage=='audit':audit(args.out)
    elif args.stage=='infer':
        check_navigation(args.out);selection.infer(args.out,args.model,args.minutes)
    else:report(args.out,args.model)
