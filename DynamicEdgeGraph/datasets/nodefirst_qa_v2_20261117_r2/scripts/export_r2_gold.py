#!/usr/bin/env python3
"""Export independently reviewed r2 Gold without mutating Pilot or r1."""
import json
from collections import Counter
from pathlib import Path

R2=Path(__file__).resolve().parents[1]
R1=R2.parent/'nodefirst_qa_v2_20261117_r1'
def load(name):
 p=name if isinstance(name,Path) else R2/name
 return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def save(name,rows):
 (R2/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
def main():
 candidates={x['draft_id']:x for x in load('qa_candidates_r2.jsonl')}
 reviews={x['draft_id']:x for x in load('qa_independent_reviews_r2.jsonl')}
 validation=load('deterministic_validation_r2.jsonl')
 r1={x['draft_id']:x for x in load(R1/'qa_gold_auto_accepted_pool_r1.jsonl')}
 eligible_ids=[x['draft_id'] for x in validation if x['status']=='GOLD_ELIGIBLE_AUTOMATIC']
 pool=[]
 for draft_id in eligible_ids:
  row=json.loads(json.dumps(candidates[draft_id]))
  row['gold_id']=row['r2_candidate_id'].replace('nodefirst_v2_r2::','nodefirst_v2_gold_r2::')
  row['independent_review']=reviews[draft_id]
  row['final_gate']={'status':'FINAL_ACCEPT_AUTOMATIC','source_integrity':'PASS','canonical_mapping':'PASS','semantic_review':'PASS','manual_approval_required':False}
  pool.append(row)
 save('qa_gold_auto_accepted_pool_r2.jsonl',pool)
 by={c:[] for c in ('single_node','cross_page','cross_document')}
 for row in pool:by[row['qa_category']].append(row)
 units=min(len(by['single_node'])//2,len(by['cross_page'])//3,len(by['cross_document'])//5)
 balanced=by['single_node'][:2*units]+by['cross_page'][:3*units]+by['cross_document'][:5*units]
 balanced.sort(key=lambda x:x['draft_id'])
 save('qa_gold_balanced_20_30_50_r2.jsonl',balanced)
 disposition={x['draft_id']:x for x in load('pr3_disposition_r2.jsonl')}
 validation_by={x['draft_id']:x for x in validation}
 diffs=[]
 for draft_id in sorted(disposition):
  old=r1.get(draft_id);new=candidates.get(draft_id);v=validation_by[draft_id]
  diffs.append({'draft_id':draft_id,'pr3_verdict':v['pr3_audit_verdict'],'r2_status':v['status'],'r2_candidate_id':new.get('r2_candidate_id') if new else None,'question_changed':bool(new and old and new['question']!=old['question']),'answer_changed':bool(new and old and new['gold_answer_draft']!=old['gold_answer_draft']),'old_question':old.get('question') if old else None,'new_question':new.get('question') if new else None,'old_answer':old.get('gold_answer_draft') if old else None,'new_answer':new.get('gold_answer_draft') if new else None,'blocking_reasons':v['blocking_reasons']})
 save('r1_to_r2_diff.jsonl',diffs)
 counts=Counter(x['qa_category'] for x in pool);bcounts=Counter(x['qa_category'] for x in balanced)
 summary={'r1_pr3_audited_count':len(disposition),'r2_candidate_count':len(candidates),'r2_gold_eligible_count':len(pool),'r2_gold_by_category':dict(counts),'balanced_gold_count':len(balanced),'balanced_gold_by_category':dict(bcounts),'balanced_distribution_exact':bool(balanced) and bcounts=={'single_node':len(balanced)*2//10,'cross_page':len(balanced)*3//10,'cross_document':len(balanced)*5//10},'manual_approval_required':False}
 (R2/'gold_export_summary_r2.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
