import argparse,json
from pathlib import Path
from evidence_graph.llm_client import TransformersLLM
Q='4ba09a15-c394-4b0c-b9c4-3307beec5a61'; ROOT=Path('DynamicEdgeGraph/stage2_edge_construction/outputs/edge_utility_slot_v1_20261112_r2')
BASE=Path('EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011')
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);a.add_argument('--model',required=True);x=a.parse_args();out=Path(x.out);out.mkdir(parents=True,exist_ok=True)
 reps=[json.loads(s) for s in (ROOT/'page_representatives.jsonl').read_text().splitlines() if json.loads(s)['question_id']==Q]
 views={r['node_id']:r for r in map(json.loads,(Path('DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/retrieval_views.jsonl')).open())}
 cand=[]
 for r in reps:
  if r['route_kind']=='graph_representative':
   v=views[r['target_node_id']]
   cand.append({'page':r['page'],'node':r['target_node_id'],'content':str(v['retrieval_text'])[:500]})
 d=[r for r in reps if r['route_kind']=='dense_replacement_representative'][0]
 v=views[d['target_node_id']]
 # Deliberately do not expose the dense/graph route to the reader: route labels
 # would let it select a candidate without reading its evidence.
 cand.append({'page':d['page'],'node':d['target_node_id'],'content':str(v['retrieval_text'])[:500]})
 common=(
  'Question: What is the maximum intrinsic outflow velocity measured in the warm H2 gas of NGC 3256, '
  'and how does it compare to the central value of the best H0 measurement from the SN H0pe study?\n'
  'Candidates below are the only evidence. Each has the same 500-character content budget. '\
  'Do not use candidate order, route, or outside knowledge.\n'+json.dumps(cand)+'\n'
  'Return JSON only: {"action":"KEEP_DENSE|SELECT_PAGE","page":[document_id,page_number],'
  '"node_id":"...","quoted_support":"an exact substring from content","reason":"..."}. '
  'SELECT_PAGE requires a nonempty exact quote that supports the requested missing evidence; otherwise KEEP_DENSE. '
  'Do not infer unsupported numbers.'
 )
 prompts={'query_only':common,'evidence_state':common+'\nAlready-read evidence supports the NGC 3256 maximum intrinsic outflow velocity. Select only a page that adds support for the SN H0pe best H0 central value; otherwise KEEP_DENSE.'}
 (out/'packet.json').write_text(json.dumps({'query_id':Q,'candidates':cand,'prompts':prompts},indent=2))
 llm=TransformersLLM(x.model,dtype='bfloat16',max_new_tokens=400,require_cuda=True,enable_thinking=False)
 result={k:{'parsed':g.parsed,'raw':g.raw,'model':g.model} for k,p in prompts.items() for g in [llm.generate_json('You are a careful evidence selector. Use only candidate text.',p)]}
 (out/'results.json').write_text(json.dumps(result,indent=2));print(out)
if __name__=='__main__':main()
