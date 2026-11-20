#!/usr/bin/env python3
"""Generate conservative QA drafts from frozen snapshot_A seed groups on GPU."""
import json,hashlib,sys,traceback
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'EvidenceNet'))
from evidence_graph.llm_client import create_llm
MODEL=ROOT/'external/models/Qwen3.5-35B-A3B'
SYSTEM="""You generate conservative Node-first QA candidates. Use only supplied evidence. Return JSON only. Never force a relationship. Multi-node items must have one explicit shared comparison dimension, dependency, constraint, or method-to-application bridge. A list of unrelated subquestions is invalid. Every answer claim needs literal source substrings from the correct evidence node. If all nodes are not necessary, return SKIP."""
def loadl(p):return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def writej(p,x):p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8');q.replace(p)
def prompt(seed):
 ev=[{'evidence_index':i,'canonical_node_id':e['canonical_node_id'],'document_id':e['document_id'],'page_id':e['page_id'],'node_type':e['node_type'],'source_corpus':e['source_corpus'],'content_text':e['content_text']} for i,e in enumerate(seed['evidence'])]
 schema={'decision':'GENERATE or SKIP','skip_reason':'required if SKIP','question':'self-contained','answer':'fully grounded','reasoning_type':'specific type','bridge_relation':'explicit shared relation','claims':[{'claim_id':'c1','claim_text':'atomic answer claim','supporting_evidence_indices':[0],'exact_spans':[{'evidence_index':0,'text':'literal source substring'}]}],'node_necessity':[{'evidence_index':0,'missing_claim_ids':['c1'],'why_answer_incomplete_without_node':'...'}]}
 return f"Target category: {seed['target_category']}\nDiscovery hint only (not evidence): {seed.get('shared_terms')}\nRules:\n- single_node uses exactly its one node.\n- cross_page requires both pages of the same document.\n- two_doc requires both documents. three_plus requires every document.\n- Exact spans must jointly entail each claim, not merely share words.\n- Do not claim visual facts unless evidence content explicitly provides them.\n- If the relationship is only an analogy or parallel list, SKIP.\nReturn schema: {json.dumps(schema)}\nEVIDENCE:\n{json.dumps(ev,ensure_ascii=False,indent=2)}"
