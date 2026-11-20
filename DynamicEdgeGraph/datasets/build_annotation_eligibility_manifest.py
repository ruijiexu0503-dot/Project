#!/usr/bin/env python3
"""Write a non-destructive eligibility gate for annotation and benchmark use."""
import json
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parent
PIPE = ROOT / 'real_documents_v1_20261113/pipeline_to_nodes_v1_20261114'
OUT = ROOT / 'annotation_eligibility_v1_20261117.json'
ALL = ROOT / 'all_qa_review_drafts_v1/all_qa_drafts.jsonl'

def main():
    manifest = json.loads((PIPE/'manifest.resolved.json').read_text())['documents']
    docs = []
    strict = set()
    for idx, doc in enumerate(manifest):
        work = PIPE/'work'/doc['document_id']/'pages'
        if not work.exists():
            continue
        total = len(fitz.open(doc['input_pdf']))
        page_dirs = {int(p.name.removeprefix('page_')) for p in work.glob('page_[0-9]*')}
        summaries = {int(p.parent.name.removeprefix('page_')) for p in work.glob('page_[0-9]*/run_summary.json')}
        failed = list(work.glob('page_[0-9]*/failure.json'))
        complete = page_dirs == summaries == set(range(1, total + 1)) and not failed
        if complete:
            strict.add(doc['document_id'])
        docs.append({'document_id':doc['document_id'], 'manifest_index':idx, 'pdf_pages':total,
            'page_dirs':len(page_dirs), 'successful_page_summaries':len(summaries), 'failure_pages':len(failed),
            'annotation_status':'ELIGIBLE_FOR_REVIEW_PENDING_NODE_MAPPING' if complete else 'EXCLUDE_OR_PARK_INCOMPLETE_PARSE',
            'benchmark_status':'NOT_GOLD_PENDING_CANONICAL_NODE_MAPPING' if complete else 'BLOCKED_INCOMPLETE_PARSE'})
    qas=[]
    for row in (json.loads(x) for x in ALL.read_text().splitlines() if x):
        if row['corpus'] == 'node_vqa_reuse_v1_20261113':
            status, reason = 'PILOT_ONLY_BLOCKED', 'legacy nodes are HYBRID_SHADOW_CANDIDATE; original PDFs/canonical-node verification absent'
        elif row['document_id'] not in strict:
            status, reason = 'EXCLUDE_OR_PARK', 'source document parse is incomplete'
        elif row.get('question_design') in {'auto_source_bound_expansion','dense_magazine_source_bound_expansion'}:
            status, reason = 'EXCLUDE_OR_PARK', 'templated auto expansion requires regeneration into standalone retrievable QA'
        else:
            status, reason = 'REVIEW_REQUIRED', 'source pages complete but canonical evidence-node mapping and human approval remain pending'
        qas.append({'draft_id':row['draft_id'],'document_id':row['document_id'],'corpus':row['corpus'],'eligibility_status':status,'reason':reason})
    OUT.write_text(json.dumps({'version':'annotation_eligibility_v1_20261117','real_documents':docs,'legacy_corpus_status':'PILOT_ONLY_BLOCKED','qa_eligibility':qas,'rule':'Use only REVIEW_REQUIRED items for human QA review; none are formal gold until canonical node mapping is verified.'},ensure_ascii=False,indent=2)+'\n')
    print(OUT)
if __name__ == '__main__': main()
