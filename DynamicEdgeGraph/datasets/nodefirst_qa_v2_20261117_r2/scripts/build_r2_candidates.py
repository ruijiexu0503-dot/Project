#!/usr/bin/env python3
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
R1=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1'
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r2'
LEG=ROOT/'DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/nodes.jsonl'
HIST=ROOT/'DynamicEdgeGraph/datasets/all_qa_review_drafts_v1/all_qa_drafts.jsonl'
def load(p):
 with p.open(encoding='utf8') as f:return [json.loads(x) for x in f if x.strip()]
def save(p,x):p.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in x),encoding='utf8')
def norm(s):return ' '.join(re.findall(r'[a-z0-9]+',s.lower()))
def tok(s):return set(norm(s).split())
def jac(a,b):
 a,b=tok(a),tok(b);return len(a&b)/len(a|b) if a|b else 1
def clauses(s):
 return [x.strip(' .') for x in re.split(r'(?<=[.!?])\s+|;\s+',s) if len(tok(x))>=2]
def spans(text):
 xs=[]
 for m in re.finditer(r'[^\n.!?]+(?:[.!?]|$)',text):
  q=m.group(0).strip()
  if q:xs.append((q,m.start(),m.end()))
 return xs or [(text,0,len(text))]
def ground_claims(answer,evidence):
 out=[]
 for i,c in enumerate(clauses(answer),1):
  ranked=[]
  for ei,e in enumerate(evidence):
   for s,a,b in spans(e['evidence_text']):ranked.append((jac(c,s),ei,s,a,b))
  ranked.sort(reverse=True);best=ranked[0];support=[best[1]]
  out.append({'claim_id':f'c{i}','claim_text':c,'supporting_evidence_indices':support,'evidence_spans':[{'evidence_index':best[1],'canonical_node_id':evidence[best[1]]['canonical_node_id'],'text':best[2],'char_start':best[3],'char_end':best[4]}],'grounding_method':'deterministic_best_span_pending_independent_review','token_jaccard':round(best[0],4)})
 return out
def add_integrative_claim(answer,evidence,claims,category):
 if category=='single_node' or any(len(set(c.get('supporting_evidence_indices',[])))>=2 for c in claims):return claims
 exact=[]
 for ei,e in enumerate(evidence):
  ranked=sorted((jac(answer,s),s,a,b) for s,a,b in spans(e['evidence_text']))
  _,s,a,b=ranked[-1]
  exact.append({'evidence_index':ei,'canonical_node_id':e['canonical_node_id'],'text':s,'char_start':a,'char_end':b})
 claims.append({'claim_id':'c_integrative','claim_text':answer,'claim_type':'integrative_synthesis','supporting_evidence_indices':list(range(len(evidence))),'evidence_spans':exact,'grounding_method':'deterministic_multi_node_span_bundle_pending_independent_review'})
 return claims
def normalize_necessity(claims,evidence):
 deletion=[]
 for ei in range(len(evidence)):
  exclusive=[c['claim_id'] for c in claims if c.get('supporting_evidence_indices')==[ei]]
  required=bool(exclusive) or len(evidence)==1
  deletion.append({'removed_evidence_index':ei,'missing_claim_ids':exclusive,'node_required':required,'answer_complete_without_node':not required,'outcome':'FAIL_WITHOUT_NODE' if required else 'PENDING_INDEPENDENT_REVIEW','model_judgment':'PENDING_INDEPENDENT_REVIEW'})
 return {'each_gold_node_required':all(x['node_required'] for x in deletion),'single_node_shortcut_found':None,'node_deletion_results':deletion,'alternative_gold_sets':[]}
def normalize_proposal_claims(claims,evidence):
 out=[]
 for c in claims:
  x=json.loads(json.dumps(c));normalized=[]
  for raw in x.get('evidence_spans',[]):
   found=None
   for ei in x['supporting_evidence_indices']:
    text=evidence[ei]['evidence_text'];pos=text.find(raw)
    if pos<0:pos=text.lower().find(raw.lower())
    if pos>=0:
     found={'evidence_index':ei,'canonical_node_id':evidence[ei]['canonical_node_id'],'text':text[pos:pos+len(raw)],'char_start':pos,'char_end':pos+len(raw)};break
   if found:normalized.append(found)
   else:normalized.append({'evidence_index':x['supporting_evidence_indices'][0],'canonical_node_id':evidence[x['supporting_evidence_indices'][0]]['canonical_node_id'],'text':raw,'char_start':None,'char_end':None,'span_resolution':'UNRESOLVED'})
  x['evidence_spans']=normalized;out.append(x)
 return out
