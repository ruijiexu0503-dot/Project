"""Set-based, disk-backed supplementary statistics for existing Top-100 routes.

This avoids per-pair UPDATE loops: SQLite aggregates the six route tables once,
then Python makes a single pass for coverage counters.
"""
from __future__ import annotations
import argparse, csv, json, sqlite3
from array import array
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from .common import read_jsonl

ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
def tn(r): return 'p_'+r.replace('_','')
def write(path,data):
 data=list(data); path.parent.mkdir(parents=True,exist_ok=True)
 if not data:return
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def moments(v):
 a=np.asarray(v,dtype=np.float32)
 if not a.size:return {'count':0,'p10':None,'p25':None,'p50':None,'p75':None,'p90':None,'mean':None}
 return {'count':int(a.size),'p10':float(np.percentile(a,10)),'p25':float(np.percentile(a,25)),'p50':float(np.percentile(a,50)),'p75':float(np.percentile(a,75)),'p90':float(np.percentile(a,90)),'mean':float(a.mean())}
def svg(path,grid):
 w,h,left,top,cw,ch=760,440,110,55,92,42;mx=max(max(x) for x in grid) or 1; out=[];labs=['P0-P50','P50-P90','P90-P100']
 for y,row in enumerate(grid):
  for x,v in enumerate(row):
   shade=int(235*(1-v/mx));out.append(f'<rect x="{left+x*cw}" y="{top+y*ch}" width="{cw-2}" height="{ch-2}" fill="rgb(25,{shade},190)"/><text x="{left+x*cw+cw/2}" y="{top+y*ch+24}" text-anchor="middle" fill="white">{v:,}</text>')
 xs=''.join(f'<text x="{left+x*cw+cw/2}" y="{top-10}" text-anchor="middle">support {x+1}</text>' for x in range(6));ys=''.join(f'<text x="{left-8}" y="{top+y*ch+24}" text-anchor="end">{lab}</text>' for y,lab in enumerate(labs))
 path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><style>text{{font:10px sans-serif}}</style><text x="{left}" y="24" style="font:bold 15px sans-serif">Pair maximum percentile bin × route agreement</text>{xs}{ys}{"".join(out)}<text x="{left}" y="{top+3*ch+28}">Maximum of route-specific percentile bins; candidate pairs are not semantic labels.</text></svg>')
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--nodes',type=Path,required=True);p.add_argument('--stats-db',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);(a.out/'figures').mkdir(exist_ok=True)
 db=a.out/'fast_statistics.sqlite'
 if db.exists():db.unlink()
 con=sqlite3.connect(db);con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF');con.execute('PRAGMA temp_store=FILE');con.execute("ATTACH DATABASE ? AS base",(str(a.stats_db),))
 # Build one union query with route bit masks and route-specific P50/P90 thresholds.
 refs={}; route_stats=[];route_support=[];mutual_obs=[];high=[]; selects=[]
 for i,r in enumerate(ROUTES):
  raw=np.fromiter((float(x['raw_score']) for x in read_jsonl(a.run/'route_candidates'/'top100'/f'{r}.jsonl')),dtype=np.float32)
  ref=np.sort(raw);p50=float(np.percentile(ref,50));p90=float(np.percentile(ref,90));refs[r]=ref
  tab=tn(r);bit=1<<i
  selects.append(f"SELECT pair, mutual, {bit} AS route_bit, CASE WHEN score>={p90!r} THEN 2 WHEN score>={p50!r} THEN 1 ELSE 0 END AS pct_bin FROM base.{tab}")
  # Exact empirical percentiles for route-level support/mutual tables; no DB writes.
  vals=defaultdict(lambda:array('f'));mvals=defaultdict(lambda:array('f'))
  cur=con.execute(f'SELECT p.score,a.support,p.mutual FROM base.{tab} p JOIN base.agreement a USING(pair)')
  while True:
   batch=cur.fetchmany(250000)
   if not batch:break
   score=np.fromiter((x[0] for x in batch),dtype=np.float32,count=len(batch));pct=np.searchsorted(ref,score,side='right')/len(ref)*100.0
   for j,(_,support,mutual) in enumerate(batch):
    vals[int(support)].append(float(pct[j]));mvals[(int(support),int(mutual))].append(float(pct[j]))
  for support,v in vals.items():
   d=moments(v);d.update({'route':r,'route_support_count':support,'percentile_definition':'empirical_CDF_of_directed_route_top100'});route_support.append(d)
  high.append({'route':r,'single_route_pairs_at_or_above_P90':int(np.count_nonzero(np.asarray(vals[1])>=90)),'single_route_pair_observations':len(vals[1])})
  for support in range(1,7):
   for flag,label in ((0,'non_mutual_in_this_route'),(1,'mutual_in_this_route')):
    d=moments(mvals[(support,flag)]);d.update({'route':r,'route_support_count':support,'retrieval_reciprocity':label});mutual_obs.append(d)
  route_stats.append({'route':r,'directed_score_count':int(len(ref)),'p50_raw_score':p50,'p90_raw_score':p90})
 # One grouped aggregation replaces six full-table per-row UPDATE passes.
 union=' UNION ALL '.join(selects)
 con.execute('CREATE TABLE pair_summary AS SELECT pair,COUNT(*) AS support,SUM(route_bit) AS route_mask,SUM(mutual) AS mutual_routes,MAX(pct_bin) AS best_bin FROM ('+union+') GROUP BY pair')
 con.execute('CREATE INDEX idx_summary_support_bin ON pair_summary(support,best_bin)');con.commit()
 write(a.out/'route_percentile_thresholds.csv',route_stats);write(a.out/'route_score_percentile_by_support.csv',route_support);write(a.out/'mutual_percentile_by_route_and_support.csv',mutual_obs);write(a.out/'high_percentile_single_route_by_route.csv',high)
 # Exact masks identify support=5 omissions without millions of point queries.
 patterns=[]
 for mask,count in con.execute('SELECT route_mask,COUNT(*) FROM pair_summary WHERE support>=5 GROUP BY route_mask ORDER BY COUNT(*) DESC'):
  present=[r for i,r in enumerate(ROUTES) if int(mask)&(1<<i)];missing=[r for r in ROUTES if r not in present]
  patterns.append({'route_support_count':len(present),'route_mask':int(mask),'routes_present':' + '.join(present),'routes_missing':' + '.join(missing) or '(none)','bm25_present':'bm25' in present,'pair_count':count})
 write(a.out/'support5_and_support6_route_combinations.csv',patterns)
 grid=[[0]*6 for _ in range(3)]
 for b,s,c in con.execute('SELECT best_bin,support,COUNT(*) FROM pair_summary GROUP BY best_bin,support'):
  grid[int(b)][int(s)-1]=int(c)
 write(a.out/'pair_max_percentile_x_support.csv',({'best_score_percentile_bin':('P0-P50','P50-P90','P90-P100')[b],'route_support_count':s+1,'pair_count':grid[b][s]} for b in range(3) for s in range(6)));svg(a.out/'figures'/'pair_max_percentile_x_route_support.svg',grid)
 write(a.out/'medium_low_percentile_with_3plus_support.csv',({'best_score_percentile_bin':('P0-P50','P50-P90')[b],'support_at_least_3_pair_count':con.execute('SELECT COUNT(*) FROM pair_summary WHERE support>=3 AND best_bin=?',(b,)).fetchone()[0]} for b in range(2)))
 write(a.out/'pair_mutuality_by_support.csv',({'route_support_count':s,'mutual_supporting_routes':m,'pair_count':c,'all_supporting_routes_mutual':s==m,'any_supporting_route_mutual':m>0} for s,m,c in con.execute('SELECT support,mutual_routes,COUNT(*) FROM pair_summary GROUP BY support,mutual_routes ORDER BY support,mutual_routes')))
 # One scan produces all 3×3 coverage cells, rather than nine scans of the summary.
 meta={x['id']:(x.get('document_id',''),x.get('node_type','unknown')) for x in read_jsonl(a.nodes)};ids=[x['node_id'] for x in read_jsonl(a.run.parent/'vldocir-representative-frozen-embeddings-20261107'/'retrieval_views.jsonl')]
 acc={(s,b):{'n':0,'cd':0,'cm':0,'deg':Counter()} for s in range(3) for b in range(3)}
 for pair,support,b in con.execute('SELECT pair,support,best_bin FROM pair_summary'):
  s=0 if support==1 else 1 if support==2 else 2;k=(s,int(b));z=acc[k];ai=int(pair)>>32;bi=int(pair)&0xffffffff;na,nb=ids[ai],ids[bi];z['n']+=1;z['deg'][na]+=1;z['deg'][nb]+=1;da,ta=meta[na];db_,tb=meta[nb];z['cd']+=da!=db_;z['cm']+=ta!=tb
 cov=[]
 for (s,b),z in acc.items():
  d=list(z['deg'].values());cov.append({'agreement_bin':('support_1','support_2','support_3plus')[s],'best_score_percentile_bin':('P0-P50','P50-P90','P90-P100')[b],'candidate_pairs':z['n'],'covered_nodes':len(z['deg']),'isolated_canonical_nodes':len(meta)-len(z['deg']),'mean_degree_over_canonical_universe':2*z['n']/len(meta),'degree_p50':float(np.median(d)) if d else None,'degree_p90':float(np.percentile(d,90)) if d else None,'cross_document_pairs':z['cd'],'cross_modal_pairs':z['cm']})
 write(a.out/'score_agreement_coverage.csv',cov)
 lines=['# Score × Agreement supplementary statistics (set-based implementation)','', 'Input: completed Job 124260 bounded Top-100 candidates. No encoder, ANN index, candidate set, threshold or structural graph was changed. Route percentiles are empirical CDFs within each route. Pair-level three-bin score category is the maximum of its supporting route-specific bins.','', '## High-percentile single-route candidates','','| Route | P90+ single-route pairs |','|---|---:|']+[f"| {x['route']} | {x['single_route_pairs_at_or_above_P90']:,} |" for x in high]
 (a.out/'SUPPLEMENT_REPORT.md').write_text('\n'.join(lines)+'\n');con.close();print(json.dumps({'output':str(a.out)}))
if __name__=='__main__':main()
