#!/usr/bin/env python3
"""Deterministic corpus/document/modality-aware companion discovery."""
import json,math,re,hashlib,random
from collections import Counter,defaultdict
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]
STOP=set('the and that with from this are was were for into their they have has had but not can could would should about which while when where what how why its also than then them these those been being use used using through between within without more most some such each other only over under'.split())
def loadl(p):return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def savel(p,x):p.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in x),encoding='utf8')
def toks(s):return [x for x in re.findall(r'[a-z][a-z0-9-]{3,}',s.lower()) if x not in STOP]
def quality(n):
 t=n['content_text'];alpha=sum(c.isalpha() for c in t);return 70<=len(t)<=2000 and alpha/max(len(t),1)>.45 and len(set(toks(t)))>=7
def family(n):
 if n['source_corpus']=='real_documents_snapshot_A':return 'nasa_spinoff_real'
 d=n['document_id'].lower()
 if d.startswith('gw150914') or d.startswith('arxiv_15') or '1511.' in d:return 'gravitational_wave_research'
 return d.split('_page_')[0]
def main():
 nodes=[x for x in loadl(OUT/'snapshot_A_canonical_nodes.jsonl') if quality(x)]
 # Keep broad document/page/modality coverage and cap very long magazines.
 groups=defaultdict(list)
 for n in nodes:groups[(n['document_id'],n['node_type'])].append(n)
 selected=[]
 for key,rows in sorted(groups.items()):
  rows.sort(key=lambda x:(x['page_number'],x['canonical_node_id']))
  cap=700 if key[1] in {'PARA','TEXT'} else 180
  if len(rows)>cap:
   idx=sorted({round(i*(len(rows)-1)/(cap-1)) for i in range(cap)})
   rows=[rows[i] for i in idx]
  selected.extend(rows)
 nodes=selected;N=len(nodes)
 token_sets=[];df=Counter();post=defaultdict(list)
 for i,n in enumerate(nodes):
  ts=set(toks(n['content_text']));token_sets.append(ts)
  for t in ts:df[t]+=1;post[t].append(i)
 def sim(i,j):
  a,b=token_sets[i],token_sets[j];shared=a&b
  if not shared:return 0
  num=sum(math.log((N+1)/(df[t]+1))+1 for t in shared);den=sum(math.log((N+1)/(df[t]+1))+1 for t in a|b)
  return num/max(den,1e-9)
 def candidates(i,mode):
  terms=sorted(token_sets[i],key=lambda t:(df[t],t))[:14];pool=Counter()
  for t in terms:
   if df[t]>max(800,N//8):continue
   w=math.log((N+1)/(df[t]+1))+1
   for j in post[t]:
    if j!=i:pool[j]+=w
  out=[];a=nodes[i]
  for j,_ in pool.most_common(500):
   b=nodes[j]
   if mode=='cross_page' and not (a['document_id']==b['document_id'] and a['page_id']!=b['page_id']):continue
   if mode=='cross_doc' and a['document_id']==b['document_id']:continue
   s=sim(i,j)
   if .035<=s<=.78:out.append((s,j))
  return sorted(out,reverse=True)
 rng=random.Random(20261117);by_doc=defaultdict(list);by_route=defaultdict(list)
 for i,n in enumerate(nodes):by_doc[n['document_id']].append(i);by_route[(n['source_corpus'],n['node_type'])].append(i)
 seeds=[];seen=set();serial=0
 def add(cat,idxs,route,score):
  nonlocal serial
  ids=tuple(sorted(nodes[i]['canonical_node_id'] for i in idxs));key=(cat,ids)
  if key in seen:return
  seen.add(key);serial+=1
  ev=[]
  for i in idxs:
   n=dict(nodes[i]);n['source_family']=family(n);ev.append(n)
  seeds.append({'seed_id':f'scale300_b001_seed::{serial:04d}','target_category':cat,'discovery_route':route,'companion_score':round(score,5),'evidence':ev,'shared_terms':sorted(set.intersection(*(token_sets[i] for i in idxs)))[:20]})
 # Singles: stratified by corpus, modality, and document.
 doc_order=sorted(by_doc);rounds=0
 while sum(x['target_category']=='single_node' for x in seeds)<60 and rounds<30:
  for d in doc_order:
   cand=[i for i in by_doc[d] if nodes[i]['node_type'] in ({'TABLE','CAPTION','COMPOSITE'} if rounds<4 else {'PARA','TEXT','TABLE','CAPTION','COMPOSITE'})]
   if cand:add('single_node',[cand[rounds%len(cand)]],'stratified_document_modality',1.0)
   if sum(x['target_category']=='single_node' for x in seeds)>=60:break
  rounds+=1
 # Cross-page: prioritize real PDFs and page distances >1.
 anchors=list(range(N));anchors.sort(key=lambda i:(nodes[i]['source_corpus']!='real_documents_snapshot_A',hashlib.sha1(nodes[i]['canonical_node_id'].encode()).hexdigest()))
 for i in anchors:
  for s,j in candidates(i,'cross_page')[:8]:
   dist=abs(nodes[i]['page_number']-nodes[j]['page_number'])
   if dist<2:continue
   add('cross_page',[i,j],f"bm25_like_cross_page_{'2_10' if dist<=10 else 'gt10'}",s)
   if sum(x['target_category']=='cross_page' for x in seeds)>=140:break
  if sum(x['target_category']=='cross_page' for x in seeds)>=140:break
 # Cross-document pairs; route order prevents legacy-only dominance.
 route_targets={'new_new':80,'new_legacy':100,'legacy_legacy':40};route_count=Counter()
 for i in anchors:
  a=nodes[i]
  for s,j in candidates(i,'cross_doc')[:30]:
   b=nodes[j];ac=a['source_corpus']=='real_documents_snapshot_A';bc=b['source_corpus']=='real_documents_snapshot_A';route='new_new' if ac and bc else ('new_legacy' if ac!=bc else 'legacy_legacy')
   if route_count[route]>=route_targets[route]:continue
   if family(a)==family(b) and s>.55:continue
   add('cross_document_two_doc',[i,j],f'bm25_like_{route}',s);route_count[route]+=1
   if sum(x['target_category']=='cross_document_two_doc' for x in seeds)>=220:break
  if sum(x['target_category']=='cross_document_two_doc' for x in seeds)>=220:break
 # Three-document clusters: anchor plus best distinct-document companions.
 for i in anchors:
  ranked=candidates(i,'cross_doc');chosen=[];used={nodes[i]['document_id']}
  for s,j in ranked:
   if nodes[j]['document_id'] in used:continue
   if family(nodes[i])==family(nodes[j]) and s>.55:continue
   chosen.append((s,j));used.add(nodes[j]['document_id'])
   if len(chosen)==2:break
  if len(chosen)==2:
   add('cross_document_three_plus_doc',[i,chosen[0][1],chosen[1][1]],'bm25_like_three_distinct_documents',(chosen[0][0]+chosen[1][0])/2)
  if sum(x['target_category']=='cross_document_three_plus_doc' for x in seeds)>=220:break
 savel(OUT/'sampled_seeds.jsonl',seeds);savel(OUT/'companion_candidates.jsonl',[x for x in seeds if x['target_category']!='single_node'])
 summary={'eligible_quality_nodes':N,'seed_count':len(seeds),'by_category':dict(Counter(x['target_category'] for x in seeds)),'cross_doc_routes':dict(Counter(x['discovery_route'] for x in seeds if x['target_category'].startswith('cross_document'))),'evidence_corpus':dict(Counter(e['source_corpus'] for x in seeds for e in x['evidence'])),'evidence_modality':dict(Counter(e['node_type'] for x in seeds for e in x['evidence']))}
 (OUT/'seed_discovery_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
