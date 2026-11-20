"""Route canonical dynamic-retrieval nodes to a single text embedding view."""
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path

def rows(path):
    with path.open(encoding="utf-8") as f:
        yield from (json.loads(x) for x in f if x.strip())

def main():
    p=argparse.ArgumentParser(); p.add_argument('--data',type=Path,required=True); p.add_argument('--out',type=Path,required=True); a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False); views=[]; rejected=[]
    for n in rows(a.data/'nodes.jsonl'):
        content=(n.get('content_text') or '').strip(); context=(n.get('context_text') or '').strip(); kind=n['node_type']
        # No generated descriptions are fabricated here.  Pure visual nodes remain
        # explicit unavailable records until a separately logged vision pass exists.
        if not content:
            rejected.append({'node_id':n['node_id'],'node_type':kind,'reason':'no_text_or_verified_visual_description','missing_mask':n['missing_mask']}); continue
        text=f'[{kind}]\n{content}'
        if context: text=f'[DOCUMENT_CONTEXT]\n{context}\n[CONTENT]\n{text}'
        views.append({'node_id':n['node_id'],'document_id':n['document_id'],'page_id':n['page_id'],'page_number':n['page_number'],'node_type':kind,'retrieval_text':text,'content_text':content,'context_text':context,'representation_sha256':hashlib.sha256(text.encode()).hexdigest(),'view_kind':'dynamic_v1_text_context'})
    views.sort(key=lambda x:x['node_id'])
    with (a.out/'retrieval_views.jsonl').open('w',encoding='utf-8') as f:
        for x in views:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n')
    with (a.out/'embedding_ids.jsonl').open('w',encoding='utf-8') as f:
        for i,x in enumerate(views):f.write(json.dumps({'embedding_row':i,'node_id':x['node_id'],'view_id':x['node_id']+'::dynamic_v1_text_context'},sort_keys=True)+'\n')
    with (a.out/'rejected_nodes.jsonl').open('w',encoding='utf-8') as f:
        for x in rejected:f.write(json.dumps(x,sort_keys=True)+'\n')
    summary={'input_nodes':len(views)+len(rejected),'routable_views':len(views),'rejected':len(rejected),'rejected_by_reason':dict(Counter(x['reason'] for x in rejected)), 'protocol':'TEXT/TABLE/CAPTION/IMAGE with verified HTML text use [DOCUMENT_CONTEXT]+[CONTENT]; pure visual nodes remain explicit unavailable; no old vectors reused'}
    (a.out/'representation_manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8'); print(json.dumps(summary))
if __name__=='__main__':main()
