#!/usr/bin/env python3
"""Build a non-destructive r3 repair set from the PR #4 20-item audit."""
import json,re
from pathlib import Path

R3=Path(__file__).resolve().parents[1]
ROOT=R3.parents[2]
R2=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r2'
HIST=ROOT/'DynamicEdgeGraph/datasets/all_qa_review_drafts_v1/all_qa_drafts.jsonl'
LEG=ROOT/'DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/nodes.jsonl'

IDS=['001','002','003','004','011','012','013','014','015','016','026','027','028','029','030','032','034','036','041','045']
REVISE={'015','016','029','041'}
CLAIM_FIX={'001','002','003','004','014','015','016','026','027','028','029','032','034','036'}
SECOND_PASS_FIX={'011','012','013','034','045'}
EXCLUDE={'015':'NO_EVIDENCE_GROUNDED_CROSS_PAGE_BRIDGE','016':'NO_EXPLICIT_PRINCIPLE_TO_EVALUATION_LINK','041':'CROSS_DOMAIN_CAUSAL_CONCEPT_CONFLATION'}

def load(p): return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def save(p,rows): p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
def norm(s): return ' '.join(re.findall(r'[a-z0-9]+',s.lower()))
def toks(s): return set(norm(s).split())
def jac(a,b):
 a,b=toks(a),toks(b);return len(a&b)/len(a|b) if a|b else 1
def span(evidence,ei,text):
 source=evidence[ei]['evidence_text'];start=source.find(text)
 if start<0: raise ValueError(f'span not found E{ei}: {text!r}')
 return {'evidence_index':ei,'canonical_node_id':evidence[ei]['canonical_node_id'],'text':text,'char_start':start,'char_end':start+len(text)}
def claim(cid,text,ei,needles,evidence):
 return {'claim_id':cid,'claim_text':text,'supporting_evidence_indices':[ei],'evidence_spans':[span(evidence,ei,x) for x in needles],'grounding_method':'pr4_semantic_repair_exact_span'}
