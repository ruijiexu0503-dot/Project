#!/usr/bin/env python3
"""Non-generative article routing and claim-view evidence-pair retrieval.

Article candidates allocate search. They are never semantic proof. Graph
endpoints remain immutable evidence nodes; internal views only improve recall.
"""
import argparse
from collections import Counter, defaultdict
from html import unescape
import json
import math
from pathlib import Path
import re

import numpy as np

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, tokens
from dolphin_text import normalize_dolphin_text

SOURCE=ROOT/'EvidenceNet/output/paper_relevance_urban_traffic_20261013/graph'
DIAGNOSTIC=ROOT/'EvidenceNet/output/subject_gate_diagnostic_v1_20261014'
DEFAULT=ROOT/'EvidenceNet/output/hierarchical_edge_retrieval_v1_20261014'
ENCODER=ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B'
GENERIC_IDS={'figure','table','dataset','model','method','transformer','cnn','rnn','gnn','gcn','gpu',
             'sentinel','land cover','traffic flow','neural network','deep learning'}


def clean(text, layout_label=None):
    # Retrieval gets an additional dehyphenated view. Do this before the common
    # semantic renderer removes the newline, so authored lexical hyphens remain.
    text=re.sub(r'(?<=\w)-\s*\n\s*(?=\w)','',text)
    text=normalize_dolphin_text(text, layout_label)
    text=re.sub(r'<[^>]+>',' ',unescape(text))
    return re.sub(r'\s+',' ',text).strip()


def identifiers(text):
    plain=clean(text);found=set()
    patterns=[r'\b[A-Z][A-Z0-9-]{1,14}(?:\([A-Z]\))?\b',
              r'\b(?:Graph WaveNet|WaveNet|EuroSAT|PeMSD7\(M\)|PEMS-BAY|DCRNN|STGCN|FUSU|FUSU-Net|HRNet|PSPNet|KNet)\b',
              r'\b[A-Z][a-z]+(?:[- ][A-Z][A-Za-z0-9-]+){1,3}\b']
    for pattern in patterns:
        for match in re.finditer(pattern,plain):
            key=re.sub(r'[^a-z0-9]+',' ',match.group().casefold()).strip()
            if key and key not in GENERIC_IDS and len(key)>2:found.add(key)
    return sorted(found)


def make_views(nodes,policies):
    views=[]
    for node in sorted(nodes.values(),key=lambda n:n['id']):
        allowed={(m['member_id'],m['kind']) for m in policies[node['id']]['members'] if m['eligible']}
        for member in node['members']:
            if (member['id'],member['kind']) not in allowed:continue
            text=member.get('text','')
            if not text.strip():continue
            pieces=[]
            if member['kind']=='atom' and '<table' in text.lower():
                trs=list(re.finditer(r'<tr[^>]*>(.*?)</tr>',text,re.I|re.S))
                header=[]
                for i,tr in enumerate(trs):
                    cells=[clean(x) for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>',tr.group(1),re.I|re.S)]
                    if not cells:continue
                    if i==0:header=cells
                    rendered=('Columns: '+' | '.join(header)+'; ' if header and i else '')+'Row: '+' | '.join(cells)
                    pieces.append(('table_row',tr.start(),tr.end(),rendered))
            # Token windows retain exact source offsets and avoid one-vector-per-long-node dilution.
            words=list(re.finditer(r'\S+',text))
            for start in range(0,len(words),72):
                window=words[start:start+96]
                if not window:break
                lo,hi=window[0].start(),window[-1].end();rendered=clean(text[lo:hi], member.get('role'))
                if len(tokens(rendered))>=4:
                    pieces.append(('visual_description' if member['kind']=='visual' else 'source_window',lo,hi,rendered))
                if start+96>=len(words):break
            seen=set()
            for kind,lo,hi,retrieval_text in pieces:
                signature=(kind,lo,hi,retrieval_text)
                if signature in seen:continue
                seen.add(signature)
                views.append({'view_id':f'VIEW_{len(views):06d}','node_id':node['id'],'article_id':node['article_id'],
                    'member_id':member['id'],'member_kind':member['kind'],'kind':kind,'char_start':lo,'char_end':hi,
                    'quote':text[lo:hi],'retrieval_text':retrieval_text,'identifiers':identifiers(retrieval_text),
                    'source_status':'ORIGINAL_TEXT' if member['kind']=='atom' else 'GENERATED_DESCRIPTION_FOR_RETRIEVAL_ONLY'})
    return views


def bm25_top(views,k=30):
    bags=[Counter(tokens(v['retrieval_text'])) for v in views];n=len(bags)
    lengths=np.asarray([sum(b.values()) for b in bags],dtype=np.float32);avg=max(float(lengths.mean()),1.)
    postings=defaultdict(list)
    for i,bag in enumerate(bags):
        for term,tf in bag.items():postings[term].append((i,tf))
    results=[]
    for i,query in enumerate(bags):
        scores=defaultdict(float)
        for term in query:
            hits=postings[term]
            if len(hits)>n*.35:continue
            idf=math.log(1+(n-len(hits)+.5)/(len(hits)+.5))
            for j,tf in hits:
                if views[j]['node_id']==views[i]['node_id']:continue
                scores[j]+=idf*tf*2.5/(tf+1.5*(.25+.75*lengths[j]/avg))
        results.append(sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:k])
    return results


