"""Query/corpus/qrels adapter; no claim to reproduce an author's training loader."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from evaluate_vldocir import rows, page, evaluate

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
MINIMAL=ROOT/'EvidenceNet/output/vldocir_minimal_inputs_20261016'
OUT=ROOT/'EvidenceNet/output/vldocir_eval_bundle_20261016'
ARMS=('page_mean','page_windows','parser_atoms','parser_atoms_visual','hybrid_text','hybrid_visual')


def page_id(document_id, number):
    return str(document_id)+':'+str(int(number))


def dump(path, records):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w') as f:
        for r in records:f.write(json.dumps(r,ensure_ascii=False)+'\n')


def export(out):
    queries=list(rows(BASE/'pilot/queries.jsonl'));evidence=list(rows(BASE/'pilot/gold_evidence.jsonl'))
    pages=list(rows(BASE/'pilot/image_pages.jsonl'));corpus={page(p) for p in pages}
    qids={q['question_id'] for q in queries};ids={page_id(p['document_id'],p['page_number']) for p in pages}
    assert len(ids)==len(pages)==518
    out.mkdir(parents=True,exist_ok=True)
    dump(out/'queries.jsonl',({'_id':q['question_id'],'text':q['question']} for q in queries))
    dump(out/'corpus_pages.jsonl',({'_id':page_id(p['document_id'],p['page_number']),'image':p['image_path']} for p in pages))
    dump(out/'page_provenance.jsonl',({'_id':page_id(p['document_id'],p['page_number']),**p} for p in pages))
    dump(out/'query_provenance.jsonl',({'_id':q['question_id'],'question_type':q['question_type']} for q in queries))
    relevance=sorted({(e['question_id'],page_id(e['document_id'],e['page_number'])) for e in evidence if e['question_id'] in qids})
    assert all(q in qids and p in ids for q,p in relevance)
    (out/'qrels.tsv').write_text('query-id\tcorpus-id\tscore\n'+''.join(q+'\t'+p+'\t1\n' for q,p in relevance))
    input_hashes={}
    for arm in ARMS:
        model_file=MINIMAL/arm/'model_inputs.jsonl';mapping_file=MINIMAL/arm/'provenance.jsonl'
        inputs=list(rows(model_file));mapping=list(rows(mapping_file));assert len(inputs)==len(mapping)
        dump(out/arm/'corpus_units.jsonl',({'_id':m['unit_id'],'text':u['content'],'title':u['title_context']} for u,m in zip(inputs,mapping)))
        dump(out/arm/'unit_pages.jsonl',({'_id':m['unit_id'],'page_id':page_id(m['document_id'],m['page_number'])} for m in mapping))
        input_hashes[str(model_file)]=hashlib.sha256(model_file.read_bytes()).hexdigest()
        input_hashes[str(mapping_file)]=hashlib.sha256(mapping_file.read_bytes()).hexdigest()
    checks={}
    for arm in ARMS:
        scores=list(rows(BASE/'retrieval'/f'{arm}_scores.jsonl'))
        dump(out/'runs'/f'{arm}.jsonl',({'query_id':r['question_id'],'corpus_id':page_id(r['document_id'],r['page_number']),'score':r['score']} for r in scores))
        restored=[]
        for r in rows(out/'runs'/f'{arm}.jsonl'):
            document_id,number=r['corpus_id'].rsplit(':',1)
            restored.append({'question_id':r['query_id'],'document_id':document_id,'page_number':int(number),'score':r['score']})
        actual=evaluate(queries,evidence,restored,corpus=corpus)
        expected=json.loads((BASE/'retrieval'/f'{arm}_metrics.json').read_text())
        assert actual['per_query']==expected['per_query'],arm
        checks[arm]={'saved_ranking_rows':len(scores),'metrics_identical_after_roundtrip':True}
    report=dict(queries=len(queries),pages=len(pages),qrels=len(relevance),
        arms=checks,training_performed=False,new_model_inference=False,
        schema='Our adapter, not a claimed official VL-DocIR training schema. Query and page relevance; no inferred node-level positive labels.',
        model_inputs='IDs/paths select samples outside the encoder. Text encoder sees text and optional title; visual encoder loads image pixels. Qrels never enter inputs.')
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    files=[Path(__file__),BASE/'manifest.json']+list(out.rglob('*.jsonl'))+[out/'qrels.tsv',out/'verification.json']
    input_hashes.update({str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files})
    (out/'manifest.json').write_text(json.dumps(input_hashes,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=OUT);a=p.parse_args();export(a.output)