def repaired_claims(code,e):
 specs={
 '001':[('c1','Generating oxygen and growing food in space motivated NASA to test indoor agriculture.',0,['The need to generate oxygen and grow food in space inspired NASA to test\nindoor agriculture techniques.'])],
 '002':[('c1','The Mars Helicopter was intended to demonstrate the viability and potential of heavier-than-air vehicles on Mars.',0,['The helicopter will demonstrate the\nviability and potential of heavier-than-air vehicles\non the Red Planet.'])],
 '003':[('c1','The Hubble image shows an area roughly 2 light-years across.',0,['this image shows an area roughly 2 light years across']),('c2','The full Veil Nebula is about 110 light-years across.',0,['the entire\nnebula is 110 light years across'])],
 '004':[('c1',"Jupiter's tidal forces are believed to cause enough internal friction to heat Europa's subsurface ocean.",0,["Tidal forces from Jupiter's\nimmense gravity are believed to cause\nenough internal friction to heat a stable\nocean of liquid water beneath the icy body's\nsurface."]),('c2','A future NASA mission was planned to conduct 45 flybys.',0,['a future NASA mission is being\nplanned that would conduct 45 flybys'])],
 '011':[('c1','Variable sources fluctuate with external conditions, while controllable sources can be turned on and off.',0,['Variable sources fluctuate based on external factors','controllable sources such as nuclear or geothermal plants can be turned on and off']),('c2','Coal and gas plants operating as spinning reserve currently provide the buffer, while storage is expected to take over this role.',1,['Today, this buffer is often provided by coal and natural gas\nplants run in a CO 2 -emitting standby mode called spinning reserve','In the future, this role is expected to be\nplayed by energy storage technologies such as batteries']),('c3','ML can reduce standby-generator emissions and improve forecasting, scheduling, control, and market design for variable electricity and flexible demand.',1,["ML\ncan both reduce emissions from today's standby generators",'forecasting, scheduling, and control','advanced electricity markets that accommodate both variable electricity and flexible demand'])],
 '012':[('c1','Existing CO2-emitting plants must have their emissions reduced because the low-carbon transition is not immediate.',0,['Reduce emissions from existing CO $_2$ -emitting power plants','will not happen overnight']),('c2','Coal and gas spinning reserve currently provides the buffer, and storage is expected to replace that role.',1,['Today, this buffer is often provided by coal and natural gas\nplants run in a CO 2 -emitting standby mode called spinning reserve','In the future, this role is expected to be\nplayed by energy storage technologies such as batteries']),('c3','ML can reduce standby-generator emissions and support the carbon-free transition through forecasting, scheduling, control, and electricity-market design.',1,["ML\ncan both reduce emissions from today's standby generators and enable the transition to carbon-free systems",'forecasting, scheduling, and control','advanced electricity markets that accommodate both variable electricity and flexible demand'])],
 '013':[('c1','Global inference models interactions among predictions to avoid redundancy.',0,['global inference schemes that model interactions\nbetween all predicted elements to avoid redundancy']),('c2','A Hungarian-algorithm bipartite matching guarantees each target a unique match.',0,['Hungarian al-\ngorithm [ 20 ] , to find a bipartite matching between ground-truth and prediction','guarantees that each target element\nhas a unique match']),('c3','The architecture uses a CNN backbone, encoder-decoder transformer, and FFN for the final prediction.',1,['a CNN backbone','an encoder-decoder transformer','a simple feed forward network (FFN) that makes the final detection prediction'])],
 '014':[('c1','Self-attention supports global interaction by aggregating information from the whole sequence.',0,['ag-\ngregating information from the whole sequence','global computations']),('c2','Fixed positional encodings supply position information because the transformer is permutation-invariant.',1,['Since the\ntransformer architecture is permutation-invariant, we supplement it with fixed\npositional encodings'])],
 '026':[('c1','The initial search reported an observed SNR of about 24.',0,['observed signal-to-\nnoise ratio (SNR) $\\sim$ 24']),('c2','The parameter analysis obtained an optimal coherent SNR of 25.1 (+1.7/-1.7), higher because it sampled a larger parameter space more finely.',1,['optimal coherent\nSNR of $\\rho = 25.1^{+1.7}_{-1.7}$','higher than the one\nreported by the search [1,3] because it is obtained using a\nfiner sampling of (a larger) parameter space'])],
 '027':[('c1','The generic transient search assigned a false-alarm probability below 2e-6 during the analysis time.',0,['probability $<2\\times10^{-6}$ of observing\none or more noise events as strong as GW150914 during\nthe analysis time']),('c2','Dedicated tests found no statistically significant evidence against a binary-black-hole merger governed by the vacuum Einstein equations.',1,['we find no statistically significant evidence\nagainst the hypothesis that GW150914 was emitted by two\nblack holes spiraling towards each other and merging to form\na single, rotating black hole','the dynamics\nof the process as a whole was in accordance with the vacuum\nEinstein field equations'])],
 '028':[('c1',"The final black hole's mass and spin determine the ringdown frequency and decay time.",0,['the final mass and spin determine the (constant)\nfrequency and decay time']),('c2','The analysis checked inspiral-predicted final mass and spin against post-inspiral estimates and the post-peak signal against the least-damped QNM.',1,["verify that the mass and spin parameters of the final black\nhole, as predicted from the binary's inspiral signal, are consis-\ntent with the final parameters inferred from the post-inspiral","data fol-\nlowing the peak of GW150914 are consistent with the least-\ndamped quasi-normal mode"] )],
 '029':[('c1','Matched filtering exploits modeled compact-binary waveforms to distinguish signals from the noise background.',0,['The gravitational waveforms for compact-object binaries\ncan be modeled using a combination of analytical and numerical methods [29, 30] .\nConsequently, it is natural to use matched filtering to distinguish signals from the\nnoise background']),('c2','The generic search uses no specific waveform model and identifies coincident excess power in time-frequency strain representations.',1,['Designed to operate without a specific waveform model,\nthis search identifies coincident excess power in time-\nfrequency representations of the detector strain data'])],
 '032':[('c1','The reconstructed sky position is the maximum of a likelihood statistic over sky coordinates.',0,['maximum likelihood\nand other coherent statistics are functions of the sky co-\nordinates','reconstructed source loca-\ntion is defined at the maximum of the likelihood statistic']),('c2','For GW150914, cross-site time delay plus amplitude and phase consistency constrain a sky ring and help resolve source geometry.',1,['The observed time delay, and the need for the registered\nsignal at the two sites to be consistent in amplitude and\nphase, allow us to localize the source to a ring on the sky','Phase and amplitude consistency\nallow us to untangle some of the geometry of the source'])],
 '034':[('c1','DETR uses a permutation-invariant Hungarian loss to match ground-truth and predictions.',0,['loss function should be invariant by a permutation of\nthe predictions','Hungarian al-\ngorithm [ 20 ] , to find a bipartite matching between ground-truth and prediction']),('c2','Reinforcement learning has no supervision; it gathers experience through environmental interaction and uses a reward signal.',1,['data/experience\nis collected by interacting with the environment','No supervision, just a reward signal'])],
 '036':[('c1','NVIDIA reported purchasing or generating enough renewable energy to match 100% of electricity usage at controlled sites.',0,['purchased or generated enough renewable energy to match 100% of our global electricity usage for\nsites under our operational control']),('c2','Renewable energy is not necessarily carbon-free.',1,['Renewable energy is produced from inexhaustible or easily replenished energy sources such as the sun, wind, or water, but need\nnot necessarily be carbon-free'])],
 '045':[('c1','Population forecasting models star-formation history and metallicity evolution through cosmic time along with waveforms and detector sensitivity.',0,['star forma-\ntion history and metallicity evolution through cosmic time','full gravitational radiation wave-\nforms and detector sensitivity noise curves']),('c2','Single-event inference measures redshifted mass and luminosity distance directly, but not redshift.',1,['We therefore\nmeasure redshifted masses','directly measure the\nluminosity distance, but not the redshift']),('c3','GR tests constrain coherent residual strain and check inspiral/post-inspiral consistency, waveform coefficients, and propagation dispersion.',2,['constraining the level of coherent (i.e., GW-\nlike) residual strain','verify that the mass and spin parameters of the final black\nhole','targeted mea-\nsurements of the PN and phenomenological coefficients','search for evidence of\ndispersion'])]
 }
 return [claim(*x,e) for x in specs[code]]
