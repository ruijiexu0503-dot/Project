"""Reproducible Score × reliable-route-support pruning over bounded candidates.

The BGE route is intentionally diagnostic-only until its broken CLS pooling is
repaired. This program never changes frozen embeddings, ANN outputs, or graphs.
"""
from __future__ import annotations
import argparse,csv,json,sqlite3
from array import array
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from .common import read_jsonl

ALL=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
def tn(r):return 'p_'+r.replace('_','')
def write(path,items):
 items=list(items);path.parent.mkdir(parents=True,exist_ok=True)
 if not items:return
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(items[0]),extrasaction='ignore');w.writeheader();w.writerows(items)
class DSU:
 def __init__(self,n):self.p=np.arange(n,dtype=np.int32);self.sz=np.ones(n,dtype=np.int32)
 def find(self,x):
  while self.p[x]!=x:self.p[x]=self.p[self.p[x]];x=int(self.p[x])
  return x
 def union(self,a,b):
  a=self.find(a);b=self.find(b)
  if a==b:return
  if self.sz[a]<self.sz[b]:a,b=b,a
  self.p[b]=a;self.sz[a]+=self.sz[b]
def sg(s):return 'support_1' if s==1 else 'support_2' if s==2 else 'support_3plus'
def quantile_thresholds(run,routes):
 out={}
 for r in routes:
  vals=np.fromiter((float(x['raw_score']) for x in read_jsonl(run/'route_candidates'/'top100'/f'{r}.jsonl')),dtype=np.float32)
  out[r]={str(q):float(np.quantile(vals,q)) for q in (.35,.4,.5,.55,.6,.65,.75,.8,.85,.9,.92,.94,.95)}
 return out
def threshold(qmap,r,q):
 # Config quantiles are decimal values and are deliberately route-local.
 key=str(float(q));
 return qmap[r].get(key,float(np.quantile(np.asarray(list(qmap[r].values())),.5)))
