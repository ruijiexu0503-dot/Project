#!/usr/bin/env python3
"""Freeze a small full-document retrieval pilot, with no labels in query inputs."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def rows(path):
    with path.open() as f:
        for line in f:
            if line.strip(): yield json.loads(line)


def rank(value): return hashlib.sha256(('vldocir-pilot-20261009:'+value).encode()).hexdigest()


def write(path,values):
    path.write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in values))


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if (a.output/'manifest.json').exists(): raise FileExistsError('Pilot already frozen')
    docs={r['document_id']:r for r in rows(a.data/'documents.jsonl')}
    evidence=defaultdict(set)
    for e in rows(a.data/'question_evidences.jsonl'):
        evidence[e['question_id']].add((e['document_id'],e['page_number']))
    selected={}
    for q in rows(a.data/'questions.jsonl'):
        ids={d for d,_ in evidence[q['question_id']]}
        if not ids or any(d not in docs or docs[d]['page_count']>32 for d in ids): continue
        sources={docs[d]['data_source'] for d in ids}
        if len(sources)!=1: continue
        cell=(next(iter(sources)),q['question_type'])
        if cell not in selected or rank(q['question_id'])<rank(selected[cell]['question_id']): selected[cell]=q
    queries=sorted(selected.values(),key=lambda q:q['question_id'])
    qids={q['question_id'] for q in queries}
    chosen={d for q in queries for d,_ in evidence[q['question_id']]}
    negatives=[]
    for source in sorted({d['data_source'] for d in docs.values()}):
        pool=[d for d in docs if docs[d]['data_source']==source and d not in chosen and docs[d]['page_count']<=10]
        if pool: negatives.append(min(pool,key=rank))
    chosen.update(negatives)
    a.output.mkdir(parents=True,exist_ok=True)
    write(a.output/'queries.jsonl',({'question_id':q['question_id'],'question':q['question'],
           'question_type':q['question_type']} for q in queries))
    write(a.output/'gold_evidence.jsonl',(e for e in rows(a.data/'question_evidences.jsonl') if e['question_id'] in qids))
    pages=[r for r in rows(a.data/'document_pages.jsonl') if r['document_id'] in chosen]
    write(a.output/'corpus_pages.jsonl',pages)
    write(a.output/'documents.jsonl',(docs[d] for d in sorted(chosen)))
    manifest={'revision':'40a1818110c20e9279bbb4a3b6283ceac2d631ba','scope':'pilot-not-official-full-corpus',
              'queries':len(queries),'documents':len(chosen),'pages':len(pages),
              'cells':[list(c) for c in sorted(selected)],'negative_only_documents':negatives,
              'selection':'one hash-selected query per source/type, only documents <=32 pages; all pages of each document plus one <=10-page distractor document per source',
              'gold_used_only_for_selection_and_evaluation':True,
              'retrieval_inputs':'queries.jsonl excludes answer, evidence and ratings',
              'metadata_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.glob('*.jsonl')}}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['queries','documents','pages','cells']},indent=2))


if __name__=='__main__': main()
