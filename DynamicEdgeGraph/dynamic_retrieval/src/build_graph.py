"""Build a deterministic new-namespace directed candidate graph from frozen node vectors.

No query, answer, qrel, or test-time field is read.  Edges are document-local:
top semantic neighbours plus explicit adjacent-page provenance.  Cross-document
retrieval remains available through the Dense candidate channel, rather than
pretending an arbitrary cross-document edge was licensed.
"""
from __future__ import annotations
import argparse,json,hashlib
from collections import defaultdict
from pathlib import Path
import numpy as np

def rows(p):
 with p.open() as f: yield from (json.loads(x) for x in f if x.strip())
def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--embeddings',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--semantic-neighbors',type=int,default=3);p.add_argument('--page-neighbors',type=int,default=2);a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=False);views=list(rows(a.data/'representations/retrieval_views.jsonl'));ids=list(rows(a.data/'representations/embedding_ids.jsonl'));v=np.load(a.embeddings/'qwen3_0_6b_dense/view_vectors.npy',mmap_mode='r')
 if len(views)!=len(ids) or len(ids)!=len(v):raise ValueError('view/ID/vector mismatch')
 if any(x['embedding_row']!=i or x['node_id']!=views[i]['node_id'] for i,x in enumerate(ids)):raise ValueError('noncanonical embedding row mapping')
 groups=defaultdict(list)
 for i,x in enumerate(views):groups[x['document_id']].append(i)
 edges=[]
 for doc,index in sorted(groups.items()):
  index=np.asarray(sorted(index),dtype=int); mat=np.asarray(v[index],dtype=np.float32);mat/=np.maximum(np.linalg.norm(mat,axis=1,keepdims=True),1e-12)
  # Blockwise exact within-document cosine; no global O(N^2) pseudo-graph.
  for local,i in enumerate(index):
   scores=mat@mat[local];scores[local]=-np.inf; take=min(a.semantic_neighbors,len(index)-1)
   if take:
    chosen=np.argpartition(-scores,take-1)[:take];chosen=chosen[np.argsort(-scores[chosen],kind='stable')]
    for j in chosen: edges.append({'source_id':views[i]['node_id'],'target_id':views[index[j]]['node_id'],'provenance':['within_document_embedding_topk'],'source_rank':int(list(chosen).index(j)+1),'semantic_cosine':float(scores[j])})
   page_candidates=sorted((abs(int(views[j]['page_number'])-int(views[i]['page_number'])),views[j]['node_id'],j) for j in index if j!=i and abs(int(views[j]['page_number'])-int(views[i]['page_number']))==1)[:a.page_neighbors]
   for _,_,j in page_candidates:edges.append({'source_id':views[i]['node_id'],'target_id':views[j]['node_id'],'provenance':['same_document_adjacent_page'],'source_rank':None,'semantic_cosine':None})
 # Merge duplicate endpoints while preserving provenance; IDs stabilize iteration.
 merged={}
 for e in edges:
  k=(e['source_id'],e['target_id']); old=merged.setdefault(k,{**e,'provenance':set(e['provenance'])});old['provenance'].update(e['provenance'])
 out=[]
 for e in merged.values(): e['provenance']=sorted(e['provenance']);out.append(e)
 out.sort(key=lambda e:(e['source_id'],e['target_id']))
 with (a.out/'edges.jsonl').open('w') as f:
  for e in out:f.write(json.dumps(e,sort_keys=True)+'\n')
 manifest={'nodes':len(views),'edges':len(out),'documents':len(groups),'embedding_path':str(a.embeddings/'qwen3_0_6b_dense/view_vectors.npy'),'semantic_neighbors':a.semantic_neighbors,'page_neighbors':a.page_neighbors,'candidate_policy':'new-namespace, document-local exact vector top-k plus adjacent-page topology; no query/gold/qrel/test input','cross_document_policy':'Dense retrieval only in initial release'}
 (a.out/'graph_manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest))
if __name__=='__main__':main()
