#!/usr/bin/env python3
"""Matched Qwen3.5 description retrieval + bounded model review, isolated output."""
import argparse
from collections import Counter
import gc
import hashlib
import html
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'EvidenceNet'))
DOCS = ['CERNCourier2022NovDec-digitaledition', 'CERNCourier2025JanFeb-digitaledition',
        'CERNCourier2026MayJun-digitaledition', 'gw150914_detection']
FIELDS = ['base_summary', 'key_points', 'keywords', 'entities', 'discourse_role']


def read(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def rows(path, value):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in value))


def matched(n, r):
    return bool(n and n['document_order'] == r['document_order'] and n['evidence_type'] == r['evidence_type']
                and all(n.get(k) == r['qwen2_5_baseline'].get(k) for k in FIELDS))


def prepare(out):
    units, excluded, hashes = [], [], {}
    for doc in DOCS:
        source = ROOT / 'EvidenceNet/output/canonical_graph' / doc / 'evidence_nodes.jsonl'
        comparison = ROOT / 'EvidenceNet/output/enrichment_comparisons/Qwen3.5-35B-A3B' / doc / 'node_enrichment_comparison.jsonl'
        for p in (source, comparison):
            hashes[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        nodes = {n['node_id']: n for n in read(source)}
        for r in read(comparison):
            n = nodes.get(r['node_id'])
            reason = None
            if not matched(n, r): reason = 'snapshot_baseline_mismatch'
            elif r['status'] != 'ok' or not r.get('qwen3_5_candidate'): reason = 'missing_successful_description'
            elif 'Qwen3.5-35B-A3B' not in r.get('candidate_model', ''): reason = 'wrong_model'
            elif len(n.get('plain_text', '').split()) < 25: reason = 'short_unit_under_25_words'
            elif n.get('evidence_type') not in ('text', 'formula'): reason = 'outside_text_formula_scope'
            elif any(t in ' '.join(n.get('section_path', [])).lower() for t in ('reference', 'bibliography', 'acknowledg')): reason = 'reference_or_acknowledgment_section'
            if reason:
                excluded.append({'node_id': r['node_id'], 'reason': reason}); continue
            desc = r['qwen3_5_candidate']
            if not desc.get('base_summary'):
                excluded.append({'node_id': r['node_id'], 'reason': 'empty_summary'}); continue
            units.append({**n, **{k: desc.get(k) for k in FIELDS}, 'description_model': r['candidate_model'],
                          'source_snapshot': str(source), 'description_source': str(comparison)})
    rows(out / 'units.jsonl', units); rows(out / 'excluded.jsonl', excluded)
    dump(out / 'input_manifest.json', {'documents': DOCS, 'units': len(units),
        'by_document': dict(Counter(n['doc_id'] for n in units)), 'excluded': dict(Counter(r['reason'] for r in excluded)),
        'sha256': hashes, 'production_modified': False,
        'scope': 'Cross-document evidence only; same-magazine article ownership is not inferred.',
        'provenance_limit': 'Historical enrichment has no original-text hash. Require exact baseline fields, node ID, order and type to match the canonical snapshot; this is stronger than ID-only but not a cryptographic source-text binding.'})


def run(out):
    import faiss
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer
    from run_ann_candidate_pilot import normalize, index_for, search_filtered
    units = read(out / 'units.jsonl')
    faiss.omp_set_num_threads(8)
    model_path = ROOT.parent / '.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181'
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if not torch.cuda.is_available(): raise RuntimeError('Run embedding and review via GPU sbatch')
    model = AutoModel.from_pretrained(model_path, local_files_only=True, dtype=torch.float16).cuda().eval()
    inputs = {'original': [n['plain_text'] for n in units],
              'description': [n['base_summary'] + '\n' + '\n'.join(n.get('key_points') or []) for n in units]}
    owners = [n['doc_id'] for n in units]
    hits, timing = {}, {}
    for mode, texts in inputs.items():
        vectors = []; lengths = tokenizer(texts, truncation=False, add_special_tokens=True)['input_ids']
        timing[mode + '_truncated_units'] = sum(len(t) > 512 for t in lengths)
        for start in range(0, len(texts), 16):
            batch = tokenizer(texts[start:start+16], padding=True, truncation=True, max_length=512, return_tensors='pt').to('cuda')
            with torch.inference_mode():
                vectors.append(torch.nn.functional.normalize(model(**batch).last_hidden_state[:,0].float(), dim=1).cpu().numpy())
        v = normalize(np.concatenate(vectors)); np.save(out / (mode + '_vectors.npy'), v)
        index, _ = index_for(v, True, 128)
        hits[mode] = search_filtered(index, v, owners, owners, 20)
        faiss.write_index(index, str(out / (mode + '.hnsw')))
        print(json.dumps({'embedded_mode': mode, 'units': len(units)}), flush=True)
    del model, vectors, batch
    gc.collect(); torch.cuda.empty_cache()
    variants = {}
    for mode in hits:
        variants[mode] = {tuple(sorted((i,j))) for i, values in enumerate(hits[mode]) for j,_ in values[:10]}
    fused = set()
    for i in range(len(units)):
        scores = Counter()
        for mode in hits:
            for rank,(j,_) in enumerate(hits[mode][i],1): scores[j] += 1/(60+rank)
        for j,_ in scores.most_common(10): fused.add(tuple(sorted((i,j))))
    variants['fused'] = fused
    variants['union'] = variants['original'] | variants['description']
    candidates = []
    for i,j in sorted(variants['union'] | fused):
        candidates.append({'a': units[i]['node_id'], 'b': units[j]['node_id'], 'a_index': i, 'b_index': j,
            'methods': [name for name, pairs in variants.items() if (i,j) in pairs], 'status': 'UNVERIFIED'})
    rows(out / 'candidates.jsonl', candidates)
    # Deterministic stratified sample; no gold labels or expected outcome in prompt.
    strata = {'shared': [], 'original_only': [], 'description_only': []}
    for r in candidates:
        if 'original' in r['methods'] and 'description' in r['methods']: key='shared'
        elif 'original' in r['methods']: key='original_only'
        elif 'description' in r['methods']: key='description_only'
        else: continue
        strata[key].append(r)
    sample=[]
    for key, values in strata.items():
        values.sort(key=lambda r: hashlib.sha256((r['a']+'\0'+r['b']).encode()).hexdigest())
        sample.extend(dict(r, stratum=key) for r in values[:8])
    rows(out / 'review_sample.jsonl', sample)
    summary = {'production_modified': False, 'slurm_job_id': os.getenv('SLURM_JOB_ID'), 'units':len(units),
        'candidate_counts':{k:len(v) for k,v in variants.items()}, 'sample_strata':dict(Counter(r['stratum'] for r in sample)),
        **timing, 'review_status':'pending', 'embedding_model':str(model_path), 'pooling':'normalized CLS',
        'limitations':['Cross-document only; no same-magazine article experiment.',
            'No independent cross-document gold labels; model review is not measured recall or human precision.',
            'Existing Qwen3.5 descriptions are reused; no other description model is substituted.']}
    dump(out / 'summary.json', summary)
    from evidence_graph.llm_client import create_llm
    llm = create_llm({'provider':'transformers','model':str(ROOT/'external/models/Qwen3.5-35B-A3B'),
                     'dtype':'bfloat16','device_map':'auto','require_cuda':True,'enable_thinking':False})
    reviews=[]
    for r in sample:
        a,b=units[r['a_index']],units[r['b_index']]
        payload={key:{'id': n['node_id'],'document':n['doc_id'],'section':n.get('section_path'),
                      'original_text':n['plain_text'],'description':n['base_summary'],'key_points':n.get('key_points')}
                 for key,n in [('A',a),('B',b)]}
        prompt='''Judge a direct relation between two evidence passages from different documents using ONLY supplied original texts. Descriptions are navigation aids, not proof. Shared topic, entity or vocabulary alone is TOPICAL_ONLY. A useful direct connection must identify a specific shared event/result/method/claim and explain the connection; support, modification or contradiction requires compatible scope. Same-topic different objects must not be equated. Do not invent citation or author intent. Return JSON: {"decision":"DIRECT_RELATION|TOPICAL_ONLY|UNRELATED|UNCERTAIN", "relation_description":"short grounded explanation", "direction":"A_TO_B|B_TO_A|SYMMETRIC|NONE", "a_span":"exact nonempty substring of A original_text for DIRECT_RELATION", "b_span":"exact nonempty substring of B original_text for DIRECT_RELATION", "reason":"short rationale"}.\n'''+json.dumps(payload,ensure_ascii=False)
        try:
            generation=llm.generate_json('Conservative cross-document evidence reviewer. JSON only.',prompt,900)
            value=generation.parsed
            valid=isinstance(value,dict) and value.get('decision') in {'DIRECT_RELATION','TOPICAL_ONLY','UNRELATED','UNCERTAIN'} and value.get('direction') in {'A_TO_B','B_TO_A','SYMMETRIC','NONE'}
            if valid and value['decision']=='DIRECT_RELATION':
                valid=all(isinstance(value.get(k),str) and bool(value[k].strip()) and value[k] in n['plain_text'] for k,n in [('a_span',a),('b_span',b)])
            reviews.append({**r,'judgment':value,'valid':bool(valid),'model':generation.model,'raw':generation.raw})
        except Exception as exc: reviews.append({**r,'valid':False,'error':str(exc)})
        rows(out/'reviews.jsonl',reviews)
        print(json.dumps({'reviewed':len(reviews),'total':len(sample)}),flush=True)
    summary['review_status']='complete'
    summary['review_counts']={key:dict(Counter(x.get('judgment',{}).get('decision') if x['valid'] else 'INVALID' for x in reviews if x['stratum']==key)) for key in strata}
    dump(out/'summary.json',summary)
    cards=[]
    for r in reviews:
        a,b=units[r['a_index']],units[r['b_index']]
        cards.append('<details><summary>'+html.escape(r['stratum']+' | '+r['a']+' ↔ '+r['b'])+'</summary><pre>'+html.escape(json.dumps(r.get('judgment',r),ensure_ascii=False,indent=2))+'</pre><p>'+html.escape(a['plain_text'])+'</p><p>'+html.escape(b['plain_text'])+'</p></details>')
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Qwen3.5 description retrieval</title><style>body{font:15px system-ui;max-width:1100px;margin:auto}pre{white-space:pre-wrap}details{padding:12px}</style><h1>Qwen3.5 描述跨文档检索对比</h1><p>模型抽样审查，不是人工金标准；不写入正式图。</p><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(cards))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','run']);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    (prepare if args.stage=='prepare' else run)(args.output)
