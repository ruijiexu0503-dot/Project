"""Adopt a verified Pilot Stage-1 vector route as a strict Stage-2 node-vector input."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
from common import load_config, read_jsonl, repo_path, run_dir, sha256_file, write_json, write_jsonl

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--stage1-run',type=Path,default=Path('DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1'));p.add_argument('--route',default='qwen3_0_6b_dense');a=p.parse_args()
 c=load_config(a.config); views=list(read_jsonl(a.stage1_run/'retrieval_views.jsonl')); summary=json.loads((a.stage1_run/'models'/a.route/'embedding_summary.json').read_text()); vectors=np.load(a.stage1_run/'models'/a.route/'view_vectors.npy',mmap_mode='r')
 if len(views)!=vectors.shape[0] or summary['views']!=len(views):raise ValueError('view/vector count mismatch')
 if summary['view_order']!='exact retrieval_views.jsonl line order':raise ValueError('unsupported view-order contract')
 view_hash=sha256_file(a.stage1_run/'retrieval_views.jsonl')
 if summary['views_sha256']!=view_hash:raise ValueError('retrieval view hash mismatch')
 ids=[]; seen=set()
 for row_index,row in enumerate(views):
  node_id=row.get('node_id')
  if not node_id or node_id in seen:raise ValueError('missing or duplicate node ID in retrieval views')
  seen.add(node_id);ids.append({'node_id':node_id,'embedding_row':row_index,'view_id':row['view_id'],'representation_sha256':row['representation_sha256']})
 out=run_dir(c);out.mkdir(parents=True,exist_ok=True);write_jsonl(out/'embedding_ids.jsonl',ids)
 manifest={'source_stage1_run':str(a.stage1_run),'route':a.route,'encoder_id':c['encoder_id'],'views':len(views),'dimensions':int(vectors.shape[1]),'vector_dtype':str(vectors.dtype),'vector_sha256':sha256_file(a.stage1_run/'models'/a.route/'view_vectors.npy'),'retrieval_views_sha256':view_hash,'node_id_mapping':'embedding_ids.jsonl line order equals view_vectors.npy row order','input_representation':views[0].get('view_kind'),'query_used':False,'gold_labels_used':False}
 write_json(out/'route_manifest.json',manifest);print(json.dumps(manifest,ensure_ascii=False))
if __name__=='__main__':main()
