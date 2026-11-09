"""Disk-backed descriptive statistics for completed VL-DocIR Stage-1 retrieval."""
from __future__ import annotations
import argparse,csv,json,math,sqlite3,time
from array import array
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from .common import read_jsonl
ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
def tname(r):return 'p_'+r.replace('_','')
def pid(a,b,ix):
 x,y=ix[a],ix[b];return (min(x,y)<<32)|max(x,y)
def did(a,b,ix):return (ix[a]<<32)|ix[b]
def moments(v):
 a=np.asarray(v,dtype=np.float32);q=[1,5,10,25,50,75,90,95,99]
 return {'count':int(a.size),'min':float(a.min()),'max':float(a.max()),'mean':float(a.mean()),'median':float(np.median(a)),'std':float(a.std()),**{f'p{x}':float(np.percentile(a,x)) for x in q}}
def write_csv(path,rows):
 rows=list(rows);path.parent.mkdir(parents=True,exist_ok=True)
 if rows:
  with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def svg_heatmap(path,grid,title):
 h,w=400,760;left,top=95,45;cw,ch=58,42;mx=max(max(x) for x in grid) or 1
 cells=[]
 for y,row in enumerate(grid):
  for x,v in enumerate(row):
   c=int(255*(1-v/mx));cells.append(f'<rect x="{left+x*cw}" y="{top+y*ch}" width="{cw-2}" height="{ch-2}" fill="rgb(30,{c},220)"/><text x="{left+x*cw+cw/2}" y="{top+y*ch+25}" text-anchor="middle" fill="white">{v:,}</text>')
 xs=''.join(f'<text x="{left+x*cw+cw/2}" y="{top-8}" text-anchor="middle">support {x+1}</text>' for x in range(6));ys=''.join(f'<text x="{left-6}" y="{top+y*ch+25}" text-anchor="end">P{y*10}-P{(y+1)*10}</text>' for y in range(10))
 path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h+110}"><style>text{{font:10px sans-serif}}</style><text x="{left}" y="20" style="font: bold 15px sans-serif">{title}</text>{xs}{ys}{"".join(cells)}<text x="{left}" y="{top+10*ch+35}">Cells count route-pair observations; percentile is route-specific raw-score percentile.</text></svg>')
def svg_hist(path,rows,title):
 w,h,left,bottom=820,360,70,55;mx=max((r['count'] for r in rows),default=1);parts=[]
 for i,r in enumerate(rows):
  x=left+i*(w-left-20)/len(rows);bh=r['count']/mx*(h-bottom-55);parts.append(f'<rect x="{x:.1f}" y="{h-bottom-bh:.1f}" width="{(w-left-20)/len(rows)-2:.1f}" height="{bh:.1f}" fill="#2374ab"/>')
 path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><style>text{{font:12px sans-serif}}</style><text x="{left}" y="24" style="font-weight:bold">{title}</text><line x1="{left}" y1="{h-bottom}" x2="{w-20}" y2="{h-bottom}" stroke="black"/>{"".join(parts)}<text x="{left}" y="{h-12}">score bins from raw route score min to max</text></svg>')
