"""GPU batch cross-scoring of the existing five-route bounded candidate union."""
from __future__ import annotations
import argparse,json,sqlite3,time
from pathlib import Path
import numpy as np
ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','mxbai_dense','gte_large_dense']
def tn(r):return 'p_'+r.replace('_','')
def main():
 p=argparse.ArgumentParser();p.add_argument('--stats-db',type=Path,required=True);p.add_argument('--models',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--batch',type=int,default=32768);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 import torch
 if not torch.cuda.is_available():raise RuntimeError('CUDA required for bounded candidate cross-scoring')
 con=sqlite3.connect(f'file:{a.stats_db}?mode=ro',uri=True)
 # SQLite UNION deduplicates canonical pairs and streams in deterministic pair order.
 tables=ROUTES+['bm25']; sql=' UNION '.join('SELECT pair FROM '+tn(r) for r in tables)
 n=con.execute('SELECT COUNT(*) FROM ('+sql+')').fetchone()[0]
 pairs=np.lib.format.open_memmap(a.out/'effective_union_pairs.npy',mode='w+',dtype=np.uint64,shape=(n,));cur=con.execute(sql);k=0
 while True:
  rows=cur.fetchmany(1_000_000)
  if not rows:break
  pairs[k:k+len(rows)]=[x[0] for x in rows];k+=len(rows)
 if k!=n:raise RuntimeError((k,n))
 # Evidence is persisted in the exact same sorted pair order as cross scores.
 # BGE is diagnostic-only and never contributes to support/mutuality here.
 joins=' '.join(f'LEFT JOIN {tn(r)} r{i} ON u.pair=r{i}.pair' for i,r in enumerate(ROUTES))
 evidence_sql='WITH u AS ('+sql+') SELECT u.pair,'+'+'.join(f'(r{i}.pair IS NOT NULL)' for i in range(4))+' AS support,'+'+'.join(f'COALESCE(r{i}.mutual,0)' for i in range(4))+' AS mutual_routes,b.score AS bm25_score,CASE WHEN b.pair IS NULL THEN 0 ELSE 1 END AS bm25_present,CASE WHEN x.pair IS NULL THEN 0 ELSE 1 END AS bge_diagnostic_present FROM u '+joins+' LEFT JOIN '+tn('bm25')+' b ON u.pair=b.pair LEFT JOIN '+tn('bge_en_icl_dense')+' x ON u.pair=x.pair ORDER BY u.pair'
 dtype=np.dtype([('support','u1'),('mutual_routes','u1'),('bm25_score','f4'),('bm25_present','u1'),('bge_diagnostic_present','u1')]);evidence=np.lib.format.open_memmap(a.out/'effective_union_evidence.npy',mode='w+',dtype=dtype,shape=(n,));cur=con.execute(evidence_sql);k=0
 while True:
  rows=cur.fetchmany(1_000_000)
  if not rows:break
  got=np.asarray([x[0] for x in rows],dtype=np.uint64)
  if not np.array_equal(got,pairs[k:k+len(rows)]):raise RuntimeError('evidence pair-order mismatch')
  evidence['support'][k:k+len(rows)]=[x[1] for x in rows];evidence['mutual_routes'][k:k+len(rows)]=[x[2] for x in rows];evidence['bm25_score'][k:k+len(rows)]=[np.nan if x[3] is None else x[3] for x in rows];evidence['bm25_present'][k:k+len(rows)]=[x[4] for x in rows];evidence['bge_diagnostic_present'][k:k+len(rows)]=[x[5] for x in rows];k+=len(rows)
 if k!=n:raise RuntimeError(('evidence_count',k,n))
 scores=np.lib.format.open_memmap(a.out/'dense_cross_scores.npy',mode='w+',dtype=np.float32,shape=(n,len(ROUTES)))
 started=time.time();device='cuda'
 for ri,r in enumerate(ROUTES):
  v=np.load(a.models/r/'view_vectors.npy',mmap_mode='r');mat=torch.from_numpy(np.asarray(v,dtype=np.float32)).to(device);mat=torch.nn.functional.normalize(mat,p=2,dim=1)
  for start in range(0,n,a.batch):
   end=min(n,start+a.batch);ps=np.asarray(pairs[start:end]);left=torch.from_numpy((ps>>np.uint64(32)).astype(np.int64)).to(device);right=torch.from_numpy((ps&np.uint64(0xffffffff)).astype(np.int64)).to(device)
   scores[start:end,ri]=(mat[left]*mat[right]).sum(dim=1).float().cpu().numpy()
  del mat;torch.cuda.empty_cache();print(json.dumps({'route':r,'done_pairs':n,'elapsed_seconds':time.time()-started}),flush=True)
 meta={'routes':ROUTES,'pairs':n,'pair_encoding':'(min_retrieval_view_index << 32) | max_retrieval_view_index','score':'cosine_similarity_of_normalized_frozen_vectors','candidate_universe':'union_of_five_effective_route_top100_candidates','evidence_alignment':'effective_union_evidence.npy aligns one-to-one with effective_union_pairs.npy; BGE is diagnostic-only','device':torch.cuda.get_device_name(0),'elapsed_seconds':time.time()-started}
 (a.out/'cross_score_manifest.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n');print(json.dumps(meta,sort_keys=True))
if __name__=='__main__':main()
