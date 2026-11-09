"""Streaming/SQLite analysis of formal VL-DocIR bounded candidate retrieval."""
from __future__ import annotations
import argparse,csv,json,sqlite3,time
from array import array
from collections import Counter
from pathlib import Path
import numpy as np
from .common import read_jsonl
ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
KS=[20,50,100]
def pair_id(a,b,ix):
 x,y=ix[a],ix[b]; return (min(x,y)<<32)|max(x,y)
def table(route,label):return 'r_'+route.replace('_','')+'_'+label
def insert_pairs(con,tbl,items):
 con.executemany(f'INSERT OR IGNORE INTO {tbl}(pair) VALUES (?)',((int(x),) for x in items));items.clear()
def describe(con,tbl,ids,meta,total):
 cur=con.execute(f'SELECT pair FROM {tbl}');degree=Counter();cross_doc=cross_mod=count=0
 for (p,) in cur:
  a,b=int(p)>>32,int(p)&0xffffffff;aid,bid=ids[a],ids[b];degree[aid]+=1;degree[bid]+=1;count+=1
  ma,mb=meta.get(aid,{}),meta.get(bid,{})
  cross_doc+=ma.get('document_id')!=mb.get('document_id');cross_mod+=ma.get('node_type')!=mb.get('node_type')
 vals=sorted(degree.values());q=lambda x:float(np.quantile(vals,x)) if vals else None
 return {'unique_candidate_pairs':count,'possible_node_pairs':total*(total-1)//2,'candidate_pair_fraction':count/(total*(total-1)//2),'covered_nodes':len(degree),'isolated_nodes':total-len(degree),'mean_candidate_degree_all_nodes':2*count/total,'mean_candidate_degree_covered_nodes':2*count/max(len(degree),1),'degree_p50_covered':q(.5),'degree_p90_covered':q(.9),'degree_max':max(vals,default=0),'cross_document_pairs':cross_doc,'cross_modality_pairs':cross_mod,'degree_histogram':dict(Counter(vals))}
def union(con,name,tables):
 con.execute(f'DROP TABLE IF EXISTS {name}');con.execute(f'CREATE TABLE {name} (pair INTEGER PRIMARY KEY)')
 for t in tables:con.execute(f'INSERT OR IGNORE INTO {name} SELECT pair FROM {t}')
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--canonical-nodes',type=Path,required=True);a=p.parse_args();run=a.run;out=run/'analysis';out.mkdir(exist_ok=True)
 views=[json.loads(x) for x in (run.parent/'vldocir-representative-frozen-embeddings-20261107'/'retrieval_views.jsonl').open() if x.strip()]
 ids=[x['node_id'] for x in views];ix={x:i for i,x in enumerate(ids)}
 meta={x['id']:{'document_id':x.get('document_id'),'node_type':x.get('node_type')} for x in read_jsonl(a.canonical_nodes)};total=len(meta)
 for r in ROUTES:
  if not (run/'route_candidates'/'top100'/f'{r}.jsonl').exists():raise FileNotFoundError(f'missing route result: {r}')
 db=out/'candidate_analysis.sqlite';
 if db.exists():db.unlink()
 con=sqlite3.connect(db);con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF');con.execute('PRAGMA temp_store=FILE')
 for r in ROUTES:
  for k in KS:con.execute(f'CREATE TABLE {table(r,"k"+str(k))} (pair INTEGER PRIMARY KEY)')
  scores=array('f');buf={k:[] for k in KS}
  for row in read_jsonl(run/'route_candidates'/'top100'/f'{r}.jsonl'):
   scores.append(float(row['raw_score']));q=pair_id(row['source_id'],row['target_id'],ix)
   for k in KS:
    if int(row['rank'])<=k:buf[k].append(q)
   if len(buf[100])>=20000:
    for k in KS:insert_pairs(con,table(r,'k'+str(k)),buf[k])
  for k in KS:insert_pairs(con,table(r,'k'+str(k)),buf[k])
  thresholds={f'q{q}':float(np.quantile(np.frombuffer(scores,dtype=np.float32),q/100)) for q in (50,75,90)}
  (out/'thresholds').mkdir(exist_ok=True);(out/'thresholds'/f'{r}.json').write_text(json.dumps(thresholds,indent=2,sort_keys=True))
  for label in thresholds:con.execute(f'CREATE TABLE {table(r,label)} (pair INTEGER PRIMARY KEY)')
  bufs={label:[] for label in thresholds}
  for row in read_jsonl(run/'route_candidates'/'top100'/f'{r}.jsonl'):
   q=pair_id(row['source_id'],row['target_id'],ix);score=float(row['raw_score'])
   for label,gate in thresholds.items():
    if score>=gate:bufs[label].append(q)
   if max(map(len,bufs.values()))>=20000:
    for label in thresholds:insert_pairs(con,table(r,label),bufs[label])
  for label in thresholds:insert_pairs(con,table(r,label),bufs[label])
  con.commit()
 # unions, top-k distributions, score sensitivity and nearest available score budget to rank20
 topk=[];unions={}
 for k in KS:
  name='u_k'+str(k);union(con,name,[table(r,'k'+str(k)) for r in ROUTES]);unions['k'+str(k)]=name;topk.append({'top_k':k,**describe(con,name,ids,meta,total)})
 union(con,'u_q50',[table(r,'q50') for r in ROUTES]);union(con,'u_q75',[table(r,'q75') for r in ROUTES]);union(con,'u_q90',[table(r,'q90') for r in ROUTES])
 threshold=[]
 for label in ('q50','q75','q90'):threshold.append({'scheme':'OR_UNION_independent_route_quantiles','gate':label,**describe(con,'u_'+label,ids,meta,total)})
 target=topk[0]['unique_candidate_pairs'];chosen=min(('q50','q75','q90'),key=lambda z:abs(con.execute(f'SELECT COUNT(*) FROM u_{z}').fetchone()[0]-target));union(con,'u_score_budget',[table(r,chosen) for r in ROUTES])
 threshold.append({'scheme':'nearest_available_score_budget_to_rank20','gate':chosen,**describe(con,'u_score_budget',ids,meta,total)})
 # route distribution, unique contribution and pairwise overlap at Top-100.
 fields=['route','unique_candidate_pairs','possible_node_pairs','candidate_pair_fraction','covered_nodes','isolated_nodes','mean_candidate_degree_all_nodes','mean_candidate_degree_covered_nodes','degree_p50_covered','degree_p90_covered','degree_max','cross_document_pairs','cross_modality_pairs','unique_to_route','leave_one_out_pairs_lost']
 summary=[];allname=unions['k100']
 for r in ROUTES:
  t=table(r,'k100');other=[table(x,'k100') for x in ROUTES if x!=r];union(con,'tmp_other',other)
  unique=con.execute(f'SELECT COUNT(*) FROM {t} WHERE pair NOT IN (SELECT pair FROM tmp_other)').fetchone()[0];d=describe(con,t,ids,meta,total);d.update({'route':r,'unique_to_route':unique,'leave_one_out_pairs_lost':unique});summary.append(d)
 d=describe(con,allname,ids,meta,total);d.update({'route':'ALL_6_OR_UNION','unique_to_route':None,'leave_one_out_pairs_lost':None});summary.append(d)
 with (out/'route_distribution.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(summary)
 with (out/'topk_sensitivity.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(topk[0]));w.writeheader();w.writerows(topk)
 with (out/'threshold_sensitivity.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(threshold[0]));w.writeheader();w.writerows(threshold)
 overlap={}
 for i,left in enumerate(ROUTES):
  for right in ROUTES[i+1:]:
   lt,rt=table(left,'k100'),table(right,'k100');inter=con.execute(f'SELECT COUNT(*) FROM {lt} INNER JOIN {rt} USING(pair)').fetchone()[0];lc=con.execute(f'SELECT COUNT(*) FROM {lt}').fetchone()[0];rc=con.execute(f'SELECT COUNT(*) FROM {rt}').fetchone()[0];overlap[left+'__'+right]={'intersection_pairs':inter,'jaccard':inter/(lc+rc-inter),'overlap_left':inter/lc,'overlap_right':inter/rc}
 (out/'route_overlap.json').write_text(json.dumps({'pairwise':overlap,'structural_in_semantic_union':False},indent=2,sort_keys=True))
 # Compact union files refer to full directed provenance held in route_candidates/top100.
 for label,name in [('top20',unions['k20']),('top50',unions['k50']),('top100',unions['k100']),('score_budget_matched', 'u_score_budget')]:
  pth=out/'candidate_unions'/f'{label}.jsonl';pth.parent.mkdir(exist_ok=True)
  with pth.open('w') as f:
   for (v,) in con.execute(f'SELECT pair FROM {name} ORDER BY pair'):
    x,y=int(v)>>32,int(v)&0xffffffff;f.write(json.dumps({'source_id':ids[x],'target_id':ids[y],'candidate_status':'UNVERIFIED_STATIC_SEMANTIC_CANDIDATE','provenance':'see route_candidates/top100 for route, score, rank, direction'},sort_keys=True)+'\n')
 resources={r:json.loads((run/'route_resources'/f'{r}.json').read_text()) for r in ROUTES}
 (out/'resource_summary.json').write_text(json.dumps({'routes':resources,'canonical_nodes':total,'eligible_views':len(ids),'all_pairs_scored':False,'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},indent=2,sort_keys=True))
 report=['# VL-DocIR Stage 1: Formal bounded candidate analysis','',f'Canonical universe: {total:,}; eligible retrieval views: {len(ids):,}. All results are unverified static semantic candidates; Structural Graph is excluded.','', '| Top-K | Union pairs | Covered nodes | Isolated | Pruning rate |','|---:|---:|---:|---:|---:|']+[f"| {x['top_k']} | {x['unique_candidate_pairs']:,} | {x['covered_nodes']:,} | {x['isolated_nodes']:,} | {1-x['candidate_pair_fraction']:.4%} |" for x in topk]
 (out/'REPORT.md').write_text('\n'.join(report)+'\n');con.close();print(json.dumps({'analysis':str(out),'topk':{x['top_k']:x['unique_candidate_pairs'] for x in topk},'score_budget_gate':chosen}))
if __name__=='__main__':main()
