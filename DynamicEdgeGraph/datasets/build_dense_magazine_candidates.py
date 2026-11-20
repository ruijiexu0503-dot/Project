#!/usr/bin/env python3
"""Densely cover a completed long-form magazine with auditable QA candidates."""
import json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PIPE=ROOT/'real_documents_v1_20261113/pipeline_to_nodes_v1_20261114'
EXP=ROOT/'qa_expansion_candidates_v1/qa_expansion_candidates.jsonl'
MANUAL=PIPE/'qa_review_drafts_v1/qa_drafts.jsonl'
OUT=ROOT/'dense_magazine_candidates_v1'
DOC='real_016_batch_16_basic_version_07'; TARGET=120

def read(p): return [json.loads(x) for x in p.read_text().splitlines() if x]
def words(s): return re.findall(r'[A-Za-z]{3,}',s.lower())
def quality(s):
    w=words(s)
    return min(len(w),260)+.5*len(set(w))-abs(len(s)-800)*.025
def main():
    existing=[r for r in read(MANUAL)+read(EXP) if r['document_id']==DOC]
    used={(e.get('page_number'),e.get('element_index')) for r in existing for e in r['gold_evidence_draft']}
    manifest={d['document_id']:d for d in json.loads((PIPE/'manifest.resolved.json').read_text())['documents']}
    candidates=[]
    for fp in sorted((PIPE/'work'/DOC/'pages').glob('page_*/output_json/page_*.json')):
        page=int(fp.stem.split('_')[-1]); rows=json.loads(fp.read_text()); heading='this article'
        for idx,row in enumerate(rows):
            txt=' '.join(str(row.get('text','')).split())
            if row.get('label') in {'title','heading'} and 8<len(txt)<180: heading=txt
            if (page,idx) in used or len(txt)<220: continue
            candidates.append((quality(txt),page,idx,row,txt,heading,fp))
    # One high-information passage per page first; this maximizes article/page coverage.
    bypage={}
    for item in candidates:
        if item[1] not in bypage or item[0]>bypage[item[1]][0]: bypage[item[1]]=item
    pool=sorted(bypage.values(),key=lambda x:x[1]); need=max(0,TARGET-len(existing))
    # Even spacing keeps the 172-page issue covered end-to-end instead of
    # consuming only its opening sections.
    selected=[pool[round(i*(len(pool)-1)/(need-1))] for i in range(need)] if need>1 else pool[:need]
    rows=[]
    for n,(_,page,idx,row,txt,heading,fp) in enumerate(selected,1):
        rows.append({'draft_id':f'dense_magazine_v1::{DOC}::{n:03d}','review_status':'NEEDS_HUMAN_REVIEW','corpus':'real_documents_v1_20261113','document_id':DOC,'source_pdf':manifest[DOC]['input_pdf'],'question':f'In the section “{heading}”, what technical mechanism, constraint, comparison, or practical outcome is established by the cited passage? Include any condition that qualifies the conclusion.','gold_answer_draft':txt,'gold_evidence_draft':[{'evidence_unit_id':f'{DOC}:p{page:04d}:e{idx:03d}','document_id':DOC,'page_number':page,'element_index':idx,'element_type':row.get('label'),'bbox':row.get('bbox'),'text':txt,'source_json':str(fp.resolve()),'future_node_mapping':'pending_evidence_node_assembly'}],'difficulty':'dense_review_candidate','question_design':'dense_magazine_source_bound_expansion','question_type_actual':'single_evidence','uses_gold_annotations':False,'node_mapping_status':'PENDING_EVIDENCE_NODE_ASSEMBLY','reviewer_decision':None,'reviewer_notes':None})
    assert len(existing)+len(rows)==TARGET, (len(existing),len(rows),TARGET)
    OUT.mkdir(exist_ok=True)
    (OUT/'qa_dense_candidates.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
    (OUT/'summary.json').write_text(json.dumps({'document_id':DOC,'target_total':TARGET,'existing_manual_or_expansion':len(existing),'new_dense_candidates':len(rows),'note':'Dense candidates are source-bound and require question/answer quality review before formal gold approval.'},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__': main()
