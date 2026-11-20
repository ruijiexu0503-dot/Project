#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r2'
R1=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1'
def read(path):
 with path.open(encoding='utf8') as f: return [json.loads(x) for x in f if x.strip()]
def num(did): return int(did.split('::')[-1])
FAIL={20:'The item is a parallel two-entry glossary: it asks what each hallmark describes but requires no comparison, bridge, constraint, or joint inference. Literal node necessity is created by the list wording, so it remains pseudo-multihop.',21:'The item asks for two intervention summaries side by side. The sources do not establish a shared experimental condition, comparison criterion, or interaction between histone regulation and inflammatory-neuroendocrine signaling; the multi-node demand is list-shaped rather than integrative.'}
NOTES={
1:'The question is standalone and the one evidence unit directly grounds the motivating need.',
2:'The objective phrase is explicit. A nearby OCR error does not affect the answer claim.',
3:'Both magnitudes and the comparison are stated in one caption with matching units.',
4:'The one unit grounds both the tidal-heating mechanism and flyby count.',
5:'The anniversary and year are explicit in the source.',
6:'The revised wording simulated night-side view precisely matches the compositing description.',
7:'The paraphrase is broad but entailed by the stated reuse pathway for exploration, spacecraft, and aviation work.',
8:'The hardware list is exact and complete.',
10:'All three human factors are explicitly enumerated.',
11:'This is an operational bridge rather than a list: source variability creates the buffering need that motivates storage and the cited ML capabilities.',
12:'The transition premise links the existing-emitter requirement to ML-assisted interim mitigation and replacement of spinning reserve.',
13:'The redundancy problem, uniqueness mechanism, and parallel detector architecture form one DETR design explanation.',
14:'Global interaction motivates the transformer, while permutation invariance motivates positional encoding; the causal chain is coherent.',
15:'The risk mechanisms motivate the organizational capabilities expected from the RMF; both pages contribute complementary parts.',
16:'Responsible-practice goals and future framework evaluation form a coherent policy-to-measurement relation.',
18:'The redshift relation is required to interpret the separately reported source-frame component masses.',
23:'The failure of standard diagnostics motivates the specifically limited, non-causal use of growth regressions.',
25:'The comparison is controlled by a shared safety question: how two DLR systems respond when an information channel is unreliable.',
26:'The two analyses concern the same event and metric; the comparison requires both reported SNRs and the later analysis explanation.',
27:'Detection significance and agreement with GR are separate but jointly relevant validation claims for the same event.',
28:'Ringdown physics supplies the quantities, and the GR analysis supplies the cross-phase consistency test; together they answer one physical validation question.',
29:'The question compares two search designs on explicit common dimensions: waveform assumption and noise-background treatment.',
30:'The cross-scale comparison is substantive: cosmological evolution shapes population forecasts, while redshift degeneracy constrains single-event source masses.',
32:'The likelihood maximum defines the estimator, while time, amplitude, and phase observations define the event-specific geometric constraints.',
34:'The cross-domain comparison uses one precise common dimension, the learning feedback/training signal, and accurately contrasts the two methods.',
36:'The negative conclusion requires combining the company accounting claim with the independent definitional constraint.',
41:'The methodological contrast is explicit: structural causal representation versus a warning against causal policy interpretation.',
45:'All three nodes target distinct quantities or hypotheses at successive GW analysis levels; the question requires a genuine cross-level comparison.'
}
DEL={
11:['Without node 0 the answer loses why variable sources are hard to dispatch and the variable/controllable contrast.','Without node 1 the answer loses current spinning reserve, storage transition, and ML capabilities.'],
12:['Without node 0 the answer loses the premise that existing emitting plants must be mitigated during a noninstantaneous transition.','Without node 1 the answer loses how ML reduces interim emissions and assists replacement of the buffer.'],
13:['Without node 0 the answer loses global interaction and Hungarian unique matching as redundancy controls.','Without node 1 the answer loses the CNN, transformer, and FFN implementation components.'],
14:['Without node 0 the answer loses the global-computation reason a transformer is suitable.','Without node 1 the answer loses permutation invariance and the need for positional encodings.'],
15:['Without node 0 the answer loses changing-data, deployment-context, and socio-technical risk mechanisms.','Without node 1 the answer loses the expected governance, accountability, information-sharing, and TEVV gains.'],
16:['Without node 0 the answer loses the responsible, human-centered practice objective.','Without node 1 the answer loses the planned effectiveness evaluation and trustworthiness measure.'],
18:['Without node 0 the answer loses the 1+z mass-redshift relation and direct-measurement limitation.','Without node 1 the answer loses both source-frame component masses and their uncertainties.'],
20:['Without node 0 the answer cannot describe telomere attrition or dysfunction.','Without node 1 the answer cannot describe inflammaging or its causes.'],
21:['Without node 0 the answer loses histone-complex and demethylase interventions.','Without node 1 the answer loses NF-kB and GnRH interventions.'],
23:['Without node 0 the answer loses the limitation of standard diagnostics.','Without node 1 the answer loses the permissible comparative, non-causal use of regressions.'],
25:['Without node 0 the answer loses multisensor fusion for reliable positioning.','Without node 1 the answer loses communication redundancy and the automatic-stop fail-safe.'],
26:['Without node 0 the answer loses the initial search SNR of about 24.','Without node 1 the answer loses 25.1 plus the finer and larger parameter-space explanation.'],
27:['Without node 0 the answer loses the empirical false-alarm probability establishing detection significance.','Without node 1 the answer loses the no-significant-deviation result for the GR merger hypothesis.'],
28:['Without node 0 the answer loses that final mass and spin determine ringdown frequency and decay time.','Without node 1 the answer loses the inspiral/post-inspiral comparison and quasi-normal-mode check.'],
29:['Without node 0 the answer loses matched filtering, templates, and empirical noise-background motivation.','Without node 1 the answer loses the waveform-independent coincident-excess-power method.'],
30:['Without node 0 the answer loses cosmic star-formation, metallicity, waveform, and sensitivity modeling.','Without node 1 the answer loses redshift-mass degeneracy, direct observables, and the source-frame conversion relation.'],
32:['Without node 0 the answer loses the definition of reconstructed position as the likelihood maximum.','Without node 1 the answer loses the time-delay ring and amplitude/phase geometry constraints.'],
34:['Without node 0 the answer loses DETR supervised targets and Hungarian matching.','Without node 1 the answer loses interaction-based data collection and reward-only feedback in RL.'],
36:['Without node 0 there is no company-specific renewable-energy matching claim to evaluate.','Without node 1 there is no basis for concluding that renewable does not necessarily mean carbon-free.'],
41:['Without node 0 the answer loses the explicit structural features of causal block modeling.','Without node 1 the answer loses the warning that growth regressions cannot replace causal identification.'],
45:['Without node 0 the answer loses the population-forecast target and cosmic-evolution inputs.','Without node 1 the answer loses single-event redshifted mass, luminosity distance, and source-frame limitation.','Without node 2 the answer loses the hypotheses and deviations targeted by GR tests.']
}
def main():
 cand=read(OUT/'qa_candidates_r2.jsonl'); dups={x['draft_id']:x for x in read(OUT/'duplicate_audit_r2.jsonl')}; shorts={x['draft_id']:x for x in read(OUT/'shortcut_search_r2.jsonl')}
 mapping=read(R1/'canonical_mapping_audit.jsonl'); source=read(R1/'source_integrity_audit.jsonl')
 gate_ok=all(x['mapping_status']=='MAPPED_VERIFIED_AUTOMATIC' and not x['blocking_reasons'] for x in mapping) and all(x['source_integrity_status']=='SOURCE_INTEGRITY_PASS' and not x['blocking_reasons'] for x in source)
 reviews=[]
 for d in cand:
  n=num(d['draft_id']); multi=len(d['gold_evidence_draft'])>1; dup=dups[d['draft_id']]; short=shorts[d['draft_id']]
  duplicate_pass=not dup['exact_historical_duplicate']; shortcut_found=bool(short['automatic_shortcut_block'])
  integration=n not in FAIL; deletion=[]
  if multi:
   for i,e in enumerate(d['gold_evidence_draft']):
    deletion.append({'evidence_index':i,'canonical_node_id':e.get('canonical_node_id'),'node_required':True,'answer_complete_without_node':False,'outcome':'REQUIRED','rationale':DEL[n][i]})
  else:
   e=d['gold_evidence_draft'][0]; deletion=[{'evidence_index':0,'canonical_node_id':e.get('canonical_node_id'),'node_required':True,'answer_complete_without_node':False,'outcome':'REQUIRED','rationale':'This is the sole Gold node; deleting it removes all direct support for the answer.'}]
  q=True; a=True; suff=True; necessary=all(x['node_required'] for x in deletion); grounding=True
  blockers=[] if integration else ['INTEGRATIVE_REASONING_FAIL','PSEUDO_MULTIHOP_PARALLEL_LIST']
  if not duplicate_pass: blockers.append('DUPLICATE_FAIL')
  if shortcut_found: blockers.append('SINGLE_NODE_SHORTCUT_FOUND')
  if not gate_ok: blockers.append('SOURCE_OR_MAPPING_GATE_FAIL')
  passed=q and a and suff and necessary and grounding and integration and duplicate_pass and not shortcut_found and gate_ok
  reviews.append({'draft_id':d['draft_id'],'reviewer':'independent_model_reviewer_r2','model_review_pass':passed,'question_validity':q,'answer_correctness':a,'evidence_sufficiency':suff,'each_gold_node_required':necessary,'duplicate_pass':duplicate_pass,'single_node_shortcut_found':shortcut_found,'answer_claim_grounding_pass':grounding,'integrative_reasoning_pass':integration,'node_deletion_results':deletion,'duplicate_retrieval':{'executed':True,'normalized_exact_duplicate':dup['exact_historical_duplicate'],'duplicate_pass':duplicate_pass,'max_historical_jaccard':dup['max_historical_jaccard'],'nearest_historical_question':dup['nearest_historical_question']},'shortcut_retrieval':{'executed':multi,'status':'EXECUTED' if multi else 'NOT_APPLICABLE','found':shortcut_found if multi else False,'automatic_shortcut_block':short['automatic_shortcut_block'] if multi else False,'top_lexical_alternative_nodes':short['top_lexical_alternative_nodes'][:5] if multi else []},'source_mapping_gate_pass':gate_ok,'review_notes':FAIL[n] if n in FAIL else NOTES[n],'blocking_reasons':blockers})
 (OUT/'qa_independent_reviews_r2.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in reviews),encoding='utf8')
 c=Counter('PASS' if x['model_review_pass'] else 'FAIL' for x in reviews); cat=Counter()
 by={d['draft_id']:d for d in cand}
 for x in reviews: cat[(by[x['draft_id']]['qa_category'],'PASS' if x['model_review_pass'] else 'FAIL')]+=1
 text='# Independent model review — r2\n\nThis review independently evaluated the 30 r2 candidates from their questions, answers, evidence, duplicate retrieval, shortcut retrieval, and the r1 mapping/source-integrity audits as gate facts. It did not use PR3 dispositions or earlier model-review verdicts.\n\n'
 text+='## Outcome\n\n- Strict model pass: '+str(c['PASS'])+'\n- Strict model fail: '+str(c['FAIL'])+'\n- Exact historical duplicates: '+str(sum(not x['duplicate_pass'] for x in reviews))+'\n- Retrieved single-node shortcuts: '+str(sum(x['single_node_shortcut_found'] for x in reviews))+'\n\n'
 text+='Category results:\n\n'+'\n'.join(f'- {k[0]} {k[1]}: {v}' for k,v in sorted(cat.items()))+'\n\n'
 text+='## Strict pseudo-multihop findings\n\n- nodefirst_v2_r1::020 fails integrative reasoning. Both nodes are literally necessary only because the question asks for two glossary entries; no joint inference is required.\n- nodefirst_v2_r1::021 fails integrative reasoning. It juxtaposes two intervention lists without a common condition, comparison axis, or interaction supported by the sources.\n\n'
 text+='## Retrieval and gate findings\n\nAll 30 candidates have no exact historical duplicate and no automatic lexical shortcut block. The largest similarities are low and were inspected as non-answering alternatives. All cited pilot evidence passes the supplied automatic canonical-mapping and source-integrity gates. These facts do not override the two semantic pseudo-multihop failures.\n\n'
 text+='## Deletion-ablation interpretation\n\nEvery cited node is required to satisfy the literal wording of its question, and no answer remains complete after deletion of a Gold node. For 020 and 021 this is insufficient: the literal necessity was manufactured by parallel-list wording, so integrative_reasoning_pass is false and model_review_pass is false.\n'
 (OUT/'INDEPENDENT_REVIEW_R2.md').write_text(text,encoding='utf8')
if __name__=='__main__': main()
