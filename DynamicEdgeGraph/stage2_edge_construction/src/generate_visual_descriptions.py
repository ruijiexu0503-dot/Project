"""Generate one crop-only, provenance-recorded visual description per task shard."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from EvidenceNet.evidence_graph.llm_client import create_llm
from common import read_jsonl, write_jsonl
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def main():
    p=argparse.ArgumentParser(); p.add_argument('--tasks',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--start',type=int,required=True); p.add_argument('--count',type=int,default=50); p.add_argument('--model',type=Path,required=True); a=p.parse_args()
    tasks=list(read_jsonl(a.tasks))[a.start:a.start+a.count]
    if not tasks: raise ValueError('empty task shard')
    llm=create_llm({'provider':'transformers','model':str(a.model),'dtype':'bfloat16','device_map':'auto','require_cuda':True,'enable_thinking':False})
    rows=[]
    for task in tasks:
        crop=Path(task['crop'])
        if not crop.is_file() or sha(crop)!=task['crop_sha256']: raise ValueError('missing or stale crop: '+task['visual_node_id'])
        result=llm.generate_raw_with_images(task['system'],task['prompt'],[str(crop)],180)
        description=result.raw.strip()
        if not description: raise ValueError('empty description: '+task['visual_node_id'])
        rows.append({**task,'description':description,'model':str(a.model.resolve()),'model_timestamp':result.timestamp,'description_status':'UNVERIFIED_RETRIEVAL_REPRESENTATION'})
    a.output.parent.mkdir(parents=True,exist_ok=True); write_jsonl(a.output,rows); print(json.dumps({'start':a.start,'rows':len(rows),'output':str(a.output)}))
if __name__=='__main__': main()
