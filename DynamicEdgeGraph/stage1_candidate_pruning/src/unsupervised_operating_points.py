"""Query-independent, label-free Stage-1 candidate operating-point analysis."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from .common import load_config,read_jsonl,repo_path,run_dir,write_jsonl

ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
def key(x): return tuple(sorted((str(x['source_id']),str(x['target_id']))))
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--baseline-run',required=True);p.add_argument('--top20-run',required=True);p.add_argument('--top50-run',required=True);p.add_argument('--budget-run',required=True);p.add_argument('--run-id',required=True);a=p.parse_args()
 c=load_config(a.config);c['run_id']=a.run_id;out=run_dir(c);out.mkdir(parents=True,exist_ok=True);base=repo_path(a.baseline_run)
 rows={r:list(read_jsonl(base/'route_candidates'/f'{r}.jsonl')) for r in ROUTES}
 bypair={}
 for r,rr in rows.items():
  for x in rr:
   k=key(x);bypair.setdefault(k,{}).setdefault(r,[]).append({'rank':x['rank'],'raw_score':x['raw_score'],'direction':x['direction']})
 score_bypair={k:dict(v) for k,v in bypair.items()}
 # HNSW searches at different K are independent approximate runs, so retain
 # provenance for pairs that appear at Top-20/50 but not in the Top-100 run.
 for source in (a.top20_run,a.top50_run):
  folder=repo_path(source)
  for r in ROUTES:
   for x in read_jsonl(folder/'route_candidates'/f'{r}.jsonl'):
    k=key(x);bypair.setdefault(k,{}).setdefault(r,[]).append({'rank':x['rank'],'raw_score':x['raw_score'],'direction':x['direction']})
 def union_from(path):
  result=set()
  for r in ROUTES:result|={key(x) for x in read_jsonl(repo_path(path)/'route_candidates'/f'{r}.jsonl')}
  return result
 rank20=union_from(a.top20_run);rank50=union_from(a.top50_run);rank100=set().union(*({key(x) for x in rows[r]} for r in ROUTES))
 budget=repo_path(a.budget_run)
 gates=json.loads((budget/'score_gate_thresholds.json').read_text())
 q=gates['quantile_thresholds']
 def scored(labels):
  return {k for k,rs in score_bypair.items() if any(any(float(x['raw_score'])>=q[labels[r]][r] for x in values) for r,values in rs.items())}
 q50,q75,q90=(scored({r:label for r in ROUTES}) for label in ('q50','q75','q90'))
 matched_labels=gates['budget_matched_gate_labels']; matched=scored(matched_labels)
 points={'rank_top20':rank20,'rank_top50':rank50,'rank_top100':rank100,'score_q50':q50,'score_q75':q75,'score_q90':q90,'score_budget_matched_to_rank20':matched}
 n=1313; possible=n*(n-1)//2;data=[]
 for name,s in points.items():
  degrees={x:0 for x in range(0)}
  covered={x for pair in s for x in pair}; multi=sum(len(bypair[k])>=2 for k in s)
  data.append({'operating_point':name,'candidate_pairs':len(s),'pruning_rate':1-len(s)/possible,'covered_retrieval_nodes':len(covered),'baseline_retrieval_nodes':1204,'isolated_canonical_nodes':n-len(covered),'multi_route_pairs':multi,'multi_route_fraction':multi/len(s) if s else 0,'vs_rank20_jaccard':len(s&rank20)/len(s|rank20) if s|rank20 else 1,'vs_score_q75_jaccard':len(s&q75)/len(s|q75) if s|q75 else 1,'threshold_or_rank_policy':json.dumps(matched_labels,sort_keys=True) if name=='score_budget_matched_to_rank20' else name})
 with (out/'operating_points.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 # Candidate outputs retain all route provenance; no semantic acceptance/type is inferred.
 for name,s in points.items():
  write_jsonl(out/'candidate_sets'/f'{name}.jsonl',({'source_id':k[0],'target_id':k[1],'candidate_status':'UNVERIFIED_STATIC_SEMANTIC_CANDIDATE','route_evidence':bypair[k],'operating_point':name} for k in sorted(s)))
 resource={}
 rp=base/'route_resources.json'
 if rp.exists():
  raw=json.loads(rp.read_text()).get('routes',{})
  resource={r:raw.get(r,{}) for r in ROUTES}
 (out/'resource_context.json').write_text(json.dumps({'source_run':str(base),'semantic_route_resources':resource,'note':'Costs are retrieval/index costs from the existing frozen-vector run; no new model training or query processing.'},indent=2,sort_keys=True))
 report=['# Stage 1 — Query-independent operating points','','This is a label-free static Node-pair pruning analysis. Candidate pairs are not verified edges, query relations, or query-conditioned evidence compositions. Structural edges are excluded.','','| Operating point | Pairs | Pruning | Coverage | Jaccard vs Rank-20 | Jaccard vs Score-q75 |','|---|---:|---:|---:|---:|---:|']
 for x in data:report.append(f"| {x['operating_point']} | {x['candidate_pairs']:,} | {x['pruning_rate']:.2%} | {x['covered_retrieval_nodes']} | {x['vs_rank20_jaccard']:.3f} | {x['vs_score_q75_jaccard']:.3f} |")
 report+=['','Suggested study points, not final thresholds: `rank_top20` is the rank-only low-budget baseline; `score_budget_matched_to_rank20` isolates score gating at the same budget; `score_q75` is a more aggressive score-gated point; and `rank_top50` supplies a higher-budget rank reference. Potential omission risk is not a measured semantic-recall claim without an external representative labelled sample.']
 (out/'reports').mkdir(exist_ok=True);(out/'reports'/'operating_points.md').write_text('\n'.join(report)+'\n')
 print(json.dumps({'output':str(out),'points':{k:len(v) for k,v in points.items()}}))
if __name__=='__main__':main()
