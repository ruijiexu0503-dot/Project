"""Sample a fixed Stage-1 Pilot Top-100 union without Query or label access."""
from __future__ import annotations
import argparse, random
from common import load_config, read_jsonl, repo_path, run_dir, stable_pair_id, write_json, write_jsonl

def canonical(a,b): return tuple(sorted((a,b)))
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();c=load_config(a.config);out=run_dir(c);out.mkdir(parents=True,exist_ok=True)
 union=repo_path(c['candidate_union_path']); routes=repo_path(c['route_candidates_root']); views=repo_path('DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/retrieval_views.jsonl')
 node={r['node_id']:r for r in read_jsonl(views)}; reservoir=[]; limit=int(c['max_pairs']); rng=random.Random(int(c['seed']))
 total=0
 for row in read_jsonl(union):
  key=canonical(row['source_id'],row['target_id'])
  if key[0] not in node or key[1] not in node:raise ValueError('union endpoint missing from retrieval views')
  total+=1
  if len(reservoir)<limit:reservoir.append(key)
  else:
   pos=rng.randrange(total)
   if pos<limit:reservoir[pos]=key
 selected=set(reservoir); observations={key:[] for key in selected}
 for path in sorted(routes.glob('*.jsonl')):
  for row in read_jsonl(path):
   key=canonical(row['source_id'],row['target_id'])
   if key in observations: observations[key].append({'route':row['route'],'retrieved_from':row['source_id'],'rank':row['rank'],'raw_score':row['raw_score'],'direction':row['direction']})
 pairs=[]
 for left,right in sorted(selected):
  x,y=node[left],node[right];pair_id=stable_pair_id(left,right,c['node_id_namespace']);obs=observations[(left,right)]
  pairs.append({'pair_id':pair_id,'source_node_id':left,'target_node_id':right,'source_document_id':x['document_id'],'target_document_id':y['document_id'],'source_page':x['page_number'],'target_page':y['page_number'],'source_modality':x['node_type'],'target_modality':y['node_type'],'candidate_origin':['pilot_stage1_top100_candidate'],'candidate_policy':'five_route_top100_OR_union_then_reservoir_sample','node_id_namespace':c['node_id_namespace'],'dataset_id':c['dataset_id'],'dataset_revision':c['dataset_revision'],'stage1_policy':None,'route_support':len({r['route'] for r in obs}),'route_observations':obs,'normalized_reference_version':None,'abc_flags':None,'review_status':'UNREVIEWED'})
 write_jsonl(out/'pairs.jsonl',pairs);write_json(out/'pair_manifest.json',{'stage1_union_pairs':total,'sampled_pairs':len(pairs),'seed':c['seed'],'candidate_origin':'pilot_stage1_top100_candidate','routes_scanned':sorted(p.name for p in routes.glob('*.jsonl')),'strict_balanced_abc_transfer':False,'why_not_strict_abc':'Pilot Top-100 routes do not carry full Balanced-v1 ECDF reference/cross-score contract.','query_used':False,'gold_labels_used':False});print(len(pairs))
if __name__=='__main__':main()
