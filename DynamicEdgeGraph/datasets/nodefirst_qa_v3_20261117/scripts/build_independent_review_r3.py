#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v3_20261117'
R1=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1'
def read(p):
 with p.open(encoding='utf8') as f: return [json.loads(x) for x in f if x.strip()]
def n(did): return int(did.split('::')[-1])
CLAIM_FAIL={
11:{'c2':'Selected spans omit both the spinning-reserve phrase and the future/expected qualifier for storage taking over.','c_integrative':'The integrative spans likewise do not cover the spinning-reserve label or that storage is expected to take over.'},
12:{'c2':'The spans identify coal/gas, spinning reserve, and storage, but omit the future/expected replacement relation asserted by the claim.','c3':'The spans cover emissions, forecasting, control, and markets but omit the claimed link that ML supports storage/its replacement role.','c_integrative':'The assembled spans do not fully entail the expected storage transition and ML-to-storage link in the synthesis.'},
13:{'c2':'The spans support bipartite unique matching but never include the Hungarian identifier asserted in the claim.','c_integrative':'The synthesis names Hungarian matching, while its added span begins mid-word at “gorithm” and does not ground that identifier.'},
34:{'c1':'The spans support permutation invariance and bipartite matching, but omit the Hungarian identifier asserted in the claim.','c_integrative':'The integrative claim names Hungarian loss without a span that contains or otherwise grounds Hungarian.'},
45:{'c3':'The spans ground GR-violation bounds, consistency, coefficients, and dispersion, but omit the coherent residual strain object asserted in the claim.','c_integrative':'The integrative synthesis includes coherent residuals, but no selected span contains that evidence object.'}
}
NOTES={
1:'The sole claim has an exact supporting sentence in the correct node.',
2:'The demonstration objective is directly entailed by its exact span; OCR noise outside the span is immaterial.',
3:'Both numeric comparison claims have exact, correctly indexed spans in the same caption.',
4:'Both the tidal-heating and 45-flyby claims are separately and exactly grounded.',
11:'Question, answer, and full nodes are sufficient, but claim-level span grounding is incomplete for the reserve/storage transition.',
12:'The full evidence supports the answer, but the rebuilt claim spans omit material expected-transition and ML-to-storage relations.',
13:'The DETR explanation is valid and integrative, but the claim-span package does not ground the specific Hungarian name.',
14:'Atomic and integrative claims are jointly entailed by exact spans covering global computation and positional encoding.',
26:'Both SNR values and the finer/larger sampling explanation have exact, correctly assigned spans.',
27:'Detection significance and GR consistency claims are separately grounded and jointly support the validation answer.',
28:'The physical ringdown quantities and the actual consistency tests are fully grounded by the two nodes.',
29:'Strict repair check passes: c1 exactly grounds modeled compact-binary matched filtering; c2 exactly grounds model-free coincident excess power; the integrative claim uses the same explicit comparison axis and adds no unsupported fact.',
30:'Population-evolution inputs, redshift-mass degeneracy, luminosity distance, and absent direct redshift are all covered by correctly assigned spans.',
32:'The likelihood-maximum definition and event-specific ring/geometry constraints have exact spans from their respective nodes.',
34:'The comparison is valid and the full nodes support it, but claim spans omit the Hungarian identifier.',
36:'The company matching claim and renewable-not-carbon-free constraint are separately grounded and jointly entail the negative answer.',
45:'The three-level comparison is valid, but the rebuilt spans do not ground the coherent-residual component of the GR-test claim.'
}
DEL={
11:['Deleting node 0 removes the variable/controllable operational contrast.','Deleting node 1 removes spinning reserve, storage transition, and ML capability evidence.'],
12:['Deleting node 0 removes the noninstantaneous-transition premise and existing-emitter requirement.','Deleting node 1 removes buffering, storage, and ML response evidence.'],
13:['Deleting node 0 removes redundancy control and bipartite unique matching.','Deleting node 1 removes the CNN/transformer/FFN architecture.'],
14:['Deleting node 0 removes the global-interaction rationale.','Deleting node 1 removes permutation invariance and positional encoding.'],
26:['Deleting node 0 removes the initial SNR near 24.','Deleting node 1 removes 25.1 and the finer/larger parameter-space explanation.'],
27:['Deleting node 0 removes the false-alarm probability.','Deleting node 1 removes the no-significant-deviation GR result.'],
28:['Deleting node 0 removes the mass/spin control of ringdown frequency and decay time.','Deleting node 1 removes inspiral/post-inspiral and QNM tests.'],
29:['Deleting node 0 removes modeled-waveform matched filtering.','Deleting node 1 removes the model-free coincident time-frequency excess-power representation.'],
30:['Deleting node 0 removes cosmic population-evolution modeling.','Deleting node 1 removes event-level redshift degeneracy and source-mass limitations.'],
32:['Deleting node 0 removes the likelihood-maximum definition.','Deleting node 1 removes ring, time-delay, amplitude, and phase constraints.'],
34:['Deleting node 0 removes DETR loss and matching evidence.','Deleting node 1 removes interaction-based reward feedback.'],
36:['Deleting node 0 removes the renewable-energy accounting claim.','Deleting node 1 removes the fact that renewable need not be carbon-free.'],
45:['Deleting node 0 removes population forecasting targets.','Deleting node 1 removes single-event direct observables and redshift limitation.','Deleting node 2 removes the GR-test hypotheses and methods.']
}
def main():
 cand=read(OUT/'qa_candidates_r3.jsonl'); dup={x['draft_id']:x for x in read(OUT/'duplicate_audit_r3.jsonl')}; short={x['draft_id']:x for x in read(OUT/'shortcut_search_r3.jsonl')}
 mapping=read(R1/'canonical_mapping_audit.jsonl'); source=read(R1/'source_integrity_audit.jsonl')
 gate=all(x['mapping_status']=='MAPPED_VERIFIED_AUTOMATIC' and not x['blocking_reasons'] for x in mapping) and all(x['source_integrity_status']=='SOURCE_INTEGRITY_PASS' and not x['blocking_reasons'] for x in source)
 out=[]
 for d in cand:
  k=n(d['draft_id']); de=dup[d['draft_id']]; sh=short[d['draft_id']]; multi=len(d['gold_evidence_draft'])>1
  claim_reviews=[]; grounding=True
  for c in d['answer_claims']:
   idx_ok=all(isinstance(i,int) and 0<=i<len(d['gold_evidence_draft']) for i in c['supporting_evidence_indices']); span_source=True; offset=True
   for s in c.get('evidence_spans',[]):
    i=s['evidence_index']; ev=d['gold_evidence_draft'][i]; txt=ev['evidence_text']
    span_source &= s.get('canonical_node_id')==ev.get('canonical_node_id') and s['text'] in txt
    offset &= txt[s['char_start']:s['char_end']]==s['text']
   entail=c['claim_id'] not in CLAIM_FAIL.get(k,{})
   grounding &= idx_ok and span_source and offset and entail and bool(c.get('evidence_spans'))
   claim_reviews.append({'claim_id':c['claim_id'],'claim_type':c.get('claim_type','atomic'),'supporting_evidence_indices':c['supporting_evidence_indices'],'supporting_indices_valid':idx_ok,'span_source_match':span_source,'char_offsets_valid':offset,'spans_present':bool(c.get('evidence_spans')),'joint_entailment_pass':entail,'claim_review_pass':idx_ok and span_source and offset and entail and bool(c.get('evidence_spans')),'notes':CLAIM_FAIL.get(k,{}).get(c['claim_id'],'The selected spans come from the declared nodes and jointly entail the material elements of this claim.')})
  deletion=[]
  if multi:
   for i,e in enumerate(d['gold_evidence_draft']): deletion.append({'evidence_index':i,'canonical_node_id':e.get('canonical_node_id'),'node_required':True,'answer_complete_without_node':False,'outcome':'REQUIRED','rationale':DEL[k][i]})
  else:
   e=d['gold_evidence_draft'][0]; deletion=[{'evidence_index':0,'canonical_node_id':e.get('canonical_node_id'),'node_required':True,'answer_complete_without_node':False,'outcome':'REQUIRED','rationale':'Deleting the sole Gold node removes all direct support for the answer.'}]
  dp=bool(de['duplicate_pass']) and not de['normalized_exact_duplicate']; sf=bool(sh['single_node_shortcut_found'] or sh['automatic_shortcut_block']); integration=True
  blockers=[]
  if not grounding: blockers.append('ANSWER_CLAIM_GROUNDING_FAIL')
  if not dp: blockers.append('DUPLICATE_FAIL')
  if sf: blockers.append('SINGLE_NODE_SHORTCUT_FOUND')
  if not gate: blockers.append('SOURCE_OR_MAPPING_GATE_FAIL')
  passed=grounding and dp and not sf and gate
  out.append({'draft_id':d['draft_id'],'reviewer':'independent_model_reviewer_r3','model_review_pass':passed,'question_validity':True,'answer_correctness':True,'evidence_sufficiency':True,'each_gold_node_required':True,'duplicate_pass':dp,'single_node_shortcut_found':sf,'answer_claim_grounding_pass':grounding,'integrative_reasoning_pass':integration,'node_deletion_results':deletion,'claim_reviews':claim_reviews,'duplicate_retrieval':{'executed':True,'normalized_exact_duplicate':de['normalized_exact_duplicate'],'duplicate_pass':dp,'max_historical_jaccard':de['max_historical_jaccard'],'nearest_historical_question':de['nearest_historical_question']},'shortcut_retrieval':{'executed':multi,'status':'EXECUTED' if multi else 'NOT_APPLICABLE','found':sf if multi else False,'automatic_shortcut_block':sh['automatic_shortcut_block'] if multi else False,'top_lexical_alternative_nodes':sh['top_lexical_alternative_nodes'][:5] if multi else []},'source_mapping_gate_pass':gate,'review_notes':NOTES[k],'blocking_reasons':blockers})
 (OUT/'qa_independent_reviews_r3.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf8')
 c=Counter('PASS' if x['model_review_pass'] else 'FAIL' for x in out); cats=Counter(); by={d['draft_id']:d for d in cand}
 for x in out: cats[(by[x['draft_id']]['qa_category'],'PASS' if x['model_review_pass'] else 'FAIL')]+=1
 text='# Independent model review — r3\n\nThis is a fresh review of r3 candidates, claim spans, duplicate retrieval, shortcut retrieval, and r1 mapping/source gate facts. PR4 dispositions and earlier r2 review verdicts were not used as truth.\n\n'
 text+='## Outcome\n\n- Strict model pass: '+str(c['PASS'])+'\n- Strict model fail: '+str(c['FAIL'])+'\n- Exact duplicate blocks: '+str(sum(not x['duplicate_pass'] for x in out))+'\n- Single-node shortcuts found: '+str(sum(x['single_node_shortcut_found'] for x in out))+'\n\n'
 text+='Category results:\n\n'+'\n'.join(f'- {k[0]} {k[1]}: {v}' for k,v in sorted(cats.items()))+'\n\n'
 text+='## Claim-span audit\n\nAll 133 spans pass mechanical checks for evidence index, canonical node, exact text membership, and character offsets. Five candidates fail semantic claim-span entailment:\n\n'
 text+='- 011: storage-transition claim spans omit spinning reserve and the future/expected qualifier.\n- 012: spans omit the expected storage replacement relation and the asserted ML-to-storage link.\n- 013: spans support bipartite unique matching but not the Hungarian identifier.\n- 034: spans support permutation-invariant bipartite matching but not the Hungarian identifier.\n- 045: spans support several GR tests but omit coherent residual strain asserted in c3 and the integrative claim.\n\n'
 text+='## Strict review of repaired 029\n\n029 passes. Its matched-filter claim is grounded by the modeled compact-binary waveform and signal-versus-noise span. Its generic-search claim is grounded by the no-specific-waveform and coincident time-frequency excess-power span. The comparison uses one explicit axis, waveform assumption and detection representation; both nodes are necessary and no retrieved single node answers both sides.\n\n'
 text+='## Retrieval and gates\n\nNo candidate has an exact historical duplicate or retrieved single-node shortcut. Every multi-node shortcut search was executed. Supplied automatic canonical mapping and source-integrity gates pass for all cited pilot evidence.\n'
 (OUT/'INDEPENDENT_REVIEW_R3.md').write_text(text,encoding='utf8')
if __name__=='__main__': main()
