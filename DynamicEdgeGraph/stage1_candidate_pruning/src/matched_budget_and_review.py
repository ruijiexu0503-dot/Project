"""Matched-budget pruning analysis and an UNREVIEWED stratified pair panel."""
from __future__ import annotations
import argparse,csv,itertools,json,random
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from .common import load_config,read_jsonl,repo_path,run_dir,write_jsonl

ROUTES=['qwen3_0_6b_dense','gte_qwen2_1_5b_dense','bge_en_icl_dense','mxbai_dense','gte_large_dense','bm25']
DENSE=set(ROUTES)-{'bm25'}
def key(r): return tuple(sorted((str(r['source_id']),str(r['target_id']))))
def pairs(path):
    rows=list(read_jsonl(path)); return rows,{key(x) for x in rows}
def metadata(config):
    p=repo_path('EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/corpus_nodes.jsonl'); out={}
    for x in read_jsonl(p): out[str(x['id'])]={'doc':str(x.get('document')),'modality':str(x.get('unit_type')),'text':str(x.get('text',''))}
    return out
def reviewed(path, universe):
    out={}
    for x in read_jsonl(path):
        a=x.get('A',{}).get('node_id');b=x.get('B',{}).get('node_id')
        if a and b and str(a) in universe and str(b) in universe: out[tuple(sorted((str(a),str(b))))]=x
    return out
