"""Merge completed description shards only after exact task/crop validation."""
from __future__ import annotations
import argparse, hashlib
from pathlib import Path
from common import read_jsonl, write_json, write_jsonl
def sha(path):
 h=hashlib.sha256();
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--tasks',type=Path,required=True);p.add_argument('--parts',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 tasks={r['visual_node_id']:r for r in read_jsonl(a.tasks)}; rows={}
 for path in sorted(a.parts.glob('part_*.jsonl')):
  for r in read_jsonl(path):
   key=r.get('visual_node_id')
   if key in rows:raise ValueError('duplicate description: '+str(key))
   if key not in tasks or r.get('crop_sha256')!=tasks[key]['crop_sha256'] or not str(r.get('description','')).strip():raise ValueError('invalid description record: '+str(key))
   if sha(Path(r['crop']))!=r['crop_sha256']:raise ValueError('stale crop: '+str(key))
   rows[key]=r
 missing=sorted(set(tasks)-set(rows))
 if missing:raise ValueError(f'incomplete description set: missing {len(missing)}')
 a.out.mkdir(parents=True,exist_ok=True);write_jsonl(a.out/'visual_descriptions.jsonl',(rows[k] for k in sorted(rows)))
 write_json(a.out/'description_manifest.json',{'tasks':len(tasks),'descriptions':len(rows),'complete':True,'task_file_sha256':sha(a.tasks),'description_file_sha256':sha(a.out/'visual_descriptions.jsonl')});print(len(rows))
if __name__=='__main__':main()