def normalize(seed,obj,serial):
 if not isinstance(obj,dict) or obj.get('decision')!='GENERATE':return None,str(obj.get('skip_reason','MODEL_SKIP')) if isinstance(obj,dict) else 'INVALID_JSON_OBJECT'
 q=str(obj.get('question','')).strip();a=str(obj.get('answer','')).strip();claims=obj.get('claims',[]);ev=seed['evidence']
 if not q or not a or not isinstance(claims,list) or not claims:return None,'EMPTY_QA_OR_CLAIMS'
 covered=set();outclaims=[]
 for ci,c in enumerate(claims):
  support=c.get('supporting_evidence_indices',[]);spans=[]
  if not support:return None,f'CLAIM_{ci}_NO_SUPPORT'
  for s in c.get('exact_spans',[]):
   ei=s.get('evidence_index');txt=s.get('text')
   if not isinstance(ei,int) or not 0<=ei<len(ev) or not isinstance(txt,str):return None,f'CLAIM_{ci}_BAD_SPAN'
   pos=ev[ei]['content_text'].find(txt)
   if pos<0:return None,f'CLAIM_{ci}_SPAN_NOT_LITERAL'
   spans.append({'evidence_index':ei,'canonical_node_id':ev[ei]['canonical_node_id'],'text':txt,'char_start':pos,'char_end':pos+len(txt)});covered.add(ei)
  if not set(support)<=set(s['evidence_index'] for s in spans):return None,f'CLAIM_{ci}_SUPPORT_WITHOUT_SPAN'
  outclaims.append({'claim_id':str(c.get('claim_id') or f'c{ci+1}'),'claim_text':str(c.get('claim_text','')).strip(),'supporting_evidence_indices':support,'evidence_spans':spans})
 if covered!=set(range(len(ev))):return None,'NOT_ALL_EVIDENCE_COVERED'
 cat=seed['target_category'];docs={e['document_id'] for e in ev};pages={(e['document_id'],e['page_id']) for e in ev}
 if cat=='single_node' and len(ev)!=1:return None,'CATEGORY_MISMATCH'
 if cat=='cross_page' and not(len(docs)==1 and len(pages)>=2):return None,'CATEGORY_MISMATCH'
 if cat=='cross_document_two_doc' and len(docs)!=2:return None,'CATEGORY_MISMATCH'
 if cat=='cross_document_three_plus_doc' and len(docs)<3:return None,'CATEGORY_MISMATCH'
 return {'draft_id':f'scale300_b001::{serial:04d}','seed_id':seed['seed_id'],'snapshot_id':'snapshot_A_20261117_runtime','qa_category':'cross_document' if cat.startswith('cross_document') else cat,'cross_document_subtype':'three_plus_doc' if cat.endswith('three_plus_doc') else ('two_doc' if cat.endswith('two_doc') else None),'question':q,'gold_answer_draft':a,'reasoning_type':str(obj.get('reasoning_type','')),'bridge_relation':str(obj.get('bridge_relation','')),'gold_evidence_draft':[{'evidence_index':i,'canonical_node_id':e['canonical_node_id'],'evidence_unit_id':e['evidence_unit_id'],'document_id':e['document_id'],'page_id':e['page_id'],'page_number':e['page_number'],'node_type':e['node_type'],'evidence_text':e['content_text'],'bbox':e.get('bbox'),'source_json':e.get('source_json'),'page_image':e.get('page_image'),'source_corpus':e['source_corpus']} for i,e in enumerate(ev)],'answer_claims':outclaims,'generator':{'model':str(MODEL),'prompt_path':'scale300_generator_v1','seed_route':seed['discovery_route']},'generation_node_necessity':obj.get('node_necessity',[]),'review':{'status':'PENDING_INDEPENDENT_MODEL_REVIEW'}},None
def main():
 seeds=loadl(OUT/'sampled_seeds.jsonl');cpdir=OUT/'checkpoints/generation';cpdir.mkdir(parents=True,exist_ok=True)
 llm=create_llm({'provider':'transformers','model':str(MODEL),'dtype':'bfloat16','device_map':'auto','require_cuda':True,'enable_thinking':False,'max_new_tokens':1800})
 candidates=[];failed=[];serial=0
 for k,seed in enumerate(seeds,1):
  cp=cpdir/f"{seed['seed_id'].replace('::','_')}.json";request=prompt(seed);finger=hashlib.sha256(request.encode()).hexdigest()
  if cp.exists() and (saved:=json.loads(cp.read_text())).get('input_sha256')==finger:rec=saved
  else:
   try:
    g=llm.generate_json(SYSTEM,request);rec={'input_sha256':finger,'parsed':g.parsed,'raw':g.raw,'model':g.model,'timestamp':g.timestamp}
   except Exception as e:rec={'input_sha256':finger,'error':repr(e),'traceback':traceback.format_exc()}
   writej(cp,rec)
  if 'parsed' not in rec:failed.append({'seed_id':seed['seed_id'],'stage':'generation','reason':'MODEL_ERROR','detail':rec.get('error')});continue
  serial+=1;c,reason=normalize(seed,rec['parsed'],serial)
  if c:candidates.append(c)
  else:failed.append({'seed_id':seed['seed_id'],'stage':'generation','reason':reason})
  if k%10==0:print(json.dumps({'processed':k,'candidates':len(candidates),'failed':len(failed)}),flush=True)
 (OUT/'qa_candidate_drafts_generated.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in candidates),encoding='utf8');(OUT/'failed_generation.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in failed),encoding='utf8')
 writej(OUT/'generation_summary.json',{'attempts':len(seeds),'valid_candidates':len(candidates),'failed_or_skipped':len(failed)})
if __name__=='__main__':main()
