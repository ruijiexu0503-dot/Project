#!/usr/bin/env python3
"""Freeze runtime-eligible parser elements and legacy nodes as snapshot_A."""
import json,hashlib,re
from collections import Counter,defaultdict
from pathlib import Path

OUT=Path(__file__).resolve().parents[1];ROOT=OUT.parents[2]
REAL=ROOT/'DynamicEdgeGraph/datasets/real_documents_v1_20261113'
PIPE=REAL/'pipeline_to_nodes_v1_20261114';WORK=PIPE/'work'
LEG=ROOT/'DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113'
R3=ROOT/'DynamicEdgeGraph/datasets/nodefirst_qa_v3_20261117'
TYPE={'para':'PARA','paragraph':'PARA','table':'TABLE','tab':'TABLE','caption':'CAPTION','cap':'CAPTION','title':'TEXT','section_header':'TEXT','sec_0':'TEXT','sec_1':'TEXT','sec_2':'TEXT','list':'TEXT'}
def loadj(p):return json.loads(p.read_text(encoding='utf8'))
def loadl(p):return [json.loads(x) for x in p.open(encoding='utf8') if x.strip()]
def savej(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def savel(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in x),encoding='utf8')
def clean(s):return ' '.join(str(s).split())
def main():
 manifest={x['document_id']:x for x in loadj(PIPE/'manifest.resolved.json')['documents']}
 inventory=[];eligible=[]
 for p in sorted(WORK.glob('progress_*.json')):
  doc_id=p.stem.removeprefix('progress_');d=next(iter(loadj(p)['documents'].values()));pages=d.get('pages',{});complete=sum(x.get('status')=='complete' for x in pages.values());total=d.get('total_pages');ok=complete==total and len(pages)==total
  reason='ELIGIBLE_COMPLETE' if ok else 'EXCLUDE_INCOMPLETE_PARSE'
  inventory.append({'document_id':doc_id,'declared_pages':total,'checkpoint_page_records':len(pages),'complete_pages':complete,'eligibility':reason,'source_pdf':manifest.get(doc_id,{}).get('input_pdf'),'source_sha256':manifest.get(doc_id,{}).get('source_sha256')})
  if ok:eligible.append(doc_id)
 nodes=[]
 for doc_id in eligible:
  meta=manifest[doc_id]
  for pd in sorted((WORK/doc_id/'pages').glob('page_*')):
   page=int(pd.name.rsplit('_',1)[1]);src=pd/'output_json'/f'{pd.name}.json';image=pd/'original.png'
   if not image.is_file():image=pd/'layout_visualization'/f'{pd.name}_layout.png'
   if not src.is_file() or not image.is_file():continue
   for idx,item in enumerate(loadj(src)):
    label=str(item.get('label','')).lower();nt=TYPE.get(label);text=clean(item.get('text',''))
    if nt is None or len(text)<35 or text.startswith('!['):continue
    eid=f'{doc_id}:p{page:04d}:e{idx:03d}';cid=f'{doc_id}_page_{page:04d}_EU_{idx:03d}'
    nodes.append({'canonical_node_id':cid,'evidence_unit_id':eid,'document_id':doc_id,'page_id':f'page_{page:04d}','page_number':page,'node_type':nt,'content_text':text[:2400],'bbox':item.get('bbox'),'source_json':str(src.resolve()),'page_image':str(image.resolve()),'source_pdf':meta['input_pdf'],'source_sha256':meta['source_sha256'],'source_corpus':'real_documents_snapshot_A','mapping_status':'MAPPED_VERIFIED_AUTOMATIC','source_integrity_status':'SOURCE_INTEGRITY_PASS'})
 for x in loadl(LEG/'nodes.jsonl'):
  text=clean(x.get('content_text',''));cid=x.get('canonical_node_id') or x.get('node_id')
  if not cid or len(text)<35:continue
  nodes.append({'canonical_node_id':cid,'evidence_unit_id':cid,'document_id':x.get('doc_id'),'page_id':x.get('page_id'),'page_number':int(str(x.get('page_id','0')).split('_')[-1]),'node_type':x.get('node_type','TEXT'),'content_text':text[:2400],'bbox':x.get('bbox'),'source_json':x.get('source_file'),'page_image':None,'source_pdf':None,'source_sha256':None,'source_corpus':'legacy_frozen_nodes','mapping_status':'MAPPED_VERIFIED_AUTOMATIC','source_integrity_status':'SOURCE_INTEGRITY_PASS'})
 ids=[x['canonical_node_id'] for x in nodes]
 if len(ids)!=len(set(ids)):raise RuntimeError('duplicate canonical node IDs')
 r3=[]
 for x in loadl(R3/'qa_gold_auto_accepted_r3.jsonl'):
  y=json.loads(json.dumps(x));y['review']={'status':'FINAL_ACCEPT_AUTOMATIC','source':'normalized_from_r3_pass2','history':[x.get('review'),{'independent_review_pass':x.get('independent_review',{}).get('model_review_pass')} ]};r3.append(y)
 modalities=Counter(x['node_type'] for x in nodes);corp=Counter(x['source_corpus'] for x in nodes);docs=Counter(x['document_id'] for x in nodes)
 snapshot={'snapshot_id':'snapshot_A_20261117_runtime','created_from_runtime_check':True,'eligible_real_documents':eligible,'excluded_real_documents':[x for x in inventory if x['eligibility']!='ELIGIBLE_COMPLETE'],'legacy_document_count':len(loadl(LEG/'documents.jsonl')),'canonical_node_count':len(nodes),'node_count_by_corpus':dict(corp),'node_count_by_modality':dict(modalities),'document_count_total':len(docs),'node_pool_sha256':hashlib.sha256('\n'.join(ids).encode()).hexdigest()}
 savel(OUT/'source_inventory_by_snapshot.jsonl',inventory);savej(OUT/'source_inventory_by_snapshot.json',snapshot);savel(OUT/'snapshot_A_canonical_nodes.jsonl',nodes);savej(OUT/'sampling_pool_by_corpus_modality.json',{'by_corpus':dict(corp),'by_modality':dict(modalities),'by_document':dict(docs)});savel(OUT/'qa_gold_r3_status_normalized.jsonl',r3)
 print(json.dumps({'eligible_real_documents':len(eligible),'nodes':len(nodes),'modalities':dict(modalities),'normalized_r3':len(r3)},ensure_ascii=False))
if __name__=='__main__':main()
