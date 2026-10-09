#!/usr/bin/env python3
"""Freeze unseen-document pages before node inference or semantic review."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import pymupdf

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT/'parsing/experiments/dolphin_v2_pilot'


def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if (a.output/'manifest.json').exists():
        raise FileExistsError('Frozen holdout already exists; use a new output directory')
    old = read(ROOT/'EvidenceNet/output/hybrid_49page_stress_prepared_20261007/manifest.json')
    seen = {t.split('/')[1] for t in old['tasks']}
    docs = read(PILOT/'document_graph_expansion_20261008.json')['documents']
    rows = []
    for doc in docs:
        name = doc['document_id']
        if name in seen: raise ValueError(f'Document overlaps regression set: {name}')
        candidates = []
        for path in (PILOT/'work/document_graph_expansion_20261008'/name/'pages').glob('page_*/run_summary.json'):
            run = read(path)
            if run['status'] != 'complete' or run['page'] < 3: continue
            labels = run['label_distribution']
            if labels.get('para', 0) < 2: continue
            score = (bool(labels.get('tab')), bool(labels.get('fig') and labels.get('cap')), min(labels.get('para',0), 8), -run['page'])
            candidates.append((score,path,run))
        if not candidates: raise ValueError(f'No qualifying parsed page: {name}')
        _, summary, run = max(candidates,key=lambda c:c[0])
        page = f"page_{run['page']:04d}"
        source = summary.parent/'output_json'/f'{page}.json'
        pdf = ROOT/doc['input_pdf']
        dest = a.output/name/page; dest.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest/'dolphin_elements.json')
        with pymupdf.open(pdf) as document:
            source_page = document[run['page']-1]
            scale = 1600/max(source_page.rect.width,source_page.rect.height)
            pix = source_page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
            if [pix.width,pix.height] != run['image_size']: raise ValueError('Parser/image geometry mismatch')
            pix.save(dest/'original.png')
        rows.append({'task':f'{name}/{page}','document_type':doc['document_type'],
                     'pdf':str(pdf),'pdf_sha256':sha(pdf),'parser_source':str(source),
                     'parser_sha256':sha(source),'image_sha256':sha(dest/'original.png'),
                     'label_distribution':run['label_distribution'],
                     'review_status':'PENDING_BEFORE_INFERENCE'})
    report = {'selection_rule':'one page per new document, >=2 paragraphs, page>=3; prioritize tables then figure+caption then paragraph count; earliest tie',
              'document_disjoint_from_49page_regression':True,'node_inference_performed':False,
              'independent_human_ground_truth':False,'pages':rows,'production_modified':False}
    (a.output/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'pages':len(rows),'tasks':[r['task'] for r in rows]},indent=2))


if __name__ == '__main__': main()
