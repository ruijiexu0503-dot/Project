#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OLD=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117'
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1'
def load(p):
 with p.open(encoding='utf8') as f:return [json.loads(x) for x in f if x.strip()]
def save(p,rows):p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
def main():
 candidates=load(OUT/'qa_candidates_r1.jsonl'); reviews={x['draft_id']:x for x in load(OUT/'qa_independent_reviews_r1.jsonl')}
 mappings={(x['draft_id'],x['evidence_unit_id']):x for x in load(OUT/'canonical_mapping_r1.jsonl')}
 source_by_node={x['canonical_node_id']:x for x in load(OUT/'source_integrity_audit.jsonl')}
 dedup={x['draft_id']:x for x in load(OUT/'duplicate_audit_r1.jsonl')}
 decisions=[]; accepted=[]
 for d in candidates:
  rid=d['draft_id']; r=reviews[rid]; ev=d['gold_evidence_draft']
  category_ok=(d['qa_category']=='single_node' and len(ev)==1) or (d['qa_category']=='cross_page' and len({x['document_id'] for x in ev})==1 and len({x['page_id'] for x in ev})>=2) or (d['qa_category']=='cross_document' and len({x['document_id'] for x in ev})>=2)
  mapping_ok=all(mappings[(rid,x['evidence_unit_id'])]['mapping_status']=='MAPPED_VERIFIED_AUTOMATIC' for x in ev)
  source_ok=all(source_by_node[x['canonical_node_id']]['source_integrity_status']=='SOURCE_INTEGRITY_PASS' for x in ev)
  semantic_ok=all(bool(r.get(k)) for k in ['model_review_pass','question_validity','answer_correctness','evidence_sufficiency','each_gold_node_required','duplicate_pass'])
  shortcut_ok=not r.get('single_node_shortcut_found',False)
  duplicate_ok=dedup[rid]['deterministic_duplicate_gate']=='PASS'
  reasons=[]
  for ok,name in [(category_ok,'CATEGORY_CONSTRAINT'),(mapping_ok,'CANONICAL_MAPPING'),(source_ok,'SOURCE_INTEGRITY'),(semantic_ok,'SEMANTIC_GROUNDING'),(shortcut_ok,'SINGLE_NODE_SHORTCUT'),(duplicate_ok,'DETERMINISTIC_DUPLICATE')]:
   if not ok: reasons.append(name)
  status='FINAL_ACCEPT_AUTOMATIC' if not reasons else 'REJECT_OR_REVISE'
  gate={'draft_id':rid,'parent_draft_id':d.get('parent_draft_id'),'qa_category':d['qa_category'],'status':status,'checks':{'category_constraint':category_ok,'canonical_mapping':mapping_ok,'source_integrity':source_ok,'independent_model_semantic_review':semantic_ok,'no_single_node_shortcut':shortcut_ok,'deterministic_duplicate':duplicate_ok},'blocking_reasons':reasons,'review_notes':r.get('review_notes')}
  decisions.append(gate)
  if status=='FINAL_ACCEPT_AUTOMATIC':
   x=json.loads(json.dumps(d));x['review']=r;x['final_gate']=gate;accepted.append(x)
 save(OUT/'final_gate_decisions_r1.jsonl',decisions);save(OUT/'qa_gold_auto_accepted_pool_r1.jsonl',accepted)
 by={k:sorted([x for x in accepted if x['qa_category']==k],key=lambda x:x['draft_id']) for k in ['single_node','cross_page','cross_document']}
 release_n=10*min(len(by['single_node'])//2,len(by['cross_page'])//3,len(by['cross_document'])//5)
 quota={'single_node':release_n//5,'cross_page':release_n*3//10,'cross_document':release_n//2}
 balanced=[]
 for k in ['single_node','cross_page','cross_document']:balanced.extend(by[k][:quota[k]])
 balanced.sort(key=lambda x:x['draft_id']);save(OUT/'qa_gold_balanced_export_r1.jsonl',balanced)
 old_reviews=load(OLD/'qa_independent_reviews.jsonl'); old_pass=sum(x['status'] in {'CONTENT_PASS_MAPPING_PENDING','PILOT_ONLY_BLOCKED_CONTENT_PASS'} for x in old_reviews)
 summary={'input_pilot':50,'r1_candidates':len(candidates),'automatic_final_accept':len(accepted),'automatic_accept_rate_over_original_pilot':len(accepted)/50,'automatic_accept_rate_over_r1_candidates':len(accepted)/len(candidates),'accepted_by_category':dict(Counter(x['qa_category'] for x in accepted)),'balanced_export_count':len(balanced),'balanced_export_by_category':dict(Counter(x['qa_category'] for x in balanced)),'old_content_pass_but_blocked':old_pass,'old_final_accept':0,'r1_reject_or_revise':len(decisions)-len(accepted),'gate_block_counts':dict(Counter(y for x in decisions for y in x['blocking_reasons']))}
 (OUT/'auto_gold_export_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':main()