def qgate(rows,q): return float(np.quantile([float(r['raw_score']) for r in rows],q))
def summarize(name,selected,positive,universe):
    n=len(universe); possible=n*(n-1)//2
    return {'strategy':name,'candidate_pairs':len(selected),'pruning_rate':1-len(selected)/possible,
      'reviewed_positive_denominator':len(positive),'reviewed_positive_hits':len(selected&positive),
      'observed_verified_positive_recall':len(selected&positive)/len(positive) if positive else None}
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--baseline-run',required=True);p.add_argument('--top20-run',required=True);p.add_argument('--reviewed',default='EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/evaluation/cases.jsonl');p.add_argument('--run-id',required=True);a=p.parse_args()
 c=load_config(a.config); c['run_id']=a.run_id; out=run_dir(c);out.mkdir(parents=True,exist_ok=True); base=repo_path(a.baseline_run); top20=repo_path(a.top20_run)
 meta=metadata(c); universe=set(meta); rev=reviewed(repo_path(a.reviewed),universe); pos={k for k,v in rev.items() if v.get('label')=='POSITIVE'}
 full_rows={};full_sets={};top20_sets={}
 for r in ROUTES:
  full_rows[r],full_sets[r]=pairs(base/'route_candidates'/f'{r}.jsonl');_,top20_sets[r]=pairs(top20/'route_candidates'/f'{r}.jsonl')
 rank20=set().union(*top20_sets.values()); rank100=set().union(*full_sets.values())
 gates={label:{r:qgate(full_rows[r],q) for r in ROUTES} for label,q in [('q50',.5),('q75',.75),('q90',.9)]}
 score_sets={label:set().union(*({key(x) for x in full_rows[r] if float(x['raw_score'])>=gates[label][r]} for r in ROUTES)) for label in gates}
 rows=[summarize('rank_top20',rank20,pos,universe),summarize('rank_top100',rank100,pos,universe)]
 rows += [summarize('score_top100_'+x,score_sets[x],pos,universe) for x in gates]
 # Search independent per-route q50/q75/q90 combinations nearest rank-20 budget.
 choices=['q50','q75','q90']; matched=[]
 for combo in itertools.product(choices,repeat=len(ROUTES)):
  selected=set()
  for r,label in zip(ROUTES,combo): selected|={key(x) for x in full_rows[r] if float(x['raw_score'])>=gates[label][r]}
  matched.append((abs(len(selected)-len(rank20)),combo,selected))
 _,combo,budget_matched=min(matched,key=lambda x:(x[0],x[1])); rows.append(summarize('score_top100_budget_matched_to_rank20',budget_matched,pos,universe)|{'route_gates':json.dumps(dict(zip(ROUTES,combo)),sort_keys=True)})
 fields=sorted({k for x in rows for k in x});
 with (out/'matched_budget_metrics.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 (out/'score_gate_thresholds.json').write_text(json.dumps({'quantile_thresholds':gates,'budget_matched_gate_labels':dict(zip(ROUTES,combo))},indent=2,sort_keys=True))
 # Route ablation only against existing reviewed positives; does not claim corpus recall.
 ablation={}
 for r in ROUTES:
  remaining=set().union(*(full_sets[x] for x in ROUTES if x!=r));ablation[r]={'pairs_lost_from_full_union':len(rank100-remaining),'reviewed_positive_lost':len((rank100-remaining)&pos),'reviewed_positive_recall_without_route':len(remaining&pos)/len(pos) if pos else None}
 (out/'leave_one_route_out_reviewed.json').write_text(json.dumps(ablation,indent=2,sort_keys=True))
 # Transparent, deterministic UNREVIEWED panel. Every record carries its stratum size/probability.
 per=defaultdict(dict)
 for r in ROUTES:
  for x in full_rows[r]:
   k=key(x); old=per[k].get(r); per[k][r]=x if old is None or int(x['rank'])<int(old['rank']) else old
 def cross(k): return meta[k[0]]['doc']!=meta[k[1]]['doc']
 def crossmod(k): return meta[k[0]]['modality']!=meta[k[1]]['modality']
 allset=rank100; rng=random.Random(20261107); strata=defaultdict(list)
 for k in allset:
  rr=set(per[k]); dense=rr&DENSE
  if len(dense)>=2:strata['multi_dense'].append(k)
  if rr=={'bm25'}:strata['bm25_only'].append(k)
  if rr=={'bge_en_icl_dense'}:strata['bge_only'].append(k)
  if len(rr)==1 and next(iter(rr)) not in {'bm25','bge_en_icl_dense'}:strata['other_route_only'].append(k)
  if k not in rank20:strata['top100_not_top20'].append(k)
  if cross(k):strata['cross_document'].append(k)
  if crossmod(k):strata['cross_modal'].append(k)
  dense_scores=[float(x['raw_score']) for r,x in per[k].items() if r in DENSE]
  if dense_scores and max(dense_scores)<.55:strata['low_dense_score'].append(k)
 # bounded random pairs absent from every route: explicit non-retrieval sample, not a negative label.
 ids=sorted(universe); missed=[]
 while len(missed)<20:
  k=tuple(sorted(rng.sample(ids,2)))
  if k not in allset and k not in missed: missed.append(k)
 strata['unretrieved_random']=missed
 panel=[];seen=set()
 for name,items in sorted(strata.items()):
  items=sorted(set(items)); sample=items if name=='unretrieved_random' else rng.sample(items,min(12,len(items)))
  for k in sample:
   if k in seen:continue
   seen.add(k); panel.append({'pair_id':'|'.join(k),'source_id':k[0],'target_id':k[1],'sampling_stratum':name,'stratum_population':len(items),'inclusion_probability':len(sample)/len(items),'review_status':'UNREVIEWED','human_label':None,'model_prediction_is_not_gold':True,'cross_document':cross(k),'cross_modal':crossmod(k),'routes':{r:{'rank':x['rank'],'raw_score':x['raw_score']} for r,x in per.get(k,{}).items()},'source_text':meta[k[0]]['text'][:1200],'target_text':meta[k[1]]['text'][:1200]})
 write_jsonl(out/'review_panel_unreviewed.jsonl',panel)
 (out/'reviewed_label_audit.json').write_text(json.dumps({'existing_records_in_current_universe':len(rev),'positive':len(pos),'negative':sum(x.get('label')=='NEGATIVE' for x in rev.values()),'other_or_unknown':len(rev)-len(pos)-sum(x.get('label')=='NEGATIVE' for x in rev.values()),'limitation':'Purpose-limited existing labels are reported as observed reviewed-positive recall only; the new panel is UNREVIEWED.'},indent=2))
 (out/'reports'/'matched_budget.md').parent.mkdir(parents=True,exist_ok=True)
 (out/'reports'/'matched_budget.md').write_text('# Matched-budget rank vs score pruning\n\nExisting reviewed labels are purpose-limited, not corpus-wide truth. New panel records are explicitly UNREVIEWED. See `matched_budget_metrics.csv`, `score_gate_thresholds.json`, `leave_one_route_out_reviewed.json`, and `review_panel_unreviewed.jsonl`.\n')
 print(json.dumps({'output':str(out),'rank20':len(rank20),'budget_matched_score':len(budget_matched),'reviewed_positive':len(pos),'unreviewed_panel':len(panel)}))
if __name__=='__main__':main()