def retrieve(views,vectors,dense_k=30):
    pair_signals={}
    def add(i,j,route,rank,score):
        if views[i]['node_id']==views[j]['node_id']:return
        a,b=sorted((views[i]['node_id'],views[j]['node_id']))
        rec=pair_signals.setdefault((a,b),{'source':a,'target':b,'signals':{},'best_views':{}})
        direction='ab' if a==views[i]['node_id'] else 'ba';key=route+'_'+direction
        value=1/(60+rank)
        if value>rec['signals'].get(key,0):
            rec['signals'][key]=value;rec['best_views'][key]={'source_view':views[i]['view_id'],
                'target_view':views[j]['view_id'],'raw_score':float(score),'rank':rank}
    for start in range(0,len(views),128):
        block=vectors[start:start+128]@vectors.T
        for off,row in enumerate(block):
            i=start+off;order=np.argpartition(-row,min(dense_k+12,len(row)-1))[:dense_k+12]
            order=order[np.argsort(-row[order],kind='stable')]
            rank=0
            for j in order:
                if views[j]['node_id']==views[i]['node_id']:continue
                rank+=1;add(i,int(j),'dense',rank,row[j])
                if rank>=dense_k:break
    for i,hits in enumerate(bm25_top(views,dense_k)):
        for rank,(j,score) in enumerate(hits,1):add(i,j,'bm25',rank,score)
    byid=defaultdict(dict)
    for i,v in enumerate(views):
        for key in v['identifiers']:byid[key].setdefault(v['node_id'],i)
    for key,hits in byid.items():
        ids=sorted(hits)
        if len(ids)<2 or len(ids)>40:continue
        for x,a in enumerate(ids):
            for b in ids[x+1:]:
                i,j=hits[a],hits[b];rec=pair_signals.setdefault((a,b),{'source':a,'target':b,'signals':{},'best_views':{}})
                rec['signals']['identifier']=max(rec['signals'].get('identifier',0),1/60)
                rec.setdefault('shared_identifiers',[]).append(key)
                rec['best_views'].setdefault('identifier',{'source_view':views[i]['view_id'],'target_view':views[j]['view_id']})
    for rec in pair_signals.values():
        # Max per direction prevents long nodes from accumulating unlimited votes.
        rec['retrieval_score']=sum(rec['signals'].values())
        rec['routes']=sorted({k.split('_')[0] for k in rec['signals']})
    return pair_signals


