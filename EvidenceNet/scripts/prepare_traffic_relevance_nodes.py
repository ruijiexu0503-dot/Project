#!/usr/bin/env python3
"""Freeze complete Dolphin paper inputs for the existing hybrid-v2 node pipeline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'parsing/experiments/dolphin_v2_pilot'))
from run_pdf_corpus import render_page
import pymupdf
from prepare_vldocir_nodes import adapt

BATCH='paper_relevance_urban_traffic_20261013'
DEFAULT=ROOT/'EvidenceNet/output'/BATCH


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata_roles(rep):
    # Keep source roles and text; remove furniture/bibliography from evidence,
    # and preserve titles independently. This is not a semantic gold label.
    first_page=rep['page']==1
    after_title=False;before_abstract=first_page
    for atom in rep['atoms']:
        role=atom['layout_role'];text=atom['text_preview'].strip()
        if role=='sec_0':after_title=True;continue
        if 'abstract' in text[:35].casefold() or (role.startswith('sec_') and role!='sec_0'):
            before_abstract=False
        reason=None
        if role in {'watermark','reference','catalogue','header','foot','footer','page_num','page_number'}:reason='source_metadata_role'
        if after_title and before_abstract and atom['atom_type'] not in {'heading','table'}:reason='front_matter_before_abstract'
        if reason:
            atom['source_atom_type']=atom['atom_type'];atom['atom_type']='furniture';atom['exclusion_reason']=reason
    return rep


def main(out):
    if out.exists():raise ValueError('fresh_output_required')
    source=ROOT/'data/incoming'/BATCH/'corpus_manifest.json'
    manifest=json.loads(source.read_text());parsed=ROOT/'parsing/experiments/dolphin_v2_pilot'
    published=json.loads((parsed/'output'/BATCH/'summary.json').read_text())
    assert published['completed_pages']==published['total_pages']==160
    tasks=[];fingerprints={str(source):sha(source)};counts=[]
    for doc in manifest['documents']:
        did=doc['document_id'];pdfpath=ROOT/doc['input_pdf'];fingerprints[str(pdfpath)]=sha(pdfpath)
        pdf=pymupdf.open(pdfpath)
        for page in range(1,len(pdf)+1):
            task=f'{did}/page_{page:04d}';src=parsed/'work'/BATCH/did/'pages'/f'page_{page:04d}'
            summary=json.loads((src/'run_summary.json').read_text());assert summary['status']=='complete'
            path=src/'output_json'/f'page_{page:04d}.json';elements=json.loads(path.read_text())
            fingerprint=sha(path);fingerprints[str(path)]=fingerprint
            image=render_page(pdf[page-1]);assert list(image.size)==summary['image_size']
            target=out/'prepared'/task;target.mkdir(parents=True,exist_ok=True);image.save(target/'original.png')
            row={'document_id':did,'page_number':page,'sha256':sha(target/'original.png')}
            rep=adapt(elements,row,{**summary,'scale_to_original':[1,1]}, {'data_source':'paper','title':doc['title']})
            metadata_roles(rep);rep['parser_elements_sha256']=fingerprint
            write(target/'input_representation.json',rep);tasks.append(task)
        counts.append({'document_id':did,'pages':len(pdf),'title':doc['title']});pdf.close()
    write(out/'prepared/manifest.json',{'tasks':tasks,'pages':len(tasks),'batch_size':20,
        'batches':[tasks[i:i+20] for i in range(0,len(tasks),20)],'uses_gold_annotations':False})
    write(out/'documents.json',counts)
    code=[Path(__file__),*[ROOT/'EvidenceNet/scripts'/name for name in ['run_vldocir_nodes.py','run_embedding_geometry_node_baseline.py','run_hybrid_node_pilot.py','run_hybrid_node_v2.py','prepare_vldocir_nodes.py','dolphin_text.py','run_traffic_relevance_graph.py']]]
    write(out/'manifest.json',{'source_sha256':fingerprints,'code_sha256':{str(p.resolve()):sha(p) for p in code},
        'prepared_sha256':{str(p.relative_to(out)):sha(p) for p in (out/'prepared').rglob('*') if p.is_file()},
        'pages':len(tasks),'documents':len(counts),'parser':'Dolphin-v2','node_generation':'embedding+geometry+Qwen hybrid-v2',
        'semantic_text_policy':'dolphin_softwrap_semantic_v1',
        'group_labels_used_for_inference':False,'evaluation':'document topic groups are not node-pair gold labels'})
    print(json.dumps({'pages':len(tasks),'batches':(len(tasks)+19)//20,'documents':counts}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=DEFAULT);main(p.parse_args().output.resolve())
