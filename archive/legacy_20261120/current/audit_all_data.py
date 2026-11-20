#!/usr/bin/env python3
"""Inventory all source documents and enumerate source pages without inference."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('choose a new output directory')
    import pymupdf
    from PIL import Image
    sampled=read(ROOT/'EvidenceNet/config/sources/relation_first_multisample_sources.json')['sources']
    sample_by_file=defaultdict(list)
    for row in sampled:sample_by_file[row['source_file']].append(row)
    pilot=ROOT/'parsing/experiments/dolphin_v2_pilot'
    full_cache={}
    for name,work in [('magazine_documents_v1.json','magazine_corpus_v1'),
                      ('government_financial_documents.json','government_financial_v1')]:
        for doc in read(pilot/name)['documents']:
            full_cache[doc['input_pdf']]=pilot/'work'/work/doc['document_id']/'pages'
    native=ROOT/'EvidenceNet/output/relation_first_corpus_shadow_v1/pptx_native'
    native_meta=read(native/'summary.json')
    documents,pages,metadata,errors=[],[],[],[]
    for path in sorted((ROOT/'data').rglob('*')):
        if not path.is_file():continue
        rel=str(path.relative_to(ROOT));ext=path.suffix.lower()
        if ext not in {'.pdf','.pptx','.jpg','.jpeg','.png'}:
            metadata.append({'path':rel,'kind':'metadata' if ext=='.json' else 'unsupported_file'})
            continue
        samples=sample_by_file.get(rel,[])
        doc_id=samples[0]['document_id'] if samples else path.stem
        row={'source_file':rel,'document_id':doc_id,'kind':ext,'source_sha256':digest(path),
             'sample_pages':len(samples),'bytes':path.stat().st_size}
        try:
            if ext=='.pdf':
                with pymupdf.open(path) as pdf:
                    if pdf.needs_pass:raise ValueError('encrypted PDF')
                    count=len(pdf)
                    dimensions=[(float(p.rect.width),float(p.rect.height)) for p in pdf]
                space='source_pdf_page'
            elif ext=='.pptx':
                with zipfile.ZipFile(path) as z:
                    count=sum(n.startswith('ppt/slides/slide') and n.endswith('.xml') and '/' not in n[len('ppt/slides/'):] for n in z.namelist())
                dimensions=[None]*count;space='native_slide'
            else:
                with Image.open(path) as image:
                    dimensions=[image.size];image.verify()
                count=1;space='raster'
            row.update(pages=count,page_space=space,status='readable')
            for n in range(1,count+1):
                page=f'slide_{n:04d}' if ext=='.pptx' else f'image_{n:04d}' if space=='raster' else f'page_{n:04d}'
                candidates=[]
                if rel in full_cache:candidates.append(full_cache[rel]/page)
                for sample in samples:
                    if sample.get('page_space')!=space or sample.get('page')!=page:continue
                    if sample['mode'] in {'fresh','fresh_image'}:
                        candidates.append(pilot/'work/relation_first_fresh/parsed'/sample.get('case_id',f'relation_{doc_id}'))
                    elif sample.get('work') and not sample.get('native_override_required'):
                        candidates.append(ROOT/sample['work'])
                cached=[]
                for candidate in dict.fromkeys(candidates):
                    summary=candidate/'run_summary.json'
                    files=sorted((candidate/'output_json').glob('*.json'))
                    if not summary.is_file() or len(files)!=1:continue
                    try:
                        stat=read(summary);elements=read(files[0])
                        if stat.get('status')=='complete' and isinstance(elements,list) and stat.get('image_size'):
                            cached.append({'work':str(candidate.relative_to(ROOT)),
                                'elements':len(elements),'elapsed_seconds':stat.get('elapsed_seconds'),
                                'source_content_verified':False,
                                'reason':'Historical parser outputs have no bound source-image hash; presence is not provenance verification.'})
                    except (OSError,ValueError,TypeError):pass
                native_match=ext=='.pptx' and native_meta.get('input_sha256')==row['source_sha256'] and native_meta.get('slides')==count
                pages.append({'document_id':doc_id,'page':page,'source_file':rel,'source_sha256':row['source_sha256'],
                    'page_number':n,'page_space':space,'source_size':dimensions[n-1],
                    'parser_cache_candidates':cached,'native_pptx_hash_match':native_match,
                    'native_pptx_faithful_render':False if ext=='.pptx' else None,
                    'pipeline_status':'not_run'})
        except Exception as exc:
            row.update(status='input_error',error=str(exc));errors.append(row)
        documents.append(row)
    ids=[d['document_id'] for d in documents]
    if len(ids)!=len(set(ids)):raise ValueError('document IDs collide; resolve before running')
    hashes=defaultdict(list)
    for d in documents:hashes[d['source_sha256']].append(d['source_file'])
    summary={'documents':len(documents),'pages':len(pages),'types':dict(Counter(d['kind'] for d in documents)),
        'pages_by_type':dict(Counter(d['kind'] for d in documents for _ in range(d.get('pages',0)))),
        'metadata_files':len(metadata),'input_errors':len(errors),'previous_sample_pages':len(sampled),
        'pages_with_parser_cache_candidates':sum(bool(p['parser_cache_candidates']) for p in pages),
        'native_pptx_hash_matched_pages':sum(p['native_pptx_hash_match'] for p in pages),
        'exact_duplicate_files':[v for v in hashes.values() if len(v)>1],
        'production_modified':False,'inference_calls':0,
        'limitations':['Cache candidates are not automatically reusable without source provenance verification.',
                       'Source PDF page numbers are not interchangeable with split-render page numbers.',
                       'PPTX native preview is approximate; unsupported objects and rendering fidelity remain unresolved.',
                       'Current edge stage emits candidates, not independently validated semantic edges.']}
    args.output.mkdir(parents=True)
    for name,value in [('summary.json',summary),('documents.json',documents),('metadata_files.json',metadata)]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    (args.output/'pages.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in pages))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