def gate_sql(policy,routes,qmap):
 clauses=[];gates={}
 for i,r in enumerate(routes):
  values=[]
  for group in ('support_1','support_2','support_3plus'):
   if policy['strategy']=='route_specific':q=policy['gates'][group][r]
   elif policy['strategy']=='support_mutual':q=None
   else:q=policy['gates'][group]
   if q is not None:values.append((group,threshold(qmap,r,q)))
  if policy['strategy']=='support_mutual':
   n=policy['gates_non_mutual'];m=policy['gates_any_mutual']
   values=[(g,threshold(qmap,r,n[g]),threshold(qmap,r,m[g])) for g in ('support_1','support_2','support_3plus')]
   case='CASE WHEN f.reliable_support=1 THEN '+str(values[0][1])+' WHEN f.reliable_support=2 THEN '+str(values[1][1])+' ELSE '+str(values[2][1])+' END'
   mcase='CASE WHEN f.reliable_support=1 THEN '+str(values[0][2])+' WHEN f.reliable_support=2 THEN '+str(values[1][2])+' ELSE '+str(values[2][2])+' END'
   clauses.append(f'(f.s{i} IS NOT NULL AND f.s{i} >= CASE WHEN f.mutual_routes>0 THEN ({mcase}) ELSE ({case}) END)')
   gates[r]={'non_mutual':dict(zip(('support_1','support_2','support_3plus'),[x[1] for x in values])),'any_mutual':dict(zip(('support_1','support_2','support_3plus'),[x[2] for x in values]))}
  else:
   case='CASE WHEN f.reliable_support=1 THEN '+str(values[0][1])+' WHEN f.reliable_support=2 THEN '+str(values[1][1])+' ELSE '+str(values[2][1])+' END'
   clauses.append(f'(f.s{i} IS NOT NULL AND f.s{i}>={case})');gates[r]=dict(zip(('support_1','support_2','support_3plus'),[x[1] for x in values]))
 return '('+' OR '.join(clauses)+')',gates
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--nodes',type=Path,required=True);p.add_argument('--views',type=Path,required=True);p.add_argument('--stats-db',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();cfg=json.loads(a.config.read_text());routes=cfg['reliable_routes'];a.out.mkdir(parents=True,exist_ok=True)
 meta={x['id']:{'doc':x.get('document_id',''),'type':x.get('node_type','unknown'),'source':x.get('data_source','unknown')} for x in read_jsonl(a.nodes)};ids=[x['node_id'] for x in read_jsonl(a.views)];ix={x:i for i,x in enumerate(ids)};total=len(meta);eligible=len(ids);qmap=quantile_thresholds(a.run,routes)
 db=a.out/'pruning.sqlite';
 if db.exists():db.unlink()
 con=sqlite3.connect(db);con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF');con.execute('PRAGMA temp_store=FILE');con.execute('ATTACH DATABASE ? AS base',(str(a.stats_db),))
 union=[]
 for i,r in enumerate(routes):union.append(f'SELECT pair,score,rank,mutual,{1<<i} AS bit,{i} AS ri FROM base.{tn(r)}')
 pivot=','.join(f'MAX(CASE WHEN ri={i} THEN score END) AS s{i},MIN(CASE WHEN ri={i} THEN rank END) AS rank{i}' for i in range(len(routes)))
 con.execute('CREATE TABLE features AS SELECT z.*,CASE WHEN b.pair IS NULL THEN 0 ELSE 1 END AS bge_diagnostic_present,b.rank AS bge_diagnostic_rank FROM (SELECT pair,COUNT(*) AS reliable_support,SUM(mutual) AS mutual_routes,SUM(bit) AS route_mask,'+pivot+' FROM ('+' UNION ALL '.join(union)+') GROUP BY pair) z LEFT JOIN base.'+tn('bge_en_icl_dense')+' b USING(pair)')
 con.execute('CREATE INDEX features_support ON features(reliable_support)');con.commit()
 (a.out/'manifest.json').write_text(json.dumps({'run_id':cfg['run_id'],'input_top_k':100,'canonical_nodes':total,'eligible_retrieval_nodes':eligible,'input_union_all_routes':34558320,'reliable_routes':routes,'bge_policy':cfg['bge_en_icl_dense'],'score_quantile_to_raw_threshold':qmap,'structural_graph_included':False},indent=2,sort_keys=True)+'\n')
 summaries=[]
 for pol in cfg['policies']:
  where,gates=gate_sql(pol,routes,qmap);name='sel_'+pol['id'].replace('-','_');con.execute(f'CREATE TABLE {name} AS SELECT * FROM features f WHERE {where}');con.execute(f'CREATE INDEX {name}_pair ON {name}(pair)');con.commit();count=con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
  policy_dir=a.out/'policies'/pol['id'];policy_dir.mkdir(parents=True,exist_ok=True);(policy_dir/'config_effective.json').write_text(json.dumps({'policy':pol,'raw_score_gates':gates,'bge':'diagnostic_only'},indent=2,sort_keys=True)+'\n')
  deg=np.zeros(eligible,dtype=np.int32);dsu=DSU(eligible);cross_doc=cross_mod=0;types=Counter();sources=Counter();type_nodes=defaultdict(set);source_nodes=defaultdict(set);combos=Counter();support=Counter();mask=Counter();mutual=Counter();bge=0;hubs=[]
  cur=con.execute(f'SELECT * FROM {name}');columns=[x[0] for x in cur.description]
  with (policy_dir/'selected_pairs.jsonl').open('w') as f:
   for row in cur:
    d=dict(zip(columns,row));pair=int(d['pair']);ai=pair>>32;bi=pair&0xffffffff;na,nb=ids[ai],ids[bi];ma,mb=meta[na],meta[nb];deg[ai]+=1;deg[bi]+=1;dsu.union(ai,bi);cross_doc+=ma['doc']!=mb['doc'];cross_mod+=ma['type']!=mb['type'];types[ma['type']]+=1;types[mb['type']]+=1;type_nodes[ma['type']].add(na);type_nodes[mb['type']].add(nb);sources[ma['source']]+=1;sources[mb['source']]+=1;source_nodes[ma['source']].add(na);source_nodes[mb['source']].add(nb);combos['|'.join(sorted((ma['type'],mb['type'])))]+=1;support[d['reliable_support']]+=1;mask[d['route_mask']]+=1;mutual['any' if d['mutual_routes'] else 'none']+=1;bge+=d['bge_diagnostic_present']
    evidence=[]
    for i,r in enumerate(routes):
     if d[f's{i}'] is not None:evidence.append({'route':r,'raw_score':d[f's{i}'],'best_rank':d[f'rank{i}'],'mutual':bool(d['mutual_routes'] and False)})
    f.write(json.dumps({'source_id':na,'target_id':nb,'candidate_status':'UNVERIFIED_STATIC_SEMANTIC_CANDIDATE','retained_by':pol['id'],'reliable_route_support':d['reliable_support'],'mutual_reliable_routes':d['mutual_routes'],'route_mask':d['route_mask'],'bge_diagnostic_present':bool(d['bge_diagnostic_present']),'evidence':evidence},sort_keys=True)+'\n')
  covered=int(np.count_nonzero(deg));dv=deg[deg>0];roots=Counter(dsu.find(i) for i in np.flatnonzero(deg));largest=max(roots.values(),default=0);top=np.argsort(deg)[-50:][::-1]
  write(policy_dir/'hub_nodes.csv',({'node_id':ids[int(i)],'degree':int(deg[int(i)]),'node_type':meta[ids[int(i)]]['type'],'document_id':meta[ids[int(i)]]['doc']} for i in top if deg[int(i)]>0))
  write(policy_dir/'route_combinations.csv',({'route_mask':m,'reliable_routes_present':' + '.join(r for i,r in enumerate(routes) if m&(1<<i)),'pairs':c} for m,c in sorted(mask.items())))
  write(policy_dir/'node_type_combinations.csv',({'node_type_combination':k,'pairs':v} for k,v in sorted(combos.items())))
  universe_type=Counter(x['type'] for x in meta.values());universe_source=Counter(x['source'] for x in meta.values())
  write(policy_dir/'node_type_coverage.csv',({'node_type':k,'canonical_nodes':universe_type[k],'covered_nodes':len(type_nodes[k]),'coverage_rate':len(type_nodes[k])/universe_type[k] if universe_type[k] else None,'edge_endpoints':types[k]} for k in sorted(universe_type)))
  write(policy_dir/'source_coverage.csv',({'data_source':k,'canonical_nodes':universe_source[k],'covered_nodes':len(source_nodes[k]),'coverage_rate':len(source_nodes[k])/universe_source[k] if universe_source[k] else None,'edge_endpoints':sources[k]} for k in sorted(universe_source)))
  audit=[]
  for s in (1,2,3,4,5):audit.append({'reliable_support':s,'input_pairs':con.execute('SELECT COUNT(*) FROM features WHERE reliable_support=?',(s,)).fetchone()[0],'retained_pairs':support[s]})
  write(policy_dir/'decision_audit.csv',audit)
  summary={'policy':pol['id'],'strategy':pol['strategy'],'edges':count,'retention_rate_of_all_route_union':count/34558320,'reliable_support_counts':json.dumps(dict(support),sort_keys=True),'bge_diagnostic_present_edges':bge,'mutual_any_edges':mutual['any'],'covered_eligible_nodes':covered,'isolated_eligible_nodes':eligible-covered,'covered_canonical_nodes':covered,'isolated_canonical_nodes':total-covered,'mean_degree_eligible':2*count/eligible,'degree_p50':float(np.quantile(dv,.5)) if len(dv) else 0,'degree_p90':float(np.quantile(dv,.9)) if len(dv) else 0,'degree_p95':float(np.quantile(dv,.95)) if len(dv) else 0,'degree_p99':float(np.quantile(dv,.99)) if len(dv) else 0,'degree_max':int(deg.max()),'components':len(roots),'largest_component_nodes':largest,'largest_component_eligible_coverage':largest/eligible,'cross_document_edges':cross_doc,'cross_document_rate':cross_doc/max(count,1),'cross_modal_edges':cross_mod,'cross_modal_rate':cross_mod/max(count,1)};summaries.append(summary)
 write(a.out/'policy_summary.csv',summaries)
 # Simple reproducible visualizations use exact CSV summary data.
 def bars(path,title,vals):
  w,h=900,430;mx=max(v[1] for v in vals) or 1;bw=700/max(len(vals),1);z=[]
  for i,(lab,val) in enumerate(vals):
   bh=300*val/mx;x=100+i*bw;z.append(f'<rect x="{x}" y="{360-bh}" width="{bw-8}" height="{bh}" fill="#2474a8"/><text x="{x+bw/2}" y="385" text-anchor="middle">{lab}</text><text x="{x+bw/2}" y="{350-bh}" text-anchor="middle">{val:,}</text>')
  path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><style>text{{font:11px sans-serif}}</style><text x="100" y="30" style="font:bold 16px sans-serif">{title}</text>{"".join(z)}</svg>')
 (a.out/'figures').mkdir(exist_ok=True);bars(a.out/'figures'/'threshold_vs_edge_count.svg','Natural edge counts by policy',[(x['policy'],x['edges']) for x in summaries]);bars(a.out/'figures'/'node_coverage_vs_edge_count.svg','Eligible-node coverage by policy',[(x['policy'],x['covered_eligible_nodes']) for x in summaries]);bars(a.out/'figures'/'cross_document_edges.svg','Cross-document edges by policy',[(x['policy'],x['cross_document_edges']) for x in summaries])
 report=['# Score × Route Support threshold pruning','', 'BGE-en-ICL is diagnostic-only: its frozen CLS vectors are collapsed and it is excluded from effective support, mutuality, and score gates. All output pairs are unverified semantic candidates; Structural Graph is not included.','', '| Policy | Edges | Mean degree | Eligible coverage | Cross-doc rate | Cross-modal rate |','|---|---:|---:|---:|---:|---:|']+[f"| {x['policy']} | {x['edges']:,} | {x['mean_degree_eligible']:.2f} | {x['covered_eligible_nodes']:,} | {x['cross_document_rate']:.2%} | {x['cross_modal_rate']:.2%} |" for x in summaries]
 (a.out/'REPORT.md').write_text('\n'.join(report)+'\n');con.close();print(json.dumps({'output':str(a.out),'policies':len(summaries)}))
if __name__=='__main__':main()
