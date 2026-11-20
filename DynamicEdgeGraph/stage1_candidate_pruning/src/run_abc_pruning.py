"""Evaluate A OR B OR C pruning on GPU cross-scored bounded candidates."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import numpy as np
from .common import read_jsonl
R=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','mxbai_dense','gte_large_dense']
def write(p,rows):
 rows=list(rows);p.parent.mkdir(parents=True,exist_ok=True)
 if rows:
  with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
class D:
 def __init__(self,n):self.p=np.arange(n);self.s=np.ones(n,dtype=np.int32)
 def f(self,x):
  while self.p[x]!=x:self.p[x]=self.p[self.p[x]];x=self.p[x]
  return x
 def u(self,a,b):
  a=self.f(a);b=self.f(b)
  if a!=b:
   if self.s[a]<self.s[b]:a,b=b,a
   self.p[b]=a;self.s[a]+=self.s[b]
def main():
 p=argparse.ArgumentParser();p.add_argument('--cross',type=Path,required=True);p.add_argument('--run',type=Path,required=True);p.add_argument('--views',type=Path,required=True);p.add_argument('--nodes',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);cfg=json.loads(a.config.read_text())
 pairs=np.load(a.cross/'effective_union_pairs.npy',mmap_mode='r');score=np.load(a.cross/'dense_cross_scores.npy',mmap_mode='r');ev=np.load(a.cross/'effective_union_evidence.npy',mmap_mode='r');n=len(pairs)
 q={}
 for r in R+['bm25']:
  x=np.fromiter((float(z['raw_score']) for z in read_jsonl(a.run/'route_candidates'/'top100'/f'{r}.jsonl')),dtype=np.float32);q[r]={str(v):float(np.quantile(x,v)) for v in (.8,.9,.95,.99,.995,.999)}
 A=ev['support']==5; b_masks={}
 for b in cfg['rule_B_grid']:
  t=np.array([q[r][str(float(b['tail_percentile']))] for r in R],dtype=np.float32);b_masks[b['id']]=np.count_nonzero(score>=t,axis=1)>=b['dense_models_at_or_above']
 c_masks={}
 for c in cfg['rule_C_grid']:
  t=np.array([q[r][str(float(c['dense_tail_percentile']))] for r in R],dtype=np.float32);dense=np.any(score>=t,axis=1);lex=ev['bm25_present'].astype(bool)&(ev['bm25_score']>=q['bm25'][str(float(c['bm25_tail_percentile']))]);c_masks[c['id']]=dense|lex
 views=[x['node_id'] for x in read_jsonl(a.views)];meta={x['id']:(x.get('document_id',''),x.get('node_type','unknown'),x.get('data_source','unknown')) for x in read_jsonl(a.nodes)};types=np.array([meta[x][1] for x in views],dtype=object);sources=np.array([meta[x][2] for x in views],dtype=object);docs=np.array([meta[x][0] for x in views],dtype=object);summary=[]
 for comb in cfg['final_combinations']:
  B=b_masks[comb['B']];C=c_masks[comb['C']];keep=A|B|C;idx=np.flatnonzero(keep);left=(pairs[idx]>>np.uint64(32)).astype(np.int64);right=(pairs[idx]&np.uint64(0xffffffff)).astype(np.int64);deg=np.bincount(np.r_[left,right],minlength=len(views));active=np.flatnonzero(deg);d=D(len(views))
  for x,y in zip(left,right):d.u(int(x),int(y))
  roots={d.f(int(x)) for x in active};largest=max((d.s[x] for x in roots),default=0);dv=deg[active]
  out=a.out/'policies'/comb['id'];out.mkdir(parents=True,exist_ok=True);np.save(out/'selected_indices.npy',idx);np.save(out/'rule_hits.npy',np.stack((A[idx],B[idx],C[idx]),axis=1))
  # Scores remain in the shared cross-score matrix; indices maintain one-to-one provenance.
  crossdoc=int(np.count_nonzero(docs[left]!=docs[right]));crossmod=int(np.count_nonzero(types[left]!=types[right]));typecov=[]
  for t in sorted(set(types)):
   alln=int(np.count_nonzero(types==t));cov=int(np.count_nonzero((deg>0)&(types==t)));typecov.append({'node_type':t,'nodes':alln,'covered':cov,'coverage':cov/alln})
  write(out/'node_type_coverage.csv',typecov);write(out/'rule_intersections.csv',[{'A':int(np.count_nonzero(A)),'B':int(np.count_nonzero(B)),'C':int(np.count_nonzero(C)),'A_only':int(np.count_nonzero(A&~B&~C)),'B_only':int(np.count_nonzero(B&~A&~C)),'C_only':int(np.count_nonzero(C&~A&~B)),'ABC_union':len(idx)}])
  summary.append({'policy':comb['id'],'edges':len(idx),'A_count':int(np.count_nonzero(A)),'B_count':int(np.count_nonzero(B)),'C_count':int(np.count_nonzero(C)),'A_only':int(np.count_nonzero(A&~B&~C)),'B_only':int(np.count_nonzero(B&~A&~C)),'C_only':int(np.count_nonzero(C&~A&~B)),'covered_eligible_nodes':len(active),'isolated_eligible_nodes':len(views)-len(active),'mean_degree':2*len(idx)/len(views),'degree_p50':float(np.quantile(dv,.5)),'degree_p90':float(np.quantile(dv,.9)),'degree_p99':float(np.quantile(dv,.99)),'degree_max':int(deg.max()),'components':len(roots),'largest_component_nodes':int(largest),'cross_document_rate':crossdoc/len(idx),'cross_modal_rate':crossmod/len(idx)})
 write(a.out/'abc_policy_summary.csv',summary);(a.out/'REPORT.md').write_text('# ABC pruning results\n\n'+json.dumps({'cross_score_input':str(a.cross),'pairs':n,'BGE':'diagnostic_only','score_quantiles':q},indent=2)+'\n');print(json.dumps({'out':str(a.out),'policies':len(summary)}))
if __name__=='__main__':main()
