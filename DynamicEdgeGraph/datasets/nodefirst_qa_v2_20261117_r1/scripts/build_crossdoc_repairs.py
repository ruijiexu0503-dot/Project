#!/usr/bin/env python3
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
OLD=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117'
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1'

PASS={27,29,30,31,34,36,39,41,43,44,45,50}
REPAIRS={
26:{
 'cause':'DIRECT_SINGLE_DOCUMENT_SHORTCUT: the parameter-analysis node already gives the causal explanation.',
 'question':'What SNR did the initial GW150914 search report, what optimal coherent SNR did the later parameter analysis obtain, and why was the latter higher?',
 'answer':'The initial search reported an SNR of about 24. The parameter analysis obtained 25.1 (+/-1.7) because it sampled a larger parameter space more finely.',
 'rationale':'Deleting the search node loses the initial numerical value 24; deleting the parameter node loses 25.1 and the sampling explanation.'
},
28:{
 'cause':'DIRECT_SINGLE_DOCUMENT_SHORTCUT: the GR-test node already describes the consistency test and QNM.',
 'question':'Which final-black-hole quantities determine ringdown frequency and decay time, and how did the GW150914 analysis test their consistency across inspiral and post-inspiral data?',
 'answer':'The final black hole’s mass and spin determine ringdown frequency and decay time. The analysis compared mass and spin predicted from the inspiral with post-inspiral estimates and checked the post-peak signal against the least-damped quasi-normal mode.',
 'rationale':'Deleting the properties node loses the physical mapping from final mass/spin to frequency/decay time; deleting the GR-test node loses the actual cross-phase test.'
},
32:{
 'cause':'DIRECT_SINGLE_DOCUMENT_SHORTCUT: the properties node alone states timing plus amplitude/phase localization.',
 'question':'In coherent gravitational-wave localization, what defines the reconstructed sky position, and what cross-site observations constrain GW150914 to a ring and help resolve its geometry?',
 'answer':'The reconstructed sky position is the maximum of a likelihood statistic over sky coordinates. For GW150914, the observed time delay constrains a ring, while amplitude and phase consistency between sites helps resolve the source geometry.',
 'rationale':'Deleting the coherent-statistics node loses the maximum-likelihood definition; deleting the properties node loses the ring and amplitude/phase constraints.'
},
38:{
 'cause':'LOOSE_ANALOGY: the original wording did not state a common comparison axis.',
 'question':'For the monopole search and the Galactic-centre pulsar survey, which physical effect made the standard detection regime unsuitable, and what replacement strategy was used in each case?',
 'answer':'Highly ionizing monopoles lose energy before reaching the calorimeter, so the search used forward-neutron and pixel-cluster triggers. Ionized gas time-broadens pulsar pulses at standard radio frequencies, so the survey observed at 8–12 GHz where scattering is weaker.',
 'rationale':'Each document is necessary for one explicitly comparable failure-mechanism/mitigation pair; neither document can answer the other search case.'
}
}
REJECT={
33:'No evidence links model architecture and datacenter architecture through a shared task, metric, or causal relation; parallel component lists are insufficient.',
35:'Neither source establishes a causal link between inference throughput per megawatt and spinning-reserve emissions.',
37:'The governance node is generic and does not establish risks specific to token-intensive reasoning models.',
40:'The mutual-information node already defines entropy reduction, so the generic entropy node is redundant.',
42:'The NIST node gives generic AI risks, not risks demonstrated for ML-controlled low-carbon grids.',
46:'Bell tests, monopole limits, and kaon measurements share only the overly broad label “new physics”; no joint inference requires all three.',
47:'The three evaluation dimensions are imposed by the author; the sources define no shared measured outcome.',
48:'The model/compute/governance stack is author-imposed and not established as one deployed service by the sources.',
49:'The causal-modeling and governance nodes are generic and not tied to the DLR navigation system.'
}

def rows(path):
 with path.open(encoding='utf8') as f:
  return [json.loads(x) for x in f if x.strip()]
def save(path,data):
 path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data),encoding='utf8')

def main():
 drafts={int(x['draft_id'].split('::')[-1]):x for x in rows(OLD/'qa_drafts.jsonl') if int(x['draft_id'].split('::')[-1])>=26}
 reviews={int(x['draft_id'].split('::')[-1]):x for x in rows(OLD/'qa_independent_reviews.jsonl') if int(x['draft_id'].split('::')[-1])>=26}
 audit=[]; candidates=[]
 for n in range(26,51):
  d=drafts[n]; evidence_ids=[e['canonical_node_id'] for e in d['gold_evidence_draft']]
  if n in PASS:
   action='RETAIN_PASS'; proposed='READY_FOR_AUTOMATED_GATES'; cause=None
   q=d['question']; a=d['gold_answer_draft']; rationale=reviews[n]['review_notes']
  elif n in REPAIRS:
   action='REWRITE_AND_RETEST'; proposed='READY_FOR_INDEPENDENT_MODEL_REVIEW'; cause=REPAIRS[n]['cause']
   q=REPAIRS[n]['question']; a=REPAIRS[n]['answer']; rationale=REPAIRS[n]['rationale']
  else:
   action='REJECT_CURRENT_EVIDENCE_GROUP'; proposed='REJECT'; cause=REJECT[n]
   q=None; a=None; rationale='No strict repair is supported by the current evidence group; resample companions rather than force a cross-document question.'
  audit.append({
   'original_draft_id':d['draft_id'],'original_necessity_pass':reviews[n]['each_gold_node_required'],
   'original_single_node_shortcut':reviews[n]['single_node_shortcut_found'],
   'failure_cause':cause,'action':action,'proposed_status':proposed,
   'repaired_question':q if action=='REWRITE_AND_RETEST' else None,
   'repaired_answer':a if action=='REWRITE_AND_RETEST' else None,
   'evidence_node_ids':evidence_ids,'ablation_rationale':rationale
  })
  if action!='REJECT_CURRENT_EVIDENCE_GROUP':
   x=dict(d); x['draft_id']=d['draft_id'].replace('nodefirst_v2_pilot','nodefirst_v2_r1')
   x['parent_draft_id']=d['draft_id']; x['corpus_snapshot']='nodefirst_qa_v2_20261117_r1'
   x['question']=q; x['gold_answer_draft']=a
   x['necessity_test']={'each_gold_node_required':True,'single_node_shortcut_found':False,'alternative_gold_sets':[],'notes':rationale}
   x['review']={'status':'PENDING_INDEPENDENT_MODEL_REVIEW' if action=='REWRITE_AND_RETEST' else 'PENDING_REVISED_AUTOMATED_GATES'}
   x['repair_action']=action; candidates.append(x)
 save(OUT/'crossdoc_repair_analysis.jsonl',audit)
 save(OUT/'qa_crossdoc_repaired_candidates.jsonl',candidates)
 summary={
  'cross_document_original':25,'original_necessity_pass':len(PASS),
  'repairable_shortcut_or_relation_failures':len(REPAIRS),
  'rejected_current_evidence_groups':len(REJECT),
  'candidate_after_repair':len(candidates),
  'candidate_pass_rate_before_independent_r1_review':len(candidates)/25,
  'direct_shortcut_repairs':[f'nodefirst_v2_pilot::{n:03d}' for n in (26,28,32)],
  'relation_axis_repair':['nodefirst_v2_pilot::038'],
  'strictly_rejected':[f'nodefirst_v2_pilot::{n:03d}' for n in sorted(REJECT)]
 }
 (OUT/'crossdoc_repair_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
if __name__=='__main__': main()
