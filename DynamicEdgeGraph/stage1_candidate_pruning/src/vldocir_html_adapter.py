"""Build traceable canonical Nodes from fixed VL-DocIR HTML element metadata."""
from __future__ import annotations
import argparse,json,re,time
from collections import Counter
from pathlib import Path
from .common import write_jsonl,sha256

TEXT={'p','h1','h2','h3','h4','li','blockquote','pre','dd','dt'}; TABLE={'table','tr','td','th'}
def kind(item):
 tag=str(item.get('tag','')).lower(); text=str(item.get('text_sample','')).strip()
 if tag in TABLE:return 'TABLE'
 if tag=='figcaption':return 'CAPTION'
 if tag in {'figure','img','svg','canvas'}:return 'IMAGE'
 if tag in {'math','mjx-container'} or re.search(r'\\(?:frac|sum|int|alpha|beta|mathbf)\b|\$\$',text):return 'FORMULA'
 return 'TEXT' if tag in TEXT else 'OTHER'
def decorative(item):
 text=str(item.get('text_sample','')).lower();tag=str(item.get('tag','')).lower()
 return tag=='img' and any(x in text for x in ('wikipedia.png','wordmark','tagline','logo','favicon','icon'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--dataset-root',required=True);p.add_argument('--output',required=True);p.add_argument('--max-docs-per-source',type=int);a=p.parse_args();root=Path(a.dataset_root);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 docs=[json.loads(x) for x in (root/'documents.jsonl').open() if x.strip()];selected=[];used=Counter()
 for d in sorted(docs,key=lambda x:(x['data_source'],x['document_id'])):
  if a.max_docs_per_source is not None and used[d['data_source']]>=a.max_docs_per_source:continue
  selected.append(d);used[d['data_source']]+=1
 nodes=[];audit=[]
 for d in selected:
  did=d['document_id'];mp=root/'document_texts'/did/f'{did}_html_elements_metadata.json';hp=root/'document_texts'/did/f'{did}.html';meta=json.loads(mp.read_text());items=meta.get('items',[]);created=0;excluded=0
  for item in items:
   text=str(item.get('text_sample','')).strip();pages=item.get('pages') or []
   if not pages:continue
   typ=kind(item);reason=None
   if decorative(item):reason='decorative_logo_or_brand_asset'
   elif not text:reason='empty_element_content'
   elif typ=='OTHER':reason='unsupported_html_element_type'
   for page in pages:
    nid=f'vldocir::{did}::p{int(page):04d}::{item.get("id")}'
    if reason:
     audit.append({'node_id':nid,'document_id':did,'page_number':page,'node_type':typ,'eligibility':'EXCLUDED','reason':reason});excluded+=1;continue
    nodes.append({'id':nid,'document_id':did,'page_number':int(page),'data_source':d['data_source'],'title':d.get('title'),'node_type':typ,'status':'CANONICAL_HTML_ELEMENT','text':text,'members':[{'id':str(item.get('id')),'kind':typ.lower(),'text':text,'bbox':item.get('bbox_orig',item.get('bbox'))}],'source_revision':'VL-DocIR-RepresentativeSubset','source_html':str(hp.relative_to(root)),'source_metadata':str(mp.relative_to(root)),'html_element_id':item.get('id'),'html_tag':item.get('tag')});audit.append({'node_id':nid,'document_id':did,'page_number':page,'node_type':typ,'eligibility':'ELIGIBLE','reason':None});created+=1
  audit.append({'document_id':did,'record_type':'document_integrity','data_source':d['data_source'],'title':d.get('title'),'declared_page_count':d['page_count'],'metadata_page_count':len({p for i in items for p in (i.get('pages') or [])}),'html_exists':hp.exists(),'metadata_exists':mp.exists(),'page_tar_exists':(root/'pages'/f'{did}.tar').exists(),'created_nodes':created,'excluded_elements':excluded})
 write_jsonl(out/'canonical_nodes.jsonl',nodes);write_jsonl(out/'node_eligibility_audit.jsonl',audit);write_jsonl(out/'documents_manifest.jsonl',selected)
 summary={'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'documents':len(selected),'pages_declared':sum(x['page_count'] for x in selected),'nodes':len(nodes),'node_types':dict(Counter(x['node_type'] for x in nodes)),'sources':dict(Counter(x['data_source'] for x in selected)),'source_documents_sha256':sha256(root/'documents.jsonl'),'adapter':'fixed HTML metadata; no query inputs; no token-count eligibility gate'}
 (out/'adapter_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True));print(json.dumps(summary,sort_keys=True))
if __name__=='__main__':main()
