"""Embed retriever-visible queries only; does not read qrels or answers."""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--model',type=Path,default=Path('EvidenceNet/models/Qwen3-Embedding-0.6B'));p.add_argument('--batch-size',type=int,default=16);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 import torch
 from transformers import AutoModel,AutoTokenizer
 qs=[]
 for split in ('train','dev','test'):
  qs += [{**x,'split':split} for x in map(json.loads,(a.data/f'queries_{split}.jsonl').open())]
 qs.sort(key=lambda x:x['query_id']); tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,padding_side='left');model=AutoModel.from_pretrained(a.model,local_files_only=True,torch_dtype=torch.bfloat16).cuda().eval()
 texts=['Instruct: Retrieve document pages containing evidence to answer the question.\nQuery: '+x['query'] for x in qs];result=[]
 with torch.inference_mode():
  for start in range(0,len(texts),a.batch_size):
   batch=tok(texts[start:start+a.batch_size],padding=True,truncation=True,max_length=512,return_tensors='pt').to('cuda');result.append(torch.nn.functional.normalize(model(**batch).last_hidden_state[:,-1].float(),p=2,dim=-1).cpu().numpy())
 values=np.concatenate(result).astype(np.float32);np.save(a.out/'query_vectors.npy',values)
 with (a.out/'query_ids.jsonl').open('w') as f:
  for i,x in enumerate(qs):f.write(json.dumps({'embedding_row':i,'query_id':x['query_id'],'split':x['split']},sort_keys=True)+'\n')
 (a.out/'manifest.json').write_text(json.dumps({'encoder':'Qwen3-Embedding-0.6B','queries':len(qs),'shape':list(values.shape),'input':'retriever-visible question only; no answer/qrel','splits':{s:sum(x['split']==s for x in qs) for s in ('train','dev','test')}},indent=2));print(a.out)
if __name__=='__main__':main()
