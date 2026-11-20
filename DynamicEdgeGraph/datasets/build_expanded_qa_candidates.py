#!/usr/bin/env python3
"""Create extra, source-bound review candidates from unused parsed passages."""
import json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEWROOT = ROOT / 'real_documents_v1_20261113/pipeline_to_nodes_v1_20261114'
OLDROOT = ROOT / 'node_vqa_reuse_v1_20261113'
OUT = ROOT / 'qa_expansion_candidates_v1'

def read(path): return [json.loads(x) for x in path.read_text().splitlines() if x]
def words(s): return re.findall(r'[A-Za-z]{3,}', s.lower())
def score(s):
    w=words(s)
    return min(len(w), 260)+len(set(w))*.6-abs(len(s)-900)*.035
def question(title):
    return f'What causal, technical, or comparative relationship does the selected passage establish in {title}, and what stated condition or consequence qualifies it?'

def new_records():
    manual=read(NEWROOT/'qa_review_drafts_v1/qa_drafts.jsonl')
    used=defaultdict(set)
    for r in manual:
        used[r['document_id']].update(e['page_number'] for e in r['gold_evidence_draft'])
    manifest=json.loads((NEWROOT/'manifest.resolved.json').read_text())['documents']
    out=[]
    for doc in manifest:
        did,title=doc['document_id'],did if False else doc['document_id']
        candidates=[]
        for fp in sorted((NEWROOT/'work'/did/'pages').glob('page_*/output_json/page_*.json')):
            page=int(fp.stem.split('_')[-1])
            if page in used[did]: continue
            for idx,row in enumerate(json.loads(fp.read_text())):
                text=' '.join(str(row.get('text','')).split())
                if len(text)>=260: candidates.append((score(text),page,idx,row,text,fp))
        # Force different portions of a magazine, then best passage in each.
        candidates.sort(reverse=True,key=lambda x:x[0]); chosen=[]
        for bucket in (0,1):
            pool=[x for x in candidates if (x[1]%2)==bucket and x[1] not in {z[1] for z in chosen}] or candidates
            if pool: chosen.append(max(pool,key=lambda x:x[0]))
        for n,(_,page,idx,row,text,fp) in enumerate(chosen,1):
            out.append({'draft_id':f'auto_new_expansion::{did}::{n}', 'review_status':'NEEDS_HUMAN_REVIEW','corpus':'real_documents_v1_20261113','document_id':did,'source_pdf':doc['input_pdf'],'question':question(did),'gold_answer_draft':text,'gold_evidence_draft':[{'evidence_unit_id':f'{did}:p{page:04d}:e{idx:03d}','document_id':did,'page_number':page,'element_index':idx,'element_type':row.get('label'),'bbox':row.get('bbox'),'text':text,'source_json':str(fp.resolve()),'future_node_mapping':'pending_evidence_node_assembly'}],'difficulty':'review_candidate','question_design':'auto_source_bound_expansion','question_type_actual':'single_evidence','uses_gold_annotations':False,'node_mapping_status':'PENDING_EVIDENCE_NODE_ASSEMBLY','reviewer_decision':None,'reviewer_notes':None})
    return out

def old_records():
    old=read(OLDROOT/'qa_review_drafts_v1/qa_drafts.jsonl'); used={r['gold_evidence_draft'][0]['evidence_unit_id'] for r in old}
    docs={r['doc_id']:r for r in read(OLDROOT/'documents.jsonl')}; pages={(r['doc_id'],r['page_id']):r.get('image_path') for r in read(OLDROOT/'pages.jsonl')}
    by=defaultdict(list)
    for n in read(OLDROOT/'nodes.jsonl'):
        text=' '.join(n.get('content_text','').split())
        if n['node_id'] not in used and len(text)>=220: by[n['doc_id']].append((score(text),n,text))
    out=[]
    for did,doc in docs.items():
        cand=sorted(by[did],reverse=True,key=lambda x:x[0]); chosen=[]
        for item in cand:
            if item[1]['page_id'] not in {z[1]['page_id'] for z in chosen}: chosen.append(item)
            if len(chosen)==2: break
        for i,(_,n,text) in enumerate(chosen,1):
            out.append({'draft_id':f'auto_legacy_expansion::{did}::{i}','review_status':'NEEDS_HUMAN_REVIEW','corpus':'node_vqa_reuse_v1_20261113','document_id':did,'document_title':doc['title'],'question':question(doc['title']),'gold_answer_draft':text,'gold_evidence_draft':[{'evidence_unit_id':n['node_id'],'document_id':did,'page_id':n['page_id'],'element_type':n['node_type'],'bbox':n['bbox'],'text':text,'source_page_image':pages.get((did,n['page_id'])),'source_node_file':n['source_file'],'source_atom_ids':n['source_atom_ids'],'future_node_mapping':'already_bound_to_legacy_node'}],'difficulty':'review_candidate','question_design':'auto_source_bound_expansion','question_type_actual':'single_evidence','uses_gold_annotations':False,'node_mapping_status':'BOUND_TO_EXISTING_LEGACY_NODE','reviewer_decision':None,'reviewer_notes':None})
    return out

def main():
    rows=new_records()+old_records(); OUT.mkdir(exist_ok=True)
    (OUT/'qa_expansion_candidates.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
    (OUT/'summary.json').write_text(json.dumps({'additional_candidates':len(rows),'new_corpus':sum(x['corpus'].startswith('real') for x in rows),'legacy_corpus':sum(x['corpus'].startswith('node') for x in rows),'note':'Automatically selected unused source passages; human review/rewrite required.'},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__': main()