def rebuild_integrative(answer,claims,evidence,category):
 if category=='single_node': return claims
 spans=[]
 for c in claims:
  for s in c['evidence_spans']:
   key=(s['evidence_index'],s['char_start'],s['char_end'])
   if key not in {(x['evidence_index'],x['char_start'],x['char_end']) for x in spans}:spans.append(s)
 claims=[c for c in claims if c.get('claim_id')!='c_integrative']
 claims.append({'claim_id':'c_integrative','claim_text':answer,'claim_type':'integrative_synthesis','supporting_evidence_indices':list(range(len(evidence))),'evidence_spans':spans,'grounding_method':'pr4_semantic_repair_joint_exact_spans'})
 return claims
def main():
 R3.mkdir(parents=True,exist_ok=True)
 source={x['draft_id']:x for x in load(R2/'qa_gold_balanced_20_30_50_r2.jsonl')}
 actions=[];candidates=[];dispositions=[]
 for code in IDS:
  did=f'nodefirst_v2_r1::{code}'; verdict='REVISE' if code in REVISE else 'PASS'
  actions.append({'draft_id':did,'pr4_content_verdict':verdict,'claim_span_fix_required':code in CLAIM_FIX,'join_key':'complete_draft_id','source_gold_id':f'nodefirst_v2_gold_r2::{code}'})
  if code in EXCLUDE:
   dispositions.append({'draft_id':did,'r3_status':'EXCLUDE_RESAMPLE','reason':EXCLUDE[code]});continue
  d=json.loads(json.dumps(source[did]));d['parent_gold_id']=d['gold_id'];d['r3_candidate_id']=f'nodefirst_v2_r3::{code}';d['corpus_snapshot']='nodefirst_qa_v3_20261117';d.pop('gold_id',None);d.pop('independent_review',None);d.pop('final_gate',None)
  if code=='004': d['gold_answer_draft']="Jupiter's tidal forces are believed to cause internal friction that heats the subsurface ocean; a future NASA mission was planned to conduct 45 flybys."
  if code=='029':
   d['question']='How do matched-filter and generic transient searches differ in their waveform assumptions and detection representations?'
   d['gold_answer_draft']='Matched filtering exploits modeled compact-binary waveforms to distinguish signals from the noise background. The generic search uses no specific waveform model and instead identifies coincident excess power in time-frequency representations of detector strain.'
   d['reasoning_type']='method_comparison'
  if code=='012':
   d['question']='Because the low-carbon transition will not happen overnight, what must happen to existing emitting plants, what buffer replacement is expected, and which ML capabilities can support the transition?'
   d['gold_answer_draft']='Emissions from existing CO2-emitting plants must be reduced during the transition. Coal and gas spinning reserve currently provides a buffer, while storage is expected to replace that role. ML can reduce standby-generator emissions and support the carbon-free transition through forecasting, scheduling, control, and electricity-market design for variable supply and flexible demand.'
  if code=='034':
   d['question']="How do DETR's training loss and reinforcement learning's feedback signal differ?"
   d['gold_answer_draft']='DETR uses a permutation-invariant Hungarian loss to match ground-truth and predictions. Reinforcement learning has no supervision; it gathers experience by interacting with the environment and learns from a reward signal.'
   d['reasoning_type']='training_signal_comparison'
  if code in CLAIM_FIX or code in SECOND_PASS_FIX:
   d['answer_claims']=repaired_claims(code,d['gold_evidence_draft'])
  d['answer_claims']=rebuild_integrative(d['gold_answer_draft'],d['answer_claims'],d['gold_evidence_draft'],d['qa_category'])
  deletion=[]
  for i in range(len(d['gold_evidence_draft'])):
   missing=[c['claim_id'] for c in d['answer_claims'] if c.get('supporting_evidence_indices')==[i]]
   deletion.append({'removed_evidence_index':i,'missing_claim_ids':missing,'node_required':bool(missing) or len(d['gold_evidence_draft'])==1,'answer_complete_without_node':False if missing or len(d['gold_evidence_draft'])==1 else None,'outcome':'FAIL_WITHOUT_NODE' if missing or len(d['gold_evidence_draft'])==1 else 'PENDING_INDEPENDENT_REVIEW'})
  d['necessity_test']={'each_gold_node_required':all(x['node_required'] for x in deletion),'single_node_shortcut_found':None,'node_deletion_results':deletion}
  d['pr4_audit_provenance']={'pr_number':4,'head_sha':'11b7f0f6c56385c812bcc7f1a8e78c64a316ff03','manifest_draft_id':did,'content_verdict':verdict,'claim_span_fix_required':code in CLAIM_FIX}
  d['review']={'status':'PENDING_INDEPENDENT_MODEL_REVIEW_R3'}
  candidates.append(d);dispositions.append({'draft_id':did,'r3_status':'CANDIDATE_REPAIRED' if verdict=='REVISE' or code in CLAIM_FIX else 'CANDIDATE_RETAINED'})
  
 allnodes=load(LEG)+load(R2.parent/'nodefirst_qa_v2_20261117_r1/real_canonical_nodes_pilot_r1.jsonl')
 history=[x.get('question','') for x in load(HIST) if x.get('question')]
 duplicates=[];shortcuts=[]
 for d in candidates:
  exact=any(norm(d['question'])==norm(q) for q in history);nearest=max(((jac(d['question'],q),q) for q in history),default=(0,''))
  duplicates.append({'draft_id':d['draft_id'],'executed':True,'status':'FAIL' if exact else 'PASS','normalized_exact_duplicate':exact,'duplicate_pass':not exact,'max_historical_jaccard':round(nearest[0],4),'nearest_historical_question':nearest[1]})
  gold={e['canonical_node_id'] for e in d['gold_evidence_draft']};rank=[]
  for n in allnodes:
   nid=n.get('canonical_node_id');txt=n.get('content_text','')
   if nid not in gold and txt:rank.append((jac(d['gold_answer_draft'],txt),nid,n.get('doc_id') or n.get('document_id'),txt[:240]))
  rank.sort(reverse=True)
  shortcuts.append({'draft_id':d['draft_id'],'executed':True,'status':'NOT_APPLICABLE' if d['qa_category']=='single_node' else 'EXECUTED','single_node_shortcut_found':False if d['qa_category']=='single_node' else None,'automatic_shortcut_block':bool(rank and rank[0][0]>=0.9),'top_lexical_alternative_nodes':[{'score':round(s,4),'canonical_node_id':nid,'document_id':doc,'preview':txt} for s,nid,doc,txt in rank[:5]]})
 claim_audit=[]
 for d in candidates:
  for c in d['answer_claims']:
   exact=all(d['gold_evidence_draft'][s['evidence_index']]['evidence_text'][s['char_start']:s['char_end']]==s['text'] for s in c['evidence_spans'])
   claim_audit.append({'draft_id':d['draft_id'],'claim_id':c['claim_id'],'supporting_evidence_indices':c['supporting_evidence_indices'],'exact_span_count':len(c['evidence_spans']),'all_spans_exact':exact,'pr4_claim_repair_applied':d['draft_id'][-3:] in CLAIM_FIX,'second_pass_repair_applied':d['draft_id'][-3:] in SECOND_PASS_FIX,'semantic_entailment':'PENDING_INDEPENDENT_REVIEW'})
 save(R3/'pr4_audit_actions.jsonl',actions);save(R3/'pr4_disposition_r3.jsonl',dispositions);save(R3/'qa_candidates_r3.jsonl',candidates);save(R3/'claim_span_audit_r3.jsonl',claim_audit);save(R3/'duplicate_audit_r3.jsonl',duplicates);save(R3/'shortcut_search_r3.jsonl',shortcuts)
 summary={'pr4_input_count':len(actions),'pr4_content_verdicts':{'PASS':16,'REVISE':4},'claim_span_fix_required':len(CLAIM_FIX),'r3_candidates':len(candidates),'excluded_resample':len(EXCLUDE),'candidate_categories':{k:sum(x['qa_category']==k for x in candidates) for k in ['single_node','cross_page','cross_document']}}
 (R3/'r3_candidate_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
