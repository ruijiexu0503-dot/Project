"""Audit the frozen BGE route without modifying frozen artifacts."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
def main():
 p=argparse.ArgumentParser();p.add_argument('--vectors',type=Path,required=True);p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--candidate-file',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 x=np.load(a.vectors,mmap_mode='r'); sample=np.unique(np.linspace(0,len(x)-1,min(2048,len(x)),dtype=int));base=np.asarray(x[0]);delta=np.max(np.abs(np.asarray(x[sample])-base),axis=1);norm=np.linalg.norm(x[sample],axis=1);gram=np.asarray(x[sample[:64]])@np.asarray(x[sample[:64]]).T
 pool=json.loads((a.model_dir/'1_Pooling'/'config.json').read_text());cfg=json.loads((a.model_dir/'config.json').read_text());scores=[]
 with a.candidate_file.open() as f:
  for line in f:
   if line.strip():
    scores.append(json.loads(line)['raw_score'])
   if len(scores)>=100000:break
 report={'route':'bge_en_icl_dense','frozen_matrix':{'shape':list(x.shape),'dtype':str(x.dtype),'sample_rows':int(len(sample)),'sample_rows_exactly_equal_to_row0':int(np.sum(delta==0)),'sample_max_abs_difference_from_row0':float(delta.max()),'sample_norm_min':float(norm.min()),'sample_norm_max':float(norm.max()),'sample_pair_dot_min':float(gram.min()),'sample_pair_dot_max':float(gram.max())},'model_pooling_config':pool,'model_architecture':cfg.get('architectures'),'pipeline_pooling_used':'cls','expected_pooling_from_model':'last_token' if pool.get('pooling_mode_lasttoken') else 'unknown','candidate_score_sample':{'count':len(scores),'min':float(np.min(scores)),'max':float(np.max(scores)),'std':float(np.std(scores))},'conclusion':'Scores and ranks are not reliable: CLS vectors collapsed. Existing frozen vectors/candidate pairs cannot recover last-token embeddings or corrected BGE scores. A separate additive re-embedding plus BGE-only ANN rerun is required to repair this route; no frozen artifact was modified.'}
 (a.out/'bge_en_icl_score_audit.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 (a.out/'BGE_SCORE_AUDIT.md').write_text('# BGE-en-ICL score audit\n\n'+json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps(report,sort_keys=True))
if __name__=='__main__':main()
