#!/usr/bin/env python3
"""Deterministic automatic gates for the PR #4 r3 repair set."""
import json,re,sys
from collections import Counter,defaultdict
from pathlib import Path

R3=Path(__file__).resolve().parents[1];R2=R3.parent/'nodefirst_qa_v2_20261117_r2';R1=R3.parent/'nodefirst_qa_v2_20261117_r1'
FULL=re.compile(r'^nodefirst_v2_r1::\d{3}$')
def load(p): return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def save(p,rows): p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
def index(rows,label):
 out={}
 for x in rows:
  did=x.get('draft_id')
  if not isinstance(did,str) or not FULL.fullmatch(did) or did in out:raise ValueError(f'{label}: invalid/duplicate {did}')
  out[did]=x
 return out
def executed(x): return x.get('executed') is True or str(x.get('status','')).upper() in {'PASS','FAIL','EXECUTED','NOT_APPLICABLE','COMPLETED'}
def main():
 try:
  actions=index(load(R3/'pr4_audit_actions.jsonl'),'actions');disp=index(load(R3/'pr4_disposition_r3.jsonl'),'dispositions');cands=index(load(R3/'qa_candidates_r3.jsonl'),'candidates');reviews=index(load(R3/'qa_independent_reviews_r3_pass2.jsonl'),'reviews')
  mappings=load(R1/'canonical_mapping_audit.jsonl');sources=load(R1/'source_integrity_audit.jsonl')
 except (ValueError,FileNotFoundError) as e:print(e,file=sys.stderr);return 2
 mi=defaultdict(list);si=defaultdict(list)
 for x in mappings:
  cid=str(x.get('canonical_node_id'));eid=str(x.get('evidence_unit_id') or cid);mi[(cid,eid)].append(x)
 for x in sources:si[str(x.get('canonical_node_id'))].append(x)
 global_errors=[]
 if len(actions)!=20:global_errors.append('PR4_MANIFEST_NOT_20')
 if Counter(x['pr4_content_verdict'] for x in actions.values())!={'PASS':16,'REVISE':4}:global_errors.append('PR4_VERDICT_COUNTS_MISMATCH')
 if set(cands)|{k for k,v in disp.items() if v['r3_status']=='EXCLUDE_RESAMPLE'} != set(actions):global_errors.append('PR4_FULL_ID_COVERAGE_MISMATCH')
 rows=[]
 for did in sorted(actions):
  errors=[];checks={};status=disp[did]['r3_status']
  if status=='EXCLUDE_RESAMPLE':
   if did in cands:errors.append('EXCLUDED_RECORD_PRESENT')
   rows.append({'draft_id':did,'pr4_content_verdict':actions[did]['pr4_content_verdict'],'status':'EXCLUDED_RESAMPLE' if not errors else 'BLOCKED','checks':{},'blocking_reasons':errors});continue
  if did not in cands:errors.append('R3_CANDIDATE_MISSING')
  if did not in reviews:errors.append('INDEPENDENT_REVIEW_MISSING')
  if errors:
   rows.append({'draft_id':did,'pr4_content_verdict':actions[did]['pr4_content_verdict'],'status':'BLOCKED','checks':{},'blocking_reasons':errors});continue
  c=cands[did];r=reviews[did];ev=c.get('gold_evidence_draft',[]);claims=c.get('answer_claims',[])
  docs={x.get('document_id') for x in ev};pages={(x.get('document_id'),x.get('page_id')) for x in ev};cat=c.get('qa_category')
  category=(cat=='single_node' and len(ev)==1) or (cat=='cross_page' and len(docs)==1 and len(pages)>=2) or (cat=='cross_document' and len(docs)>=2)
  if not category:errors.append('CATEGORY_CONSTRAINT_FAIL')
  covered=set();integrative=False;ground=True
  for j,cl in enumerate(claims):
   support=cl.get('supporting_evidence_indices',[]);covered.update(x for x in support if isinstance(x,int));integrative|=len(set(support))>=2
   spans=cl.get('evidence_spans',[])
   if not spans:errors.append(f'CLAIM_{j}_SPAN_EMPTY');ground=False
   seen=set()
   for k,s in enumerate(spans):
    ei=s.get('evidence_index');txt=s.get('text');start=s.get('char_start');end=s.get('char_end')
    ok=isinstance(ei,int) and 0<=ei<len(ev) and isinstance(txt,str) and isinstance(start,int) and isinstance(end,int) and ev[ei]['evidence_text'][start:end]==txt
    if not ok:errors.append(f'CLAIM_{j}_SPAN_{k}_NOT_EXACT');ground=False
    else:seen.add(ei)
   if not set(support)<=seen:errors.append(f'CLAIM_{j}_SUPPORT_WITHOUT_SPAN');ground=False
  if covered!=set(range(len(ev))):errors.append('CLAIMS_DO_NOT_COVER_ALL_NODES');ground=False
  if cat!='single_node' and not integrative:errors.append('INTEGRATIVE_CLAIM_MISSING')
  mapping=all(any(x.get('mapping_status')=='MAPPED_VERIFIED_AUTOMATIC' for x in mi[(str(e.get('canonical_node_id')),str(e.get('evidence_unit_id')))]) for e in ev)
  source=all(any(x.get('source_integrity_status')=='SOURCE_INTEGRITY_PASS' for x in si[str(e.get('canonical_node_id'))]) for e in ev)
  if not mapping:errors.append('CANONICAL_MAPPING_FAIL')
  if not source:errors.append('SOURCE_INTEGRITY_FAIL')
  deletion={x.get('evidence_index',x.get('removed_evidence_index')):x for x in r.get('node_deletion_results',[])}
  necessity=all(i in deletion and (deletion[i].get('node_required') is True or deletion[i].get('answer_complete_without_node') is False) for i in range(len(ev)))
  if not necessity:errors.append('NODE_NECESSITY_FAIL_OR_INCOMPLETE')
  dup=r.get('duplicate_retrieval',{});shortcut=r.get('shortcut_retrieval',{})
  dup_ok=executed(dup) and r.get('duplicate_pass') is True and dup.get('normalized_exact_duplicate') is False
  shortcut_ok=executed(shortcut) and r.get('single_node_shortcut_found') is False and shortcut.get('single_node_shortcut_found',shortcut.get('found',False)) is False
  if not dup_ok:errors.append('DUPLICATE_GATE_FAIL')
  if not shortcut_ok:errors.append('SINGLE_NODE_SHORTCUT_GATE_FAIL')
  sem_keys=['model_review_pass','question_validity','answer_correctness','evidence_sufficiency','each_gold_node_required','duplicate_pass','answer_claim_grounding_pass','integrative_reasoning_pass']
  semantic=all(r.get(k) is True for k in sem_keys) and r.get('single_node_shortcut_found') is False and 'independent' in str(r.get('reviewer','')).lower()
  if not semantic:errors.append('INDEPENDENT_SEMANTIC_REVIEW_FAIL')
  checks={'category_constraint':category,'claim_exact_spans':ground,'integrative_claim':cat=='single_node' or integrative,'canonical_mapping':mapping,'source_integrity':source,'node_necessity':necessity,'duplicate':dup_ok,'single_node_shortcut':shortcut_ok,'independent_semantic_review':semantic}
  rows.append({'draft_id':did,'pr4_content_verdict':actions[did]['pr4_content_verdict'],'status':'GOLD_ELIGIBLE_AUTOMATIC' if not errors else 'BLOCKED','checks':checks,'blocking_reasons':errors})
 save(R3/'deterministic_validation_r3.jsonl',rows)
 eligible=[x for x in rows if x['status']=='GOLD_ELIGIBLE_AUTOMATIC'];counts=Counter(cands[x['draft_id']]['qa_category'] for x in eligible)
 summary={'join_key':'complete draft_id','pr4_input_count':len(actions),'status_counts':dict(Counter(x['status'] for x in rows)),'blocking_reason_counts':dict(Counter(e for x in rows for e in x['blocking_reasons'])),'gold_eligible_count':len(eligible),'gold_eligible_by_category':dict(counts),'manifest_or_global_errors':global_errors,'manual_approval_required':False,'automatic_gold_export_allowed':not global_errors and bool(eligible)}
 (R3/'deterministic_validation_summary_r3.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(summary,ensure_ascii=False,indent=2))
 return 0 if summary['automatic_gold_export_allowed'] else 1
if __name__=='__main__':raise SystemExit(main())
