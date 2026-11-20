#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117'
def load():
 with (OUT/'qa_drafts.jsonl').open(encoding='utf8') as f: return [json.loads(x) for x in f if x.strip()]
def save(path,rows): path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf8')
REVISE={
9:'Evidence supports transport of crew and supplies, but stimulating spinoffs is a consequence, not a second vehicle role. Rewrite the question or answer.',
17:'The first efficiency node is redundant because the second already states throughput per megawatt and cost per token.',
22:'The excerpts omit the intermediate derivation from artificial-language approximations to a Markov source. Add a bridge node.',
25:'The shared redundancy theme is imposed across separate magazine articles; neither excerpt establishes a common system.',
26:'The parameter-analysis node itself explains the higher SNR. The other document supplies only the exact earlier value, not the core why-answer.',
28:'The GR-test node already describes inspiral/post-inspiral consistency and the quasi-normal mode. The other node is not necessary.',
32:'The properties node alone states time delay plus amplitude/phase consistency. The first document repeats a nonessential component.',
33:'This is a parallel list linked only by the phrase systems architecture; no shared task, metric, or inference makes both necessary.',
35:'Neither source establishes the proposed connection between this inference workload and emitting grid reserves.',
37:'The evidence supports two independent concerns but does not connect token-intensive reasoning to the cited governance risks.',
38:'Both searches changed regimes, but the evidence group is a parallel analogy across unrelated targets rather than a joint inference.',
40:'The mutual-information node already defines information as entropy reduction. The generic entropy excerpt is not required.',
42:'The NIST node gives generic AI risks, not risks demonstrated for low-carbon-grid ML. An application-specific source is required.',
46:'The three documents describe unrelated constraints. New physics is too broad for a necessary joint chain, and the kaon OCR needs image verification.',
47:'The three criteria are reviewer-created; the sources do not define a common measured outcome or say they must be combined.',
48:'The model/compute/governance stack is imposed by the question; no document establishes one deployed vision service.',
49:'The causal-model and governance recommendations are generic and are not tied by evidence to the DLR navigation system.'
}
PASS={
1:'The paragraph explicitly states the oxygen and food need; one unit is sufficient.',
2:'The caption explicitly states the Mars Helicopter objective; nearby OCR noise does not alter the answer.',
3:'One caption contains both the shown area and full-nebula span with units.',
4:'One caption states both the tidal-heating mechanism and the 45-flyby plan.',
5:'The paragraph explicitly identifies the 25th operational year in 2015.',
6:'The caption supports the satellite, acquisition dates, and compositing method.',
7:'The paragraph supports the Earth-benefit pathway, although its wording is broad and promotional.',
8:'The caption explicitly lists S3/S4 and the solar arrays.',
10:'The paragraph explicitly lists hard work, perseverance, and overcoming setbacks.',
11:'One page explains variable supply; the next explains buffering and ML levers. Deleting either loses a requested causal component.',
12:'The first page supplies decarbonization actions and the second supplies the ML balancing role.',
13:'One page supports Hungarian uniqueness and the other the three-part architecture.',
14:'The first node supports global attention and the second permutation invariance plus positional encoding.',
15:'Risk mechanisms and expected organizational gains jointly answer the cause-and-outcome question.',
16:'The first page grounds responsible practice; the later page grounds effectiveness evaluation.',
18:'The redshift relation and event-specific source masses are separate necessary facts.',
19:'One page gives ringdown physics and the other gives the model-averaging decision.',
20:'The pages support a valid comparison between cell-intrinsic damage and systemic inflammaging.',
21:'Each page supports a different intervention class and both are necessary.',
23:'The first page states the diagnostic limitation and the later page the non-causal comparative use.',
24:'Dataset coverage and the Bangladesh percentile form a valid resource-to-claim bridge.',
27:'Detection significance and GR consistency are independent necessary evidential dimensions.',
29:'The documents provide genuinely contrasting modeled and model-independent search strategies.',
30:'Population modeling and event-level redshift interpretation are distinct necessary analysis levels.',
31:'The information limit and concrete energy/noise statistic form a defensible abstraction-to-implementation bridge.',
34:'The sources directly support a meaningful contrast between supervised matching and reward-based learning.',
36:'The company claim and renewable-versus-low-carbon definition are both necessary for the negative conclusion.',
39:'Both concern the Galactic centre: one supports past activity and the other the pulsar-scattering obstacle.',
41:'The sources directly contrast explicit causal blocks with descriptive country regressions.',
43:'Search significance, inferred masses, and GR tests are three distinct necessary validation layers.',
44:'The evidence forms a coherent chain: data quality, empirical significance, then theory consistency.',
45:'Population, event, and gravity-test models answer distinct questions for the same source class.',
50:'Entropy, the data-processing limit, and the ranking statistic form a coherent three-stage conceptual chain.'
}
def main():
 drafts=load(); rows=[]
 for d in drafts:
  n=int(d['draft_id'].split('::')[-1]); legacy=all(e['source_corpus']=='node_vqa_reuse_v1_20261113' for e in d['gold_evidence_draft']); revise=n in REVISE
  status='REVISE' if revise else ('PILOT_ONLY_BLOCKED_CONTENT_PASS' if legacy else 'CONTENT_PASS_MAPPING_PENDING')
  q=n!=9; suff=n not in {35,37,42,47,48,49}; necessary=not revise
  rows.append({'draft_id':d['draft_id'],'status':status,'question_validity':q,'answer_correctness':True,'evidence_sufficiency':suff,'evidence_necessity':necessary,'source_integrity':'PAGE_AND_NODE_TRACEABLE_ORIGINAL_PDF_UNVERIFIED' if legacy else 'PAGE_JSON_TRACEABLE_PDF_PIXEL_CHECK_PENDING','node_mapping':'CANONICAL_ID_PRESENT_BUT_PILOT_ONLY_HYBRID_SHADOW' if legacy else 'PENDING_CANONICAL_MAPPING','duplicate_alternative_evidence':'NOT_EXHAUSTIVELY_SEARCHED','leakage_difficulty':'No evaluated graph edges declared; difficulty may be inflated by parallel-list wording.' if revise else 'No evaluated graph edges declared; relation is evidence-grounded.','each_gold_node_required':necessary,'single_node_shortcut_found':n in {26,28,32,40},'review_notes':REVISE[n] if revise else PASS[n],'reviewer':'independent_review_pass_v1','reviewed_at':'2026-11-17'})
 save(OUT/'qa_independent_reviews.jsonl',rows)
 counts=Counter(x['status'] for x in rows); cross=[x for x in rows if 26<=int(x['draft_id'].split('::')[-1])<=50]; cp=sum(x['each_gold_node_required'] for x in cross); cf=25-cp
 text='# Independent review summary\n\nThis pass reviewed only qa_drafts.jsonl questions, answers, and evidence. It did not use curation pre-review hints. No item is eligible for FINAL_ACCEPT.\n\n## Decisions\n\n'
 text+='\n'.join('- '+k+': '+str(v) for k,v in sorted(counts.items()))+'\n\n## Cross-document necessity result\n\n'
 text+=f'Of 25 cross-document drafts, **{cp} passed** semantic multi-document necessity and **{cf} failed**. The pass rate is {cp/25:.0%}. Four failures (026, 028, 032, 040) have a direct single-document shortcut; the others are loose analogies, generic governance transfer, or author-imposed parallel lists.\n\n'
 text+='## Gate interpretation\n\n- Passing real-periodical items remain CONTENT_PASS_MAPPING_PENDING; page-image/PDF verification and canonical mapping are required.\n- Passing legacy items remain PILOT_ONLY_BLOCKED_CONTENT_PASS because nodes are HYBRID_SHADOW_CANDIDATE and original PDFs are not uniformly verified.\n- Alternative-evidence and semantic duplicate search was not exhaustive, so no item may be exported as verified Gold.\n'
 (OUT/'independent_review_summary.md').write_text(text,encoding='utf8')
if __name__=='__main__': main()
