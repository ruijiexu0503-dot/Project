"""Freeze one current-pipeline dense encoder over VL-DocIR retrieval views.

Writes a model-specific matrix and JSON manifest; it never alters canonical nodes
or pre-existing frozen embeddings.  Completed outputs are resumable at model level.
"""
from __future__ import annotations
import argparse, gc, json, os, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"EvidenceNet"/"scripts"))
from compare_edge_embedding_models import load_tokenizer, pool_hidden

MODELS={
 "qwen3_0_6b_dense": ("Qwen3-Embedding-0.6B", "last_token", "left", 64),
 "gte_qwen2_1_5b_dense": ("gte-Qwen2-1.5B-instruct", "last_token", "left", 12),
 "bge_en_icl_dense": ("bge-en-icl", "cls", "right", 32),
 "mxbai_dense": ("mxbai-embed-large-v1", "cls", "right", 48),
 "gte_large_dense": ("gte-large-en-v1.5", "cls", "right", 48),
}
def digest(path: Path) -> str:
 import hashlib
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser(); p.add_argument("--views",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--route",choices=sorted(MODELS),required=True);p.add_argument("--batch-size",type=int);p.add_argument("--max-length",type=int,default=512);p.add_argument("--device",default="cuda");p.add_argument("--start",type=int,default=0);p.add_argument("--end",type=int);a=p.parse_args()
 model_dir,pooling,padding,default_batch=MODELS[a.route]; batch_size=a.batch_size or default_batch
 destination=a.output/a.route; summary_path=destination/"embedding_summary.json"
 if a.device=="cuda":
  import torch
  if not torch.cuda.is_available(): raise RuntimeError("CUDA requested but unavailable")
 import torch
 from transformers import AutoModel
 rows=[json.loads(x) for x in a.views.open() if x.strip()]
 end=len(rows) if a.end is None else a.end
 if not (0 <= a.start < end <= len(rows)): raise ValueError(f"invalid range [{a.start}, {end}) for {len(rows)} views")
 is_shard=(a.start != 0 or end != len(rows))
 if not is_shard and summary_path.exists(): print(summary_path.read_text()); return
 shard_path=destination/"shards"/f"{a.start:06d}_{end:06d}.npy"
 shard_summary=destination/"shards"/f"{a.start:06d}_{end:06d}.json"
 if is_shard and shard_path.exists() and shard_summary.exists(): print(shard_summary.read_text()); return
 selected=rows[a.start:end]; texts=[x["retrieval_text"] for x in selected]
 model_path=ROOT/"EvidenceNet"/"models"/model_dir
 if not model_path.exists(): raise FileNotFoundError(model_path)
 destination.mkdir(parents=True,exist_ok=True)
 tokenizer=load_tokenizer(model_path,padding); dtype=torch.bfloat16 if a.device=="cuda" else torch.float32
 kwargs=dict(local_files_only=True,trust_remote_code=True,torch_dtype=dtype)
 try: model=AutoModel.from_pretrained(model_path,attn_implementation="sdpa",**kwargs)
 except (TypeError,ValueError): model=AutoModel.from_pretrained(model_path,**kwargs)
 model=model.to(a.device).eval(); chunks=[]; started=time.monotonic(); peak=0
 for start in range(0,len(texts),batch_size):
  batch=tokenizer(texts[start:start+batch_size],padding=True,truncation=True,max_length=a.max_length,return_tensors="pt").to(a.device)
  with torch.inference_mode():
   forward=dict(batch)
   if getattr(model.config,"use_cache",None) is not None: forward["use_cache"]=False
   hidden=model(**forward).last_hidden_state
   vec=torch.nn.functional.normalize(pool_hidden(hidden,batch["attention_mask"],pooling).float(),p=2,dim=1)
  chunks.append(vec.cpu().numpy().astype(np.float32,copy=False)); peak=max(peak,torch.cuda.max_memory_allocated() if a.device=="cuda" else 0)
  if start % (batch_size*100)==0 or start+batch_size>=len(texts): print(f"{a.route} embedded {min(start+batch_size,len(texts))}/{len(texts)}",flush=True)
 vectors=np.concatenate(chunks)
 config_files=sorted(model_path.glob("*.json")); summary={"route":a.route,"model_directory":str(model_path.resolve()),"model_config_sha256":{x.name:digest(x) for x in config_files},"views":len(rows),"dimensions":int(vectors.shape[1]),"view_order":"exact retrieval_views.jsonl line order","views_sha256":digest(a.views),"embedding":{"device":torch.cuda.get_device_name(0) if a.device=="cuda" else "cpu","dtype":"bfloat16" if a.device=="cuda" else "float32","pooling":pooling,"padding_side":padding,"batch_size":batch_size,"max_length":a.max_length,"elapsed_seconds":time.monotonic()-started,"peak_cuda_allocated_bytes":int(peak)},"frozen_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
 summary["range"]={"start":a.start,"end":end,"total_views":len(rows)}
 if is_shard:
  shard_path.parent.mkdir(parents=True,exist_ok=True); np.save(shard_path,vectors)
  shard_summary.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
 else:
  np.save(destination/"view_vectors.npy",vectors); summary_path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
 print(json.dumps(summary,sort_keys=True)); del model; gc.collect()
 if a.device=="cuda":torch.cuda.empty_cache()
if __name__=="__main__":main()
