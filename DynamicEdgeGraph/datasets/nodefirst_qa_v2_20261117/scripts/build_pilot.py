#!/usr/bin/env python3
import hashlib,json,re
from collections import Counter
from pathlib import Path
R=Path(__file__).resolve().parents[4]; O=R/'DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117'; L=R/'DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113'; W=R/'DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work'; EL=R/'DynamicEdgeGraph/datasets/annotation_eligibility_v1_20261117.json'; SEED=20261117
def jl(p):
 with p.open(encoding='utf8') as f:
  for s in f:
   if s.strip(): yield json.loads(s)
def dumpl(p,x): p.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in x),encoding='utf8')
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def cases():
 out=[]
 for s in (O/'pilot_cases.tsv').read_text(encoding='utf8').splitlines():
  if not s or s.startswith('#'): continue
  cat,sub,typ,q,a,refs,hint=s.split('\t'); out.append({'cat':cat,'sub':sub or None,'typ':typ,'q':q,'a':a,'refs':refs.split(','),'hint':hint})
 return out
def main():
 eligibility=json.loads(EL.read_text()); nodes={x['canonical_node_id']:x for x in jl(L/'nodes.jsonl')}; pages={(x['doc_id'],x['page_id']):x for x in jl(L/'pages.jsonl')}; docs=list(jl(L/'documents.jsonl')); C=cases()
 estate=Counter(x['eligibility_status'] for x in eligibility['qa_eligibility']); realstate=Counter(x['annotation_status'] for x in eligibility['real_documents']); ns=list(nodes.values()); eligible_nodes=[n for n in ns if len(n.get('content_text','').strip())>=40 and n.get('node_type') in {'TEXT','TABLE','CAPTION','COMPOSITE'}]
 inv={'snapshot':'2026-11-17','eligibility_manifest':str(EL),'sampling_seed':SEED,'eligibility_counts':dict(estate),'real_document_status_counts':dict(realstate),'legacy':{'documents':len(docs),'pages':len(pages),'nodes':len(ns),'canonical_non_null':sum(bool(n.get('canonical_node_id')) for n in ns),'canonical_unique':len(nodes),'node_statuses':dict(Counter(n.get('status') for n in ns)),'node_types':dict(Counter(n.get('node_type') for n in ns)),'heuristic_eligible':len(eligible_nodes),'eligibility':'PILOT_ONLY_BLOCKED','warning':'Original PDFs are not uniformly verified; all nodes remain HYBRID_SHADOW_CANDIDATE.'},'real':{'eligible_review_pending_mapping':sum(x['annotation_status']=='ELIGIBLE_FOR_REVIEW_PENDING_NODE_MAPPING' for x in eligibility['real_documents']),'excluded_or_parked':[x['document_id'] for x in eligibility['real_documents'] if x['annotation_status']!='ELIGIBLE_FOR_REVIEW_PENDING_NODE_MAPPING'],'canonical_node_mapping':'ABSENT','benchmark_status':'NOT_GOLD_PENDING_CANONICAL_NODE_MAPPING'},'historical_qa_usage':'Dedup and QC only; historical questions/answers are not read by this builder.'}; dump(O/'source_inventory.json',inv)
 drafts=[]; maps=[]; unresolved=[]; seeds=[]; groups=[]
 for k,c in enumerate(C,1):
  did=f'nodefirst_v2_pilot::{k:03d}'; ev=[]
  for i,r in enumerate(c['refs']):
   if '|' in r:
    doc,p,e=r.split('|'); p=int(p); e=int(e); sj=W/doc/'pages'/f'page_{p:04d}'/'output_json'/f'page_{p:04d}.json'; x=json.loads(sj.read_text())[e]; eid=f'{doc}:p{p:04d}:e{e:03d}'; z={'source_corpus':'real_documents_v1_20261113','document_id':doc,'page_number':p,'page_id':f'page_{p:04d}','evidence_unit_id':eid,'canonical_node_id':None,'node_mapping_status':'PENDING_MAPPING','source_json':str(sj),'page_image':str(sj.parents[1]/f'page_{p:04d}.png'),'bbox':x.get('bbox'),'node_type':x.get('label','UNKNOWN').upper(),'evidence_text':x.get('text','')}; unresolved.append({'draft_id':did,'evidence_unit_id':eid,'issue':'No canonical mapping for eligible real-periodical evidence.','required_action':'Assemble frozen canonical nodes and verify evidence-unit mapping.'})
   else:
    n=nodes[r]; pg=pages[(n['doc_id'],n['page_id'])]; z={'source_corpus':'node_vqa_reuse_v1_20261113','document_id':n['doc_id'],'page_number':int(re.search(r'(\d+)$',n['page_id']).group(1)),'page_id':n['page_id'],'evidence_unit_id':n['node_id'],'canonical_node_id':n['canonical_node_id'],'node_mapping_status':'PILOT_ONLY_ID_PRESENT_SOURCE_PDF_UNVERIFIED','source_json':n.get('source_file'),'page_image':pg.get('image_path'),'bbox':n.get('bbox'),'node_type':n.get('node_type'),'evidence_text':n.get('content_text','')}
   z['support_claim_ids']=[f'c{i+1}']; z['necessity_reason']=f'Supports answer component c{i+1}; deletion removes that requested component.'; ev.append(z); maps.append({'draft_id':did,'evidence_unit_id':z['evidence_unit_id'],'canonical_node_id':z['canonical_node_id'],'mapping_status':z['node_mapping_status'],'reference_exists':True,'source_integrity_verified':False})
  ds=sorted({x['document_id'] for x in ev}); seed={'source_corpus':ev[0]['source_corpus'],'evidence_unit_id':ev[0]['evidence_unit_id'],'canonical_node_id':ev[0]['canonical_node_id'],'sampling_stratum':f"{c['cat']}::{ev[0]['node_type']}",'sampling_seed':SEED}; d={'draft_id':did,'corpus_snapshot':'nodefirst_qa_v2_20261117_pilot_v1','qa_category':c['cat'],'cross_document_subtype':c['sub'],'reasoning_type':c['typ'],'question':c['q'],'gold_answer_draft':c['a'],'seed':seed,'gold_evidence_draft':ev,'answer_claims':[{'claim_id':f'c{i+1}','claim_text':f'Answer component {i+1}','supporting_evidence_indices':[i]} for i in range(len(ev))],'candidate_discovery':{'methods':['deterministic_seed','lexical','metadata','curator_relation_check'],'graph_edges_used_for_gold_selection':False},'necessity_test':{'each_gold_node_required':None,'single_node_shortcut_found':None,'alternative_gold_sets':[],'notes':'Reserved for independent review.'},'provenance':{'historical_question_or_answer_used':False,'document_ids':ds,'pre_review_hint':c['hint']},'review':{'status':'UNREVIEWED'}}; drafts.append(d); seeds.append({'draft_id':did,**seed})
  if c['cat']!='single_node': groups.append({'draft_id':did,'evidence_ids':[x['evidence_unit_id'] for x in ev],'document_ids':ds,'relation':c['typ'],'discovery_methods':d['candidate_discovery']['methods']})
 dumpl(O/'qa_drafts.jsonl',drafts); dumpl(O/'sampled_seeds.jsonl',seeds); dumpl(O/'evidence_group_candidates.jsonl',groups); dumpl(O/'mapping_audit.jsonl',maps); dumpl(O/'unresolved_evidence_mapping.jsonl',unresolved); dumpl(O/'qa_gold_verified.jsonl',[]); dumpl(O/'alternative_gold_sets.jsonl',[])
 v={'draft_count':len(drafts),'unique_ids':len({x['draft_id'] for x in drafts}),'category_counts':dict(Counter(x['qa_category'] for x in drafts)),'cross_document_subtypes':dict(Counter(x['cross_document_subtype'] for x in drafts if x['qa_category']=='cross_document')),'all_references_resolved':all(x['reference_exists'] for x in maps),'mapping_counts':dict(Counter(x['mapping_status'] for x in maps)),'gold_export_count':0,'sha256':{}}
 for n in ['qa_drafts.jsonl','sampled_seeds.jsonl','evidence_group_candidates.jsonl','mapping_audit.jsonl','unresolved_evidence_mapping.jsonl']: v['sha256'][n]=hashlib.sha256((O/n).read_bytes()).hexdigest()
 dump(O/'validation_report.json',v)
if __name__=='__main__': main()