def route_and_select(nodes,pairs,article_neighbors=2,pairs_per_article=16,global_escape=96,intra_per_article=8):
    grouped=defaultdict(list)
    for pair in pairs.values():
        aa,bb=nodes[pair['source']]['article_id'],nodes[pair['target']]['article_id']
        pair['source_article']=aa;pair['target_article']=bb
        grouped[tuple(sorted((aa,bb)))].append(pair)
    article_rows=[]
    for (a,b),items in grouped.items():
        if a==b:continue
        top=sorted(items,key=lambda p:(-p['retrieval_score'],p['source'],p['target']))[:5]
        ids=sorted({x for p in top for x in p.get('shared_identifiers',[])})
        article_rows.append({'source_article':a,'target_article':b,'routing_score':sum(p['retrieval_score'] for p in top),
            'supporting_candidate_pairs':[{'source':p['source'],'target':p['target']} for p in top],
            'shared_identifiers':ids,'status':'ROUTING_CANDIDATE_NOT_SEMANTIC_EDGE'})
    selected_article_keys=set()
    articles=sorted({n['article_id'] for n in nodes.values()})
    for aid in articles:
        choices=[r for r in article_rows if aid in {r['source_article'],r['target_article']}]
        for r in sorted(choices,key=lambda x:(-x['routing_score'],x['source_article'],x['target_article']))[:article_neighbors]:
            selected_article_keys.add(tuple(sorted((r['source_article'],r['target_article']))))
    for r in article_rows:r['selected_for_node_search']=tuple(sorted((r['source_article'],r['target_article']))) in selected_article_keys
    selected={}
    def take(items,limit,route,degree_cap=4):
        degree=Counter();count=0
        for p in sorted(items,key=lambda x:(-x['retrieval_score'],x['source'],x['target'])):
            if degree[p['source']]>=degree_cap or degree[p['target']]>=degree_cap:continue
            key=(p['source'],p['target']);q=selected.setdefault(key,{**p,'selection_routes':[]})
            if route not in q['selection_routes']:q['selection_routes'].append(route)
            degree[p['source']]+=1;degree[p['target']]+=1;count+=1
            if count>=limit:break
    for key in selected_article_keys:take(grouped[key],pairs_per_article,'article_routed')
    cross=[p for key,items in grouped.items() if key[0]!=key[1] for p in items]
    take(cross,global_escape,'global_escape',6)
    for aid in articles:take(grouped.get((aid,aid),[]),intra_per_article,'intra_article',3)
    result=[]
    for i,p in enumerate(sorted(selected.values(),key=lambda x:(-x['retrieval_score'],x['source'],x['target']))):
        p['pair_id']=f'HIER_{i:05d}';result.append(p)
    return article_rows,result


def prepare(out):
    if out.exists():raise ValueError('fresh_output_required')
    source_files=['units.jsonl','eligibility.json','reading_edges.jsonl','pages.json','cpu_execution_manifest.json']
    for name in source_files:
        if not (SOURCE/name).exists():raise ValueError('missing_source:'+name)
    out.mkdir(parents=True)
    nodes={n['id']:n for n in rows(SOURCE/'units.jsonl')};policies=read(SOURCE/'eligibility.json')
    views=make_views(nodes,policies);jsonl(out/'views.jsonl',views)
    articles=defaultdict(list)
    for n in nodes.values():articles[n['article_id']].append(n['id'])
    jsonl(out/'articles.jsonl',[{'article_id':a,'node_ids':sorted(ids),'document':nodes[ids[0]]['document'],
        'status':'KNOWN_PAPER_DOCUMENT_PROFILE'} for a,ids in sorted(articles.items())])
    write(out/'manifest.json',{'experiment':'hierarchical_edge_retrieval_v1','source':str(SOURCE),
        'source_sha256':{name:sha(SOURCE/name) for name in source_files},'code_sha256':sha(__file__),
        'nodes':len(nodes),'views':len(views),'articles':len(articles),'encoder':str(ENCODER),
        'design':'article routing candidates + claim-view node retrieval + global escape; no LLM; no semantic edges',
        'article_candidate_semantics':'search allocation only','graph_endpoint':'immutable evidence node',
        'labels_used_for_selection':False})
    print(json.dumps({'nodes':len(nodes),'views':len(views),'articles':len(articles)}),flush=True)


