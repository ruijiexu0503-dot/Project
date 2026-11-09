"""Formal bounded Top-100 retrieval for one VL-DocIR Stage-1 route.

Dense routes use batched FAISS HNSW; BM25 uses SQLite FTS5.  Neither route
constructs a Node--Node score matrix.  Results are written incrementally and
Top-20/50 files are derived from each Top-100 ANN/sparse retrieval pass.
"""
from __future__ import annotations
import argparse,json,math,os,platform,resource,sqlite3,sys,time
from pathlib import Path
_LOCAL=Path(__file__).resolve().parents[1]/'.ann_deps'
if _LOCAL.exists():sys.path.insert(0,str(_LOCAL))
import numpy as np
from .common import read_jsonl,tokens

ROUTES={
 'qwen3_0_6b_dense':('Qwen3-Embedding-0.6B','qwen3_0_6b_dense'),
 'gte_qwen2_1_5b_dense':('gte-Qwen2-1.5B-instruct','gte_qwen2_1_5b_dense'),
 'bge_en_icl_dense':('BGE-en-ICL','bge_en_icl_dense'),
 'mxbai_dense':('mxbai-embed-large-v1','mxbai_dense'),
 'gte_large_dense':('gte-large-en-v1.5','gte_large_dense'),
}
def open_outputs(root:Path,route:str):
 out=[]
 for k in (20,50,100):
  p=root/'route_candidates'/f'top{k}'/f'{route}.jsonl';p.parent.mkdir(parents=True,exist_ok=True);out.append((k,p.open('w',encoding='utf-8')))
 return out
def emit(outputs,row):
 line=json.dumps(row,ensure_ascii=True,sort_keys=True)+'\n'
 for k,f in outputs:
  if row['rank']<=k:f.write(line)
def close(outputs):
 for _,f in outputs:f.close()
def dense(views,vector_path,route,root,batch,ef_search):
 import faiss
 vectors=np.load(vector_path,mmap_mode='r',allow_pickle=False)
 if len(vectors)!=len(views):raise ValueError(f'{route}: vector/view count mismatch')
 mat=np.asarray(vectors,dtype=np.float32); norms=np.linalg.norm(mat,axis=1)
 if not np.isfinite(mat).all() or np.any(norms==0):raise ValueError(f'{route}: invalid vectors')
 mat=np.ascontiguousarray(mat/norms[:,None],dtype=np.float32)
 index=faiss.IndexHNSWFlat(mat.shape[1],32,faiss.METRIC_INNER_PRODUCT);index.hnsw.efConstruction=160;index.hnsw.efSearch=ef_search
 started=time.perf_counter();index.add(mat);build=time.perf_counter()-started
 (root/'ann_indexes').mkdir(parents=True,exist_ok=True);faiss.write_index(index,str(root/'ann_indexes'/f'{route}.hnsw'))
 outputs=open_outputs(root,route);fetch=min(len(views),616);started=time.perf_counter();written=0
 for start in range(0,len(views),batch):
  scores,ids=index.search(mat[start:start+batch],fetch)
  for local,(ss,ii) in enumerate(zip(scores,ids)):
   source=start+local; seen={views[source]['node_id']};rank=0
   for score,target in zip(ss,ii):
    if target<0 or not math.isfinite(float(score)) or views[int(target)]['node_id'] in seen:continue
    seen.add(views[int(target)]['node_id']);rank+=1
    emit(outputs,{'source_id':views[source]['node_id'],'target_id':views[int(target)]['node_id'],'route':route,'direction':'forward','rank':rank,'raw_score':float(score),'model':ROUTES[route][0],'retrieval_engine':'faiss.IndexHNSWFlat','candidate_bounded':True})
    written+=1
    if rank==100:break
 close(outputs)
 return {'engine':'faiss.IndexHNSWFlat','approximate':True,'hnsw_m':32,'ef_construction':160,'ef_search':ef_search,'overfetch':fetch,'index_build_seconds':build,'search_seconds':time.perf_counter()-started,'directed_top100_records':written,'vector_shape':list(vectors.shape)}
def bm25(views,route,root):
 db=root/'bm25_index.sqlite';
 if db.exists():db.unlink()
 con=sqlite3.connect(db);con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF');con.execute('PRAGMA temp_store=FILE');con.execute("CREATE VIRTUAL TABLE docs USING fts5(node_id UNINDEXED, content, tokenize='unicode61')")
 con.executemany('INSERT INTO docs(node_id,content) VALUES (?,?)',((x['node_id'],x['retrieval_text']) for x in views));con.commit()
 outputs=open_outputs(root,route);started=time.perf_counter();written=0
 cur=con.cursor()
 for source,x in enumerate(views):
  # Quoted OR terms avoid query syntax injection; 128 terms bounds each sparse query.
  terms=list(dict.fromkeys(tokens(x['retrieval_text'])))[:128]
  if not terms:continue
  query=' OR '.join('"'+t.replace('"','')+'"' for t in terms)
  rows=cur.execute('SELECT node_id,-bm25(docs) FROM docs WHERE docs MATCH ? AND node_id != ? ORDER BY bm25(docs) LIMIT 100',(query,x['node_id'])).fetchall()
  for rank,(target,score) in enumerate(rows,1):
   emit(outputs,{'source_id':x['node_id'],'target_id':target,'route':route,'direction':'forward','rank':rank,'raw_score':float(score),'model':'BM25:SQLite-FTS5','retrieval_engine':'sqlite_fts5_bm25','candidate_bounded':True});written+=1
 close(outputs);con.close()
 return {'engine':'sqlite_fts5_bm25','tokenizer':'unicode61; quoted OR query; max 128 unique query terms','index_path':str(db),'search_seconds':time.perf_counter()-started,'directed_top100_records':written}
def main():
 p=argparse.ArgumentParser();p.add_argument('--views',type=Path,required=True);p.add_argument('--models-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--route',choices=sorted([*ROUTES,'bm25']),required=True);p.add_argument('--batch-size',type=int,default=256);p.add_argument('--ef-search',type=int,default=256);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 views=[json.loads(x) for x in a.views.open() if x.strip()];started=time.perf_counter()
 stats=bm25(views,a.route,a.output) if a.route=='bm25' else dense(views,a.models_root/ROUTES[a.route][1]/'view_vectors.npy',a.route,a.output,a.batch_size,a.ef_search)
 stats.update({'route':a.route,'views':len(views),'elapsed_seconds_total':time.perf_counter()-started,'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'host':platform.platform(),'all_pairs_scored':False})
 pth=a.output/'route_resources';pth.mkdir(exist_ok=True);(pth/f'{a.route}.json').write_text(json.dumps(stats,indent=2,sort_keys=True)+'\n');print(json.dumps(stats,sort_keys=True))
if __name__=='__main__':main()