def coverage(con,where,ids,meta,total):
 deg=Counter();crossdoc=crossmod=count=0
 for (p,) in con.execute('SELECT pair FROM agreement WHERE '+where):
  a,b=int(p)>>32,int(p)&0xffffffff;aa,bb=ids[a],ids[b];deg[aa]+=1;deg[bb]+=1;count+=1;ma,mb=meta[aa],meta[bb];crossdoc+=ma['doc']!=mb['doc'];crossmod+=ma['type']!=mb['type']
 vals=list(deg.values())
 return {'set':where,'candidate_pairs':count,'covered_nodes':len(deg),'isolated_nodes':total-len(deg),'mean_degree':2*count/total,'degree_p50':float(np.median(vals)) if vals else None,'degree_p90':float(np.percentile(vals,90)) if vals else None,'degree_max':max(vals,default=0),'cross_document_pairs':crossdoc,'cross_modal_pairs':crossmod}
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--canonical-nodes',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 for directory in ('figures','histograms','rank_score','thresholds'):(a.output/directory).mkdir(exist_ok=True)
 views=[json.loads(x) for x in (a.run.parent/'vldocir-representative-frozen-embeddings-20261107'/'retrieval_views.jsonl').open() if x.strip()];ids=[x['node_id'] for x in views];ix={x:i for i,x in enumerate(ids)}
 meta={x['id']:{'type':x.get('node_type','unknown'),'source':x.get('data_source','unknown'),'doc':x.get('document_id','')} for x in read_jsonl(a.canonical_nodes)};total=len(meta)
 db=a.output/'descriptive.sqlite'
 if db.exists(): db.unlink()
 con=sqlite3.connect(db);con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF');con.execute('PRAGMA temp_store=FILE')
 score_rows=[];rank_rows=[];type_rows=[];source_rows=[];thresholds={};percent_grid=[[0]*6 for _ in range(10)]
 # Per route: raw-score distribution, rank relation, type/source distributions and directed mutuality.
 for route in ROUTES:
  con.execute(f'DROP TABLE IF EXISTS {tname(route)}');con.execute(f'CREATE TABLE {tname(route)} (pair INTEGER PRIMARY KEY, score REAL NOT NULL, rank INTEGER NOT NULL, mutual INTEGER NOT NULL DEFAULT 0)')
  path=a.run/'route_candidates'/'top100'/f'{route}.jsonl';scores=array('f');direct=array('Q');rank_sum=[0.0]*101;rank_count=[0]*101;groups_t=defaultdict(lambda:array('f'));groups_s=defaultdict(lambda:array('f'))
  for row in read_jsonl(path):
   s=float(row['raw_score']);scores.append(s);direct.append(did(row['source_id'],row['target_id'],ix));rank=int(row['rank']);rank_sum[rank]+=s;rank_count[rank]+=1
   ma,mb=meta[row['source_id']],meta[row['target_id']];groups_t[ma['type']+'|'+mb['type']].append(s);groups_s[ma['source']+'|'+mb['source']].append(s)
  arr=np.frombuffer(scores,dtype=np.float32);stat=moments(arr);stat.update({'route':route,'metric':'cosine_inner_product_hnsw_higher_is_better' if route!='bm25' else 'SQLite_FTS5_BM25_negated_higher_is_better','score_direction':'higher_is_better'});score_rows.append(stat)
  thresholds[route]=[float(np.percentile(arr,q)) for q in range(0,101,10)]
  hist,bins=np.histogram(arr,bins=40);write_csv(a.output/'histograms'/f'{route}_score_histogram.csv',({'bin_left':float(bins[i]),'bin_right':float(bins[i+1]),'count':int(hist[i])} for i in range(len(hist))));svg_hist(a.output/'figures'/f'{route}_score_histogram.svg',[{'count':int(x)} for x in hist],route+' raw-score histogram')
  write_csv(a.output/'rank_score'/f'{route}.csv',({'route':route,'rank':i,'count':rank_count[i],'mean_score':rank_sum[i]/rank_count[i] if rank_count[i] else None} for i in range(1,101)))
  for group,vals in groups_t.items():
   d=moments(vals);d.update({'route':route,'group_kind':'node_type_pair','group':group});type_rows.append(d)
  for group,vals in groups_s.items():
   d=moments(vals);d.update({'route':route,'group_kind':'document_source_pair','group':group});source_rows.append(d)
  direct_np=np.sort(np.frombuffer(direct,dtype=np.uint64));batch=[]
  for row in read_jsonl(path):
   x,y=ix[row['source_id']],ix[row['target_id']];rev=np.uint64((y<<32)|x);pos=np.searchsorted(direct_np,rev);mut=int(pos<len(direct_np) and direct_np[pos]==rev);batch.append((pid(row['source_id'],row['target_id'],ix),float(row['raw_score']),int(row['rank']),mut))
   if len(batch)>=20000:
    con.executemany(f'INSERT INTO {tname(route)}(pair,score,rank,mutual) VALUES(?,?,?,?) ON CONFLICT(pair) DO UPDATE SET score=MAX(score,excluded.score),rank=MIN(rank,excluded.rank),mutual=MAX(mutual,excluded.mutual)',batch);batch.clear()
  if batch:con.executemany(f'INSERT INTO {tname(route)}(pair,score,rank,mutual) VALUES(?,?,?,?) ON CONFLICT(pair) DO UPDATE SET score=MAX(score,excluded.score),rank=MIN(rank,excluded.rank),mutual=MAX(mutual,excluded.mutual)',batch)
  con.commit()
 write_csv(a.output/'route_score_distribution.csv',score_rows);write_csv(a.output/'node_type_score_distribution.csv',type_rows);write_csv(a.output/'document_source_score_distribution.csv',source_rows)
 # Rebuild the canonical Top-100 union from the six route aggregates.  This avoids
 # relying on any optional/internal SQLite tables from the prior analysis run.
 con.execute('CREATE TABLE union_top100 (pair INTEGER PRIMARY KEY)')
 for route in ROUTES: con.execute(f'INSERT OR IGNORE INTO union_top100 SELECT pair FROM {tname(route)}')
 con.commit()
 # Agreement is retrieval-list membership, not an explicit non-relevance judgment.
 joins=' '.join(f'LEFT JOIN {tname(r)} x{i} ON u.pair=x{i}.pair' for i,r in enumerate(ROUTES));support='+'.join(f'(x{i}.pair IS NOT NULL)' for i in range(6));dense='+'.join(f'(x{i}.pair IS NOT NULL)' for i in range(5))
 con.execute('DROP TABLE IF EXISTS agreement');con.execute(f'CREATE TABLE agreement AS SELECT u.pair AS pair, {support} AS support, {dense} AS dense_support, (x5.pair IS NOT NULL) AS has_bm25 FROM union_top100 u {joins}');con.execute('CREATE UNIQUE INDEX agreement_pair ON agreement(pair)');con.commit()
 agreement=[]
 for n,c in con.execute('SELECT support,COUNT(*) FROM agreement GROUP BY support ORDER BY support'):agreement.append({'route_support_count':n,'pair_count':c,'pair_fraction':c/con.execute('SELECT COUNT(*) FROM agreement').fetchone()[0]})
 write_csv(a.output/'route_agreement_distribution.csv',agreement)
 overlap=json.loads((a.run/'analysis'/'route_overlap.json').read_text());(a.output/'route_overlap.json').write_text(json.dumps(overlap,indent=2,sort_keys=True))
 # Support/percentile grid and mutual/non-mutual comparisons at canonical-pair route observations.
 mutual_rows=[]
 for i,route in enumerate(ROUTES):
  tab=tname(route);cuts=thresholds[route]
  for score,support,mutual in con.execute(f'SELECT x.score,a.support,x.mutual FROM {tab} x JOIN agreement a USING(pair)'):
   b=min(9,max(0,int(np.searchsorted(cuts,float(score),side='right')-1)));percent_grid[b][int(support)-1]+=1
  for flag,label in ((1,'mutual'),(0,'non_mutual')):
   vals=array('f',(float(x[0]) for x in con.execute(f'SELECT score FROM {tab} WHERE mutual=?',(flag,))));d=moments(vals);d.update({'route':route,'retrieval_reciprocity':label});mutual_rows.append(d)
 write_csv(a.output/'mutual_retrieval_score_distribution.csv',mutual_rows);write_csv(a.output/'score_percentile_x_support.csv',({'percentile_bin':f'P{i*10}-P{(i+1)*10}','route_support_count':j+1,'route_pair_observations':percent_grid[i][j]} for i in range(10) for j in range(6)));svg_heatmap(a.output/'figures'/'score_percentile_x_route_support.svg',percent_grid,'Route-specific score percentile × route agreement')
 # Coverage subsets.  High single-route is P90+ in its sole route; low multi-route means every supporting route <= P50.
 # Materialize score flags only for coverage, keeping original candidate sets untouched.
 con.execute('DROP VIEW IF EXISTS agscore');con.execute(f'CREATE VIEW agscore AS SELECT a.*, '+','.join(f'x{i}.score AS s{i}' for i in range(6))+f' FROM agreement a {" ".join(f"LEFT JOIN {tname(r)} x{i} ON a.pair=x{i}.pair" for i,r in enumerate(ROUTES))}')
 # coverage helper expects agreement; temporarily express conditions using correlated route existence.
 cov=[]
 for n in (1,2,3,4):cov.append(coverage(con,f'support>={n}',ids,meta,total))
 hs='support=1 AND ('+' OR '.join(f'EXISTS(SELECT 1 FROM {tname(r)} z WHERE z.pair=agreement.pair AND z.score>={thresholds[r][9]})' for r in ROUTES)+')';cov.append(coverage(con,hs,ids,meta,total))
 lm='support>=2 AND '+' AND '.join(f'(NOT EXISTS(SELECT 1 FROM {tname(r)} z WHERE z.pair=agreement.pair) OR EXISTS(SELECT 1 FROM {tname(r)} z WHERE z.pair=agreement.pair AND z.score<={thresholds[r][5]}))' for r in ROUTES);cov.append(coverage(con,lm,ids,meta,total))
 labels=['single_route_only','at_least_2_routes','at_least_3_routes','at_least_4_routes','high_percentile_single_route','multi_route_low_percentile'];
 for row,label in zip(cov,labels):row['set']=label
 write_csv(a.output/'candidate_coverage.csv',cov)
 report=['# VL-DocIR Stage 1 — Retrieval Score and Route Agreement Statistics','',f'Input: completed Job 124260 / six bounded Top-100 routes. Canonical universe {total:,}; semantic candidate analysis excludes Structural Graph. Scores retain their route-specific metric and **higher-is-better direction**; raw values are never compared across routes.','', '## Route agreement','', '| Support routes | Pair count | Fraction of semantic union |','|---:|---:|---:|']+[f"| {x['route_support_count']} | {x['pair_count']:,} | {x['pair_fraction']:.2%} |" for x in agreement]
 report+=['','Detailed raw-score distributions, rank curves, type/source group tables, mutuality tables, coverage sets, CSV summaries and SVG charts are in this directory. Score percentile × support cells count route-pair observations, not independently verified semantic edges. Non-retrieval by a route is absence from its bounded Top-100 list, not an explicit non-relevance decision.']
 (a.output/'REPORT.md').write_text('\n'.join(report)+'\n');con.close();print(json.dumps({'output':str(a.output),'union_pairs':sum(x['pair_count'] for x in agreement)}))
if __name__=='__main__':main()