def run(out):
    # The CPU encoder pulls in the full graph-building stack; candidate ranking
    # helpers are also imported by lightweight evaluation scripts that do not
    # need those dependencies.
    from run_traffic_relevance_cpu import cpu_embed

    manifest=read(out/'manifest.json')
    if manifest['code_sha256']!=sha(__file__):raise ValueError('changed_code')
    for name,h in manifest['source_sha256'].items():
        if sha(SOURCE/name)!=h:raise ValueError('changed_source:'+name)
    views=rows(out/'views.jsonl');nodes={n['id']:n for n in rows(SOURCE/'units.jsonl')}
    vectors=np.asarray(cpu_embed([v['retrieval_text'] for v in views],ENCODER),dtype=np.float32)
    np.save(out/'view_vectors.npy',vectors)
    pairs=retrieve(views,vectors);articles,candidates=route_and_select(nodes,pairs)
    jsonl(out/'article_candidates.jsonl',articles);jsonl(out/'node_candidates.jsonl',candidates)
    write(out/'retrieval_manifest.json',{'views_sha256':sha(out/'views.jsonl'),'vectors_sha256':sha(out/'view_vectors.npy'),
        'article_candidates_sha256':sha(out/'article_candidates.jsonl'),'node_candidates_sha256':sha(out/'node_candidates.jsonl'),
        'article_neighbor_budget':2,'node_pairs_per_routed_article_pair':16,'global_escape_pairs':96,
        'intra_article_pairs':8,'qwen_calls':0})
    report(out)


def report(out):
    candidates=rows(out/'node_candidates.jsonl') if (out/'node_candidates.jsonl').exists() else []
    articles=rows(out/'article_candidates.jsonl') if (out/'article_candidates.jsonl').exists() else []
    keys={frozenset((p['source'],p['target'])):p for p in candidates}
    evaluation=[]
    if (DIAGNOSTIC/'comparison.jsonl').exists():
        for item in rows(DIAGNOSTIC/'comparison.jsonl'):
            if item['cohort']!='new_method':continue
            hit=keys.get(frozenset((item['source'],item['target'])))
            evaluation.append({'pair_id':item['pair_id'],'reference_method_correspondence':item['reference_method_correspondence'],
                'baseline_natural_candidate':item['natural_candidate'],'hierarchical_candidate':bool(hit),
                'selection_routes':hit['selection_routes'] if hit else [],'retrieval_score':hit['retrieval_score'] if hit else None})
    jsonl(out/'diagnostic_coverage.jsonl',evaluation)
    positives=[x for x in evaluation if x['reference_method_correspondence']]
    negatives=[x for x in evaluation if not x['reference_method_correspondence']]
    summary={'phase':'RETRIEVAL_COMPLETE_NO_RELATION_VERIFICATION' if candidates else 'PREPARED',
        'articles':len(rows(out/'articles.jsonl')),'views':len(rows(out/'views.jsonl')),
        'article_candidate_pairs':len(articles),'selected_article_pairs':sum(r.get('selected_for_node_search',False) for r in articles),
        'node_candidates':len(candidates),'qwen_calls':0,
        'diagnostic_positive_coverage':sum(x['hierarchical_candidate'] for x in positives),'diagnostic_positive_total':len(positives),
        'baseline_positive_coverage':sum(bool(x['baseline_natural_candidate']) for x in positives),
        'diagnostic_negative_candidates':sum(x['hierarchical_candidate'] for x in negatives),'diagnostic_negative_total':len(negatives),
        'article_candidates_are_semantic_edges':False,'retrieval_gain':'NOT_EVALUATED'}
    write(out/'summary.json',summary)
    (out/'REPORT.md').write_text('# Hierarchical edge retrieval\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n\n'+json.dumps(evaluation,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','run','report']);p.add_argument('--output',type=Path,default=DEFAULT)
    a=p.parse_args();globals()[a.stage](a.output.resolve())