KEEP_UPDATES={
 'nodefirst_v2_r1::004':{'reasoning_type':'composite_fact'},
 'nodefirst_v2_r1::006':{'question':'How was the simulated night-side Earth view assembled?'},
 'nodefirst_v2_r1::016':{'gold_answer_draft':'The RMF frames risk management as aligning AI design and use with human-centered and socially responsible values; NIST plans future work with the AI community to measure whether the framework improves trustworthiness.'},
 'nodefirst_v2_r1::018':{'gold_answer_draft':'Cosmological redshift rescales detector-frame mass by 1+z. The inferred source-frame masses were 36 (+5/-4) and 29 (+4/-4) solar masses.'},
 'nodefirst_v2_r1::023':{'question':'What limitation of standard country-growth diagnostics motivates using growth regressions, and what non-causal policy use can those regressions still provide?'},
 'nodefirst_v2_r1::027':{'gold_answer_draft':'The generic transient search found a false-alarm probability below 2e-6 during the analyzed observing time, while dedicated tests found no statistically significant departure from a binary-black-hole merger governed by the vacuum Einstein equations.'},
 'nodefirst_v2_r1::029':{'question':'How do a modeled matched-filter search and a generic transient search differ in their use of waveform assumptions and noise-background treatment?'},
 'nodefirst_v2_r1::034':{'reasoning_type':'cross_domain_comparison'},
 'nodefirst_v2_r1::036':{'gold_answer_draft':'No. NVIDIA reports an annual accounting match between renewable energy purchased or generated and electricity use at controlled sites; the other source states that renewable energy is not necessarily carbon-free.'}
}
def main():
 r1={x['draft_id']:x for x in load(R1/'qa_gold_auto_accepted_pool_r1.jsonl')}; actions=load(OUT/'pr3_audit_actions.jsonl'); props={x['draft_id']:x for x in load(OUT/'r2_repair_proposals.jsonl')}
 candidates=[];disposition=[]
 for a in actions:
  rid=a['draft_id']; verdict=a['audit_verdict']
  if verdict=='REMOVE':
   disposition.append({'draft_id':rid,'r2_status':'REMOVE_RESAMPLE','reason':a.get('reason')});continue
  if verdict=='REVISE':
   p=props[rid]
   if p['proposal_status']!='REVISED_CANDIDATE':
    disposition.append({'draft_id':rid,'r2_status':'REMOVE_RESAMPLE','reason':p.get('repair_note')});continue
  d=json.loads(json.dumps(r1[rid]));d['parent_draft_id']=rid;d['draft_id']=rid;d['r2_candidate_id']=rid.replace('_r1::','_r2::');d['corpus_snapshot']='nodefirst_qa_v2_20261117_r2'
  if verdict=='REVISE':
   p=props[rid];d['question']=p['proposed_question'];d['gold_answer_draft']=p['proposed_answer'];d['reasoning_type']=p['proposed_reasoning_type'];d['integrative_reasoning']=p['integrative_reasoning'];d['answer_claims']=normalize_proposal_claims(p['answer_claims'],d['gold_evidence_draft']);d['repair_note']=p['repair_note']
  else:
   for k,v in KEEP_UPDATES.get(rid,{}).items():d[k]=v
   d['answer_claims']=ground_claims(d['gold_answer_draft'],d['gold_evidence_draft'])
   d['integrative_reasoning']={'label':'SINGLE_NODE_NOT_APPLICABLE' if d['qa_category']=='single_node' else 'PENDING_INDEPENDENT_REVIEW','rationale':'Recomputed in r2 independent review.'}
  d['answer_claims']=add_integrative_claim(d['gold_answer_draft'],d['gold_evidence_draft'],d['answer_claims'],d['qa_category'])
  d['necessity_test']=normalize_necessity(d['answer_claims'],d['gold_evidence_draft'])
  d['audit_provenance']={'pr_number':3,'manifest_draft_id':rid,'audit_verdict':verdict,'join_key':'full_draft_id'}
  d['review']={'status':'PENDING_INDEPENDENT_MODEL_REVIEW_R2'};d.pop('final_gate',None);candidates.append(d);disposition.append({'draft_id':rid,'r2_status':'CANDIDATE_REVISED' if verdict=='REVISE' else 'CANDIDATE_KEEP'})
 allnodes=load(LEG)+load(R1/'real_canonical_nodes_pilot_r1.jsonl');shortcut=[]
 for d in candidates:
  gold={e['canonical_node_id'] for e in d['gold_evidence_draft']};rank=[]
  for n in allnodes:
   nid=n.get('canonical_node_id');text=n.get('content_text','')
   if nid not in gold and text:rank.append((jac(d['gold_answer_draft'],text),nid,n.get('doc_id') or n.get('document_id'),text[:240]))
  rank.sort(reverse=True)
  shortcut.append({'draft_id':d['draft_id'],'top_lexical_alternative_nodes':[{'score':round(s,4),'canonical_node_id':n,'document_id':doc,'preview':t} for s,n,doc,t in rank[:5]],'automatic_shortcut_block':rank[0][0]>=0.9 if rank else False,'model_shortcut_review':'PENDING'})
 hist=[x.get('question','') for x in load(HIST) if x.get('question')];dedup=[]
 for d in candidates:
  scores=sorted((jac(d['question'],q),q) for q in hist);best=scores[-1] if scores else (0,'')
  exact=any(norm(d['question'])==norm(q) for q in hist)
  dedup.append({'draft_id':d['draft_id'],'executed':True,'status':'FAIL' if exact else 'PASS','normalized_exact_duplicate':exact,'exact_historical_duplicate':exact,'duplicate_pass':not exact,'max_historical_jaccard':round(best[0],4),'nearest_historical_question':best[1],'model_duplicate_review':'PENDING'})
 save(OUT/'qa_candidates_r2.jsonl',candidates);save(OUT/'pr3_disposition_r2.jsonl',disposition);save(OUT/'shortcut_search_r2.jsonl',shortcut);save(OUT/'duplicate_audit_r2.jsonl',dedup)
 summary={'pr3_input':len(actions),'keep':sum(a['audit_verdict']=='KEEP' for a in actions),'revise':sum(a['audit_verdict']=='REVISE' for a in actions),'remove':sum(a['audit_verdict']=='REMOVE' for a in actions),'r2_candidates':len(candidates),'candidate_categories':{k:sum(d['qa_category']==k for d in candidates) for k in ['single_node','cross_page','cross_document']},'revised_retained':sum(x['r2_status']=='CANDIDATE_REVISED' for x in disposition),'remove_or_resample':sum(x['r2_status']=='REMOVE_RESAMPLE' for x in disposition)}
 (OUT/'r2_candidate_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':main()
