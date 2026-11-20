#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OLD=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117'
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1'
HIST=ROOT/'DynamicEdgeGraph/datasets/all_qa_review_drafts_v1/all_qa_drafts.jsonl'
def load(p):
 with p.open(encoding='utf8') as f:return [json.loads(x) for x in f if x.strip()]
def save(p,rows):p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
def norm(s):return ' '.join(re.findall(r'[a-z0-9]+',s.lower()))
def toks(s):return set(norm(s).split())
def jac(a,b):
 a,b=toks(a),toks(b)
 return len(a&b)/len(a|b) if a|b else 1.0
def main():
 old=load(OLD/'qa_drafts.jsonl'); repaired=load(OUT/'qa_crossdoc_repaired_candidates.jsonl')
 auto_map={x['evidence_unit_id']:x for x in load(OUT/'automatic_evidence_unit_mapping.jsonl')}
 real_pool={x['canonical_node_id']:x for x in load(OUT/'real_canonical_nodes_pilot_r1.jsonl')}
 # Keep original single/cross-page records; use only necessity-valid cross-document candidates.
 candidates=[json.loads(json.dumps(x)) for x in old[:25]]+repaired
 mapping=[]
 for d in candidates:
  d['corpus_snapshot']='nodefirst_qa_v2_20261117_r1'
  d['parent_draft_id']=d.get('parent_draft_id',d['draft_id'])
  oldnum=int(d['parent_draft_id'].split('::')[-1]); d['draft_id']=f'nodefirst_v2_r1::{oldnum:03d}'
  for e in d['gold_evidence_draft']:
   if e['canonical_node_id'] is None:
    source=Path(e['source_json']); m=auto_map[e['evidence_unit_id']]; cid=m['canonical_node_id']; node=real_pool[cid]
    page_dir=source.parents[1]; images=sorted((page_dir/'layout_visualization').glob('*_layout.png'))
    e['canonical_node_id']=cid;e['node_mapping_status']='AUTO_MAPPED_EXACT_SOURCE_ELEMENT';e['page_image']=str(images[0]) if images else None
    mapping.append({'draft_id':d['draft_id'],'evidence_unit_id':e['evidence_unit_id'],'canonical_node_id':cid,'mapping_status':m['mapping_status'],'method':node['mapping_method']})
   else:
    e['node_mapping_status']='MAPPED_VERIFIED_AUTOMATIC'
    mapping.append({'draft_id':d['draft_id'],'evidence_unit_id':e['evidence_unit_id'],'canonical_node_id':e['canonical_node_id'],'mapping_status':'MAPPED_VERIFIED_AUTOMATIC','method':'FROZEN_LEGACY_NODE_EXACT_ID'})
  d['seed']['canonical_node_id']=d['gold_evidence_draft'][0]['canonical_node_id']
  d['review']={'status':'PENDING_INDEPENDENT_MODEL_REVIEW_R1'}
 hist=load(HIST); hq=[(x.get('draft_id'),x.get('question','')) for x in hist if x.get('question')]
 dedup=[]
 for d in candidates:
  scores=sorted(((jac(d['question'],q),i,q) for i,q in hq),reverse=True)
  best=scores[0] if scores else (0,None,None)
  dedup.append({'draft_id':d['draft_id'],'normalized_exact_duplicate':any(norm(d['question'])==norm(q) for _,q in hq),'max_token_jaccard':round(best[0],4),'nearest_historical_draft_id':best[1],'nearest_historical_question':best[2],'deterministic_duplicate_gate':'BLOCK' if any(norm(d['question'])==norm(q) for _,q in hq) else 'PASS'})
 save(OUT/'canonical_mapping_r1.jsonl',mapping);save(OUT/'qa_candidates_r1.jsonl',candidates);save(OUT/'duplicate_audit_r1.jsonl',dedup)
 summary={'candidate_count':len(candidates),'category_counts':{k:sum(x['qa_category']==k for x in candidates) for k in ['single_node','cross_page','cross_document']},'new_canonical_nodes':len(real_pool),'mapping_pass':sum(x['mapping_status']=='MAPPED_VERIFIED_AUTOMATIC' for x in mapping),'mapping_total':len(mapping),'exact_duplicate_blocks':sum(x['deterministic_duplicate_gate']=='BLOCK' for x in dedup),'rejected_cross_document_parent_ids':[f'nodefirst_v2_pilot::{n:03d}' for n in [33,35,37,40,42,46,47,48,49]]}
 (OUT/'r1_candidate_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':main()
