"""Validate and merge independently frozen VL-DocIR dense-embedding shards."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
import numpy as np
def main():
 p=argparse.ArgumentParser();p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--expected-views',type=int,required=True);a=p.parse_args()
 shards=[]
 for meta_path in sorted((a.model_dir/'shards').glob('*.json')):
  meta=json.loads(meta_path.read_text()); r=meta['range']; arr=a.model_dir/'shards'/f"{r['start']:06d}_{r['end']:06d}.npy"
  if not arr.exists():raise FileNotFoundError(arr)
  data=np.load(arr,mmap_mode='r')
  if len(data)!=r['end']-r['start'] or data.shape[1]!=meta['dimensions']:raise ValueError(f'invalid shard {arr}')
  shards.append((r['start'],r['end'],arr,meta))
 if not shards:raise ValueError('no shard metadata')
 cursor=0; dims=shards[0][3]['dimensions']
 for start,end,path,meta in shards:
  if start!=cursor or meta['dimensions']!=dims:raise ValueError(f'non-contiguous or incompatible shard at {path}')
  cursor=end
 if cursor!=a.expected_views:raise ValueError(f'coverage ends at {cursor}, expected {a.expected_views}')
 out=np.lib.format.open_memmap(a.model_dir/'view_vectors.npy',mode='w+',dtype=np.float32,shape=(a.expected_views,dims))
 for start,end,path,_ in shards:out[start:end]=np.load(path,mmap_mode='r')
 del out
 base=dict(shards[0][3]);base['range']={'start':0,'end':a.expected_views,'total_views':a.expected_views};base['merged_from_shards']=len(shards);base['merged_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
 (a.model_dir/'embedding_summary.json').write_text(json.dumps(base,indent=2,sort_keys=True)+'\n');print(json.dumps(base,sort_keys=True))
if __name__=='__main__':main()
