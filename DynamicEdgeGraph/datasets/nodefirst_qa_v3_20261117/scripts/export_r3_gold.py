#!/usr/bin/env python3
"""Export per-record automatic r3 Gold and complete r2→r3 diff."""
import json
from collections import Counter
from pathlib import Path
R3=Path(__file__).resolve().parents[1];R2=R3.parent/'nodefirst_qa_v2_20261117_r2'
def load(p): return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def save(p,rows): p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
def main():
 old={x['draft_id']:x for x in load(R2/'qa_gold_balanced_20_30_50_r2.jsonl')};new={x['draft_id']:x for x in load(R3/'qa_candidates_r3.jsonl')};reviews={x['draft_id']:x for x in load(R3/'qa_independent_reviews_r3_pass2.jsonl')};validation={x['draft_id']:x for x in load(R3/'deterministic_validation_r3.jsonl')};disp={x['draft_id']:x for x in load(R3/'pr4_disposition_r3.jsonl')}
 gold=[];diff=[]
 for did in sorted(old):
  n=new.get(did);v=validation[did]
  if v['status']=='GOLD_ELIGIBLE_AUTOMATIC':
   row=json.loads(json.dumps(n));row['gold_id']=row['r3_candidate_id'].replace('nodefirst_v2_r3::','nodefirst_v2_gold_r3::');row['independent_review']=reviews[did];row['final_gate']={'status':'FINAL_ACCEPT_AUTOMATIC','source_integrity':'PASS','canonical_mapping':'PASS','claim_grounding':'PASS','node_necessity':'PASS','single_node_shortcut':'PASS','manual_approval_required':False};gold.append(row)
  diff.append({'draft_id':did,'r2_gold_id':old[did].get('gold_id'),'r3_candidate_id':n.get('r3_candidate_id') if n else None,'r3_status':v['status'],'question_changed':bool(n and old[did]['question']!=n['question']),'answer_changed':bool(n and old[did]['gold_answer_draft']!=n['gold_answer_draft']),'claims_changed':bool(n and old[did]['answer_claims']!=n['answer_claims']),'old_question':old[did]['question'],'new_question':n.get('question') if n else None,'old_answer':old[did]['gold_answer_draft'],'new_answer':n.get('gold_answer_draft') if n else None,'blocking_reasons':v['blocking_reasons'],'disposition_reason':disp[did].get('reason')})
 save(R3/'qa_gold_auto_accepted_r3.jsonl',gold);save(R3/'r2_to_r3_diff.jsonl',diff)
 claim_base=load(R3/'claim_span_audit_r3.jsonl');verified=[]
 for row in claim_base:
  cr=next((x for x in reviews[row['draft_id']].get('claim_reviews',[]) if x.get('claim_id')==row['claim_id']),{})
  out=dict(row);out['semantic_entailment']='PASS' if cr.get('joint_entailment_pass') is True else 'FAIL';out['independent_claim_review']=cr;verified.append(out)
 save(R3/'claim_span_audit_verified_r3.jsonl',verified)
 counts=Counter(x['qa_category'] for x in gold);summary={'r2_audited_gold_count':len(old),'r3_candidate_count':len(new),'r3_gold_count':len(gold),'r3_gold_by_category':dict(counts),'excluded_or_blocked_count':len(old)-len(gold),'manual_approval_required':False}
 (R3/'gold_export_summary_r3.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
