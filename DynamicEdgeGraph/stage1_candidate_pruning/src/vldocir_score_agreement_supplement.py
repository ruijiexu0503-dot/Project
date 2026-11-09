"""Additional disk-backed score/agreement statistics; never alters candidate sets."""
from __future__ import annotations
import argparse, csv, json, sqlite3
from array import array
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from .common import read_jsonl

ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
def tn(r): return 'p_'+r.replace('_','')
def rows(path):
    with path.open('w', newline='') as f:
        yield f
def write(path, data):
    data=list(data); path.parent.mkdir(parents=True,exist_ok=True)
    if not data: return
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
def q(v, ps=(10,25,50,75,90)):
    a=np.asarray(v,dtype=np.float32)
    return {'count':int(len(a)),**{f'p{x}':float(np.percentile(a,x)) for x in ps},'mean':float(a.mean()) if len(a) else None}
def svg(path, grid, title, ylabels):
    w,h,left,top,cw,ch=760,440,110,55,92,42; mx=max(max(r) for r in grid) or 1; s=[]
    for y,r in enumerate(grid):
        for x,v in enumerate(r):
            shade=int(235*(1-v/mx)); color=f'rgb(25,{shade},190)'
            s.append(f'<rect x="{left+x*cw}" y="{top+y*ch}" width="{cw-2}" height="{ch-2}" fill="{color}"/><text x="{left+x*cw+cw/2}" y="{top+y*ch+24}" fill="white" text-anchor="middle">{v:,}</text>')
    xs=''.join(f'<text x="{left+x*cw+cw/2}" y="{top-10}" text-anchor="middle">support {x+1}</text>' for x in range(6))
    ys=''.join(f'<text x="{left-8}" y="{top+y*ch+24}" text-anchor="end">{lab}</text>' for y,lab in enumerate(ylabels))
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><style>text{{font:10px sans-serif}}</style><text x="{left}" y="24" style="font:bold 15px sans-serif">{title}</text>{xs}{ys}{"".join(s)}<text x="{left}" y="{top+len(grid)*ch+28}">Pair-level maximum route-specific percentile; candidates are not semantic labels.</text></svg>')
def main():
 p=argparse.ArgumentParser(); p.add_argument('--run',type=Path,required=True); p.add_argument('--nodes',type=Path,required=True); p.add_argument('--stats-db',type=Path,required=True); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
 # The previous stats DB is input-only. All supplementary temporary state is separate.
 src=sqlite3.connect(f'file:{a.stats_db}?mode=ro',uri=True)
 db=a.out/'score_agreement_supplement.sqlite'
 if db.exists(): db.unlink()
 con=sqlite3.connect(db); con.execute('PRAGMA journal_mode=OFF'); con.execute('PRAGMA synchronous=OFF'); con.execute('PRAGMA temp_store=FILE')
 con.execute('CREATE TABLE pair_summary(pair INTEGER PRIMARY KEY,support INTEGER,best_pct REAL DEFAULT 0,mutual_routes INTEGER DEFAULT 0)')
 con.executemany('INSERT INTO pair_summary(pair,support) VALUES(?,?)',src.execute('SELECT pair,support FROM agreement'))
 con.commit()
 route_support=[]; high_single=[]; mutual_obs=[]
 # Route percentiles are empirical CDFs of the original *directed* Top-100 scores.
 # Each canonical pair uses the maximum directed score already held in p_<route>.
 for route in ROUTES:
  raw=array('f',(float(x['raw_score']) for x in read_jsonl(a.run/'route_candidates'/'top100'/f'{route}.jsonl')))
  ref=np.sort(np.frombuffer(raw,dtype=np.float32)); del raw
  tab=tn(route); vals=defaultdict(lambda: array('f')); mutual=defaultdict(lambda: array('f')); batch=[]
  for pair,score,support,flag in src.execute(f'SELECT p.pair,p.score,a.support,p.mutual FROM {tab} p JOIN agreement a USING(pair)'):
   pct=float(np.searchsorted(ref,float(score),side='right'))/len(ref)*100.0
   vals[int(support)].append(pct); mutual[(int(support),int(flag))].append(pct)
   batch.append((pct,int(flag),pair))
   if len(batch)>=50000:
    con.executemany('UPDATE pair_summary SET best_pct=MAX(best_pct,?),mutual_routes=mutual_routes+? WHERE pair=?',batch); batch.clear()
  if batch: con.executemany('UPDATE pair_summary SET best_pct=MAX(best_pct,?),mutual_routes=mutual_routes+? WHERE pair=?',batch)
  for s,v in vals.items():
   d=q(v); d.update({'route':route,'route_support_count':s,'percentile_definition':'empirical_CDF_of_directed_route_top100'}); route_support.append(d)
  for s in range(1,7):
   for flag,label in ((0,'non_mutual_in_this_route'),(1,'mutual_in_this_route')):
    d=q(mutual[(s,flag)]); d.update({'route':route,'route_support_count':s,'retrieval_reciprocity':label}); mutual_obs.append(d)
  high_single.append({'route':route,'single_route_pairs_at_or_above_P90':int(sum(1 for x in vals[1] if x>=90)),'single_route_pair_observations':len(vals[1])})
  con.commit()
 write(a.out/'route_score_percentile_by_support.csv',route_support)
 write(a.out/'high_percentile_single_route_by_route.csv',high_single)
 write(a.out/'mutual_percentile_by_route_and_support.csv',mutual_obs)
 # Exact agreement patterns: enables a direct audit of which route is missing at support 5.
 patterns=[]
 for r in range(1,7):
  cols=','.join(f'EXISTS(SELECT 1 FROM {tn(x)} p WHERE p.pair=agreement.pair) AS r{i}' for i,x in enumerate(ROUTES))
  # materialize only via the existing source connection, so no candidate data is changed
  break
 patt=defaultdict(int)
 for (pair,support) in src.execute('SELECT pair,support FROM agreement WHERE support>=5'):
  present=[]
  for i,route in enumerate(ROUTES):
   if src.execute(f'SELECT 1 FROM {tn(route)} WHERE pair=?',(pair,)).fetchone(): present.append(route)
  patt[tuple(present)]+=1
 for present,count in sorted(patt.items(),key=lambda z:(-z[1],z[0])):
  patterns.append({'route_support_count':len(present),'routes_present':' + '.join(present),'routes_missing':' + '.join(r for r in ROUTES if r not in present) or '(none)','bm25_present':'bm25' in present,'pair_count':count})
 write(a.out/'support5_and_support6_route_combinations.csv',patterns)
 # Pair-level bins use highest route-specific percentile among the supporting routes.
 bins=[('P0-P50',0,50),('P50-P90',50,90),('P90-P100',90,101)]
 grid=[[0]*6 for _ in bins]; midlow=[]
 for label,lo,hi in bins:
  for s,c in con.execute('SELECT support,COUNT(*) FROM pair_summary WHERE best_pct>=? AND best_pct<? GROUP BY support',(lo,hi)):
   grid[bins.index((label,lo,hi))][int(s)-1]=int(c)
 for label,lo,hi in bins[:2]:
  midlow.append({'best_score_percentile_bin':label,'support_at_least_3_pair_count':con.execute('SELECT COUNT(*) FROM pair_summary WHERE support>=3 AND best_pct>=? AND best_pct<?',(lo,hi)).fetchone()[0]})
 write(a.out/'pair_max_percentile_x_support.csv',({'best_score_percentile_bin':lab,'route_support_count':s+1,'pair_count':grid[i][s]} for i,(lab,_,_) in enumerate(bins) for s in range(6)))
 write(a.out/'medium_low_percentile_with_3plus_support.csv',midlow)
 svg(a.out/'figures'/'pair_max_percentile_x_route_support.svg',grid,'Pair maximum percentile × route agreement',[x[0] for x in bins])
 # Pair-level mutuality and support relation.
 mutual_pairs=[]
 for support,mutual_routes,count in con.execute('SELECT support,mutual_routes,COUNT(*) FROM pair_summary GROUP BY support,mutual_routes ORDER BY support,mutual_routes'):
  mutual_pairs.append({'route_support_count':support,'mutual_supporting_routes':mutual_routes,'pair_count':count,'all_supporting_routes_mutual':int(support)==int(mutual_routes),'any_supporting_route_mutual':int(mutual_routes)>0})
 write(a.out/'pair_mutuality_by_support.csv',mutual_pairs)
 # Coverage for Score × Agreement cells (support 1 / 2 / 3+ × pair max percentile bin).
 meta={x['id']:(x.get('document_id',''),x.get('node_type','unknown')) for x in read_jsonl(a.nodes)}
 ids=[x['node_id'] for x in read_jsonl(a.run.parent/'vldocir-representative-frozen-embeddings-20261107'/'retrieval_views.jsonl')]
 coverage=[]
 for slabel,where in [('support_1','support=1'),('support_2','support=2'),('support_3plus','support>=3')]:
  for blabel,lo,hi in bins:
   deg=Counter(); count=cd=cm=0
   for (pair,) in con.execute(f'SELECT pair FROM pair_summary WHERE {where} AND best_pct>=? AND best_pct<?',(lo,hi)):
    ai=int(pair)>>32; bi=int(pair)&0xffffffff; na,nb=ids[ai],ids[bi]; deg[na]+=1;deg[nb]+=1;count+=1
    da,ta=meta[na];db_,tb=meta[nb]; cd+=da!=db_; cm+=ta!=tb
   v=list(deg.values()); coverage.append({'agreement_bin':slabel,'best_score_percentile_bin':blabel,'candidate_pairs':count,'covered_nodes':len(deg),'isolated_canonical_nodes':len(meta)-len(deg),'mean_degree_over_canonical_universe':2*count/len(meta),'degree_p50':float(np.median(v)) if v else None,'degree_p90':float(np.percentile(v,90)) if v else None,'cross_document_pairs':cd,'cross_modal_pairs':cm})
 write(a.out/'score_agreement_coverage.csv',coverage)
 lines=['# Score × Agreement supplementary statistics','', 'All values use the completed Job 124260 bounded Top-100 candidate lists. No retriever, threshold, candidate set, or structural graph was changed. Route percentiles are empirical CDF percentiles computed separately within each route’s directed Top-100 score population. Pair-level bins use the maximum percentile among routes that retrieved that pair.','', '## High-percentile single-route candidates','', '| Route | P90+ single-route pairs |','|---|---:|']+[f"| {x['route']} | {x['single_route_pairs_at_or_above_P90']:,} |" for x in high_single]
 lines += ['', '## Medium/low maximum-percentile pairs with at least three supporting routes','', '| Pair maximum-percentile bin | Pair count |','|---|---:|']+[f"| {x['best_score_percentile_bin']} | {x['support_at_least_3_pair_count']:,} |" for x in midlow]
 lines += ['', 'See CSV tables and `figures/pair_max_percentile_x_route_support.svg` for full tables. “Mutual” means both directed retrievals occurred within the same route’s bounded Top-100 output; absence is not a negative relevance judgement.']
 (a.out/'SUPPLEMENT_REPORT.md').write_text('\n'.join(lines)+'\n')
 con.close();src.close(); print(json.dumps({'output':str(a.out)}))
if __name__=='__main__': main()
