"""ColNomic page-image retrieval on the exact frozen 24-query / 518-page pilot."""
import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

from evaluate_vldocir import rows, page, evaluate
from evaluate_vldocir_ap import average_precision
from run_node_context_edges import ROOT, read, write, jsonl, sha

BASELINE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
OUT=ROOT/'EvidenceNet/output/vldocir_colnomic_7b_20261016'
MODEL=ROOT/'external/models/ColNomic-7B'
BASE=ROOT/'external/models/ColQwen2.5-7B-base'
ENGINE=ROOT/'external/colpali-engine'
MODEL_REV='09dbc9502b66605d5be56d2226019b49c9fd3293'
BASE_REV='15e77de3944c94363b38ff3b53844f066e6fcd19'
ENGINE_REV='97487f8871ff4d5d2284411fe61bdcd2cfe99894'


def serializable_loading_info(loading):
    # Transformers 5 returns sets for some loading diagnostics.
    return {k:sorted(v) if isinstance(v,set) else v for k,v in loading.items()}


def validate_inputs(queries,pages,evidence):
    qids={q['question_id'] for q in queries};pids={page(p) for p in pages}
    if len(qids)!=len(queries) or len(pids)!=len(pages):raise ValueError('duplicate query/page')
    gold=defaultdict(set)
    for e in evidence:
        if e['question_id'] in qids:gold[e['question_id']].add(page(e))
    if any(not gold[q] or not gold[q]<=pids for q in qids):raise ValueError('missing gold page')
    return gold


def prepare(out):
    if (out/'manifest.json').exists():check(out);return
    index=read(BASE/'model.safetensors.index.json')
    for name in set(index['weight_map'].values()):
        if not (BASE/name).is_file():raise ValueError('base download incomplete: '+name)
    if __import__('subprocess').check_output(['git','-C',str(ENGINE),'rev-parse','HEAD'],text=True).strip()!=ENGINE_REV:
        raise ValueError('unexpected engine revision')
    queries=list(rows(BASELINE/'pilot/queries.jsonl'));pages=list(rows(BASELINE/'pilot/image_pages.jsonl'))
    evidence=list(rows(BASELINE/'pilot/gold_evidence.jsonl'));validate_inputs(queries,pages,evidence)
    assert len(queries)==24 and len(pages)==518
    for p in pages:
        if sha(p['image_path'])!=p['sha256']:raise ValueError('changed original image')
    # A page manifest binds source identity; pixel data is loaded separately, never JSON metadata.
    pages=sorted(pages,key=lambda p:(p['document_id'],int(p['page_number'])))
    jsonl(out/'pages.jsonl',pages);jsonl(out/'queries.jsonl',queries)
    docs={d['document_id']:d for d in rows(BASELINE/'pilot/documents.jsonl')}
    first={}
    for i,p in enumerate(pages):first.setdefault(docs[p['document_id']]['data_source'],i)
    write(out/'protocol.json',dict(model='nomic-ai/colnomic-embed-multimodal-7b',revision=MODEL_REV,
        base='nomic-ai/colqwen2.5-7B-base',base_revision=BASE_REV,engine_commit=ENGINE_REV,
        queries=24,pages=518,input='Original page pixels and plain questions through official processor, no node JSON, OCR, title text or gold features.',
        visual_tokens=1280,visual_token_source='Official published training_config.yml; explicitly set because processor config contains legacy size fields.',
        score='Official process_images/process_queries and score_multi_vector MaxSim, no Ctx/rerank/ensemble.',
        dtype='bfloat16',device='cuda:0',attention='sdpa',smoke_indices=list(first.values()),
        caveat='Selected-corpus pilot. Different model and representation from Qwen3 text baseline; not an isolated node-generation ablation or full-paper reproduction.'))
    files=[BASELINE/'pilot'/x for x in ['queries.jsonl','gold_evidence.jsonl','image_pages.jsonl','documents.jsonl']]
    files += [Path(__file__),Path(__file__).with_name('evaluate_vldocir.py'),Path(__file__).with_name('evaluate_vldocir_ap.py')]
    files += [out/'pages.jsonl',out/'queries.jsonl',out/'protocol.json']
    files += [p for d in [MODEL,BASE] for p in d.iterdir() if p.is_file()]
    files += list((ENGINE/'colpali_engine').rglob('*.py'))
    files += list((ROOT/'external/colnomic_runtime/peft').rglob('*.py'))
    write(out/'manifest.json',dict(files={str(p):sha(p) for p in files},images={p['image_path']:p['sha256'] for p in pages}))
    print(dict(prepared=True,queries=len(queries),pages=len(pages)),flush=True)


def check(out):
    m=read(out/'manifest.json')
    for p,digest in m['files'].items():
        if sha(p)!=digest:raise ValueError('changed model/code/input: '+p)
    for p,digest in m['images'].items():
        if sha(p)!=digest:raise ValueError('changed page image: '+p)


def report(out):
    queries=list(rows(out/'queries.jsonl'));pages=list(rows(out/'pages.jsonl'))
    evidence=list(rows(BASELINE/'pilot/gold_evidence.jsonl'))
    gold=validate_inputs(queries,pages,evidence);scores=list(rows(out/'scores.jsonl'))
    if len(scores)!=len(queries)*len(pages):raise ValueError('incomplete scores')
    observed={(s['question_id'],page(s)) for s in scores}
    if len(observed)!=len(scores) or observed!={(q['question_id'],page(p)) for q in queries for p in pages}:raise ValueError('score coverage')
    metrics=evaluate(queries,evidence,scores,corpus={page(p) for p in pages})
    byquery=defaultdict(dict)
    for s in scores:byquery[s['question_id']][page(s)]=s['score']
    ap={};groups=defaultdict(list)
    for q in queries:
        qid=q['question_id'];ranked=sorted(byquery[qid],key=lambda p:(-byquery[qid][p],p))
        ap[qid]={f'AP@{k}':average_precision(ranked,gold[qid],k) for k in [3,5,10]}
        ap[qid]['AP_full']=average_precision(ranked,gold[qid]);groups[q['question_type']].append(ap[qid])
    macro_ap={key:sum(sum(r[key] for r in rr)/len(rr) for rr in groups.values())/len(groups) for key in next(iter(ap.values()))}
    metrics.update(scope='same frozen pilot; base ColNomic raw pages',per_query_ap=ap,macro_ap=macro_ap)
    write(out/'metrics.json',metrics)
    frozen=read(BASELINE/'retrieval/comparison.json')
    baseline_ap={}
    for arm in frozen['arms']:
        buckets=defaultdict(dict)
        for s in rows(BASELINE/'retrieval'/f'{arm}_scores.jsonl'):buckets[s['question_id']][page(s)]=s['score']
        per_type=defaultdict(list)
        for q in queries:
            qid=q['question_id'];ranked=sorted(buckets[qid],key=lambda p:(-buckets[qid][p],p))
            per_type[q['question_type']].append({'AP@5':average_precision(ranked,gold[qid],5),'AP_full':average_precision(ranked,gold[qid])})
        baseline_ap[arm]={k:sum(sum(r[k] for r in rr)/len(rr) for rr in per_type.values())/len(per_type) for k in ['AP@5','AP_full']}
    write(out/'comparison.json',dict(complete=True,queries=24,pages=518,colnomic_macro=metrics['macro_six_types'],
        colnomic_macro_ap=macro_ap,frozen_controls=frozen['arms'],frozen_controls_ap=baseline_ap,
        note='Same queries/corpus/gold. Model and representation both differ. No edge expansion.'))
    lines=['# ColNomic raw-page comparison','','24 questions / 518 pages, exact frozen corpus. No graph expansion.','',
           '| Method | Recall@5 | nDCG@5 | RecallAll@5 | mAP@5 | mAP full |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name,m in [('ColNomic-7B original pages',metrics['macro_six_types'])]+list(frozen['arms'].items()):
        ap_row=macro_ap if name=='ColNomic-7B original pages' else baseline_ap[name]
        lines.append('| '+name+' | '+' | '.join(f'{m[k]*100:.2f}%' for k in ['Recall@5','nDCG@5','RecallAll@5'])+' | '+' | '.join(f'{ap_row[k]*100:.2f}%' for k in ['AP@5','AP_full'])+' |')
    lines+=['','ColNomic AP (denominator: all relevant pages): '+json.dumps(macro_ap),
            'Small selected pilot, not author full-corpus score. Loading and input provenance: execution.json and manifest.json.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(read(out/'comparison.json'),flush=True)


def run(out,max_seconds=3000):
    check(out)
    import torch
    from PIL import Image
    from colpali_engine.models import ColQwen2_5,ColQwen2_5_Processor
    from peft import PeftModel,get_peft_model_state_dict
    from peft.utils.save_and_load import load_peft_weights
    if not torch.cuda.is_available():raise RuntimeError('CUDA required; do not fall back to CPU')
    started=time.monotonic();torch.set_num_threads(8)
    protocol=read(out/'protocol.json');pages=list(rows(out/'pages.jsonl'));queries=list(rows(out/'queries.jsonl'))
    base,loading=ColQwen2_5.from_pretrained(str(BASE),local_files_only=True,dtype=torch.bfloat16,
        device_map='cuda:0',attn_implementation='sdpa',output_loading_info=True)
    if loading.get('missing_keys') or loading.get('mismatched_keys'):raise RuntimeError('base checkpoint incomplete: '+str(loading))
    # Generation head may exist in the base but is unused by a retrieval encoder.
    if any(k!='lm_head.weight' for k in loading.get('unexpected_keys',[])):raise RuntimeError('unexpected base weights: '+str(loading))
    loading=serializable_loading_info(loading)
    expected=load_peft_weights(str(MODEL),device='cpu',key_mapping=base._checkpoint_conversion_mapping)
    model=PeftModel.from_pretrained(base,str(MODEL),is_trainable=False,local_files_only=True,autocast_adapter_dtype=False).eval()
    actual=get_peft_model_state_dict(model,save_embedding_layers=False)
    if set(actual)!=set(expected):raise RuntimeError('adapter keys not fully loaded')
    if any(not torch.equal(actual[k].detach().cpu(),expected[k].to(actual[k].dtype)) for k in actual):raise RuntimeError('adapter values changed or missing')
    del expected,actual
    if {str(p.device) for p in model.parameters()}!={'cuda:0'}:raise RuntimeError('unexpected CPU/offload placement')
    processor=ColQwen2_5_Processor.from_pretrained(str(MODEL),local_files_only=True,max_num_visual_tokens=1280)
    write(out/'execution.json',dict(slurm_job_id=__import__('os').environ.get('SLURM_JOB_ID'),
        gpu=torch.cuda.get_device_name(0),parameter_devices=['cuda:0'],base_loading=loading,
        adapter_weights_verified=True,adapter_tensors=len(get_peft_model_state_dict(model,save_embedding_layers=False)),
        versions={p:importlib.metadata.version(p) for p in ['torch','transformers','peft']},
        processor_max_pixels=processor.image_processor.max_pixels,query_prefix=processor.query_prefix,
        query_augmentation_token=processor.query_augmentation_token,visual_prefix=processor.visual_prompt_prefix))
    if (out/'queries.pt').exists():qemb=torch.load(out/'queries.pt',map_location='cpu',weights_only=True)
    else:
        qemb=[]
        for i in range(0,len(queries),4):
            batch=processor.process_queries([q['question'] for q in queries[i:i+4]]).to('cuda:0')
            with torch.inference_mode():emb=model(**batch)
            for e in emb:
                if not torch.isfinite(e).all():raise RuntimeError('nonfinite query vector')
                qemb.append(e.detach().cpu())
        torch.save(qemb,out/'queries.pt')
    dest=out/'page_embeddings';dest.mkdir(exist_ok=True)
    order=protocol['smoke_indices']+[i for i in range(len(pages)) if i not in protocol['smoke_indices']]
    for count,i in enumerate(order,1):
        path=dest/f'{i:04d}.pt'
        if not path.exists():
            if time.monotonic()-started>max_seconds:
                write(out/'status.json',dict(complete=False,reason='time_budget',pages_completed=len(list(dest.glob('*.pt')))))
                return
            with Image.open(pages[i]['image_path']) as image:batch=processor.process_images([image.convert('RGB')]).to('cuda:0')
            with torch.inference_mode():emb=model(**batch)[0]
            if not torch.isfinite(emb).all() or emb.ndim!=2 or emb.shape[-1]!=128:raise RuntimeError('invalid page embedding')
            torch.save(emb.detach().cpu(),path)
        if count==len(protocol['smoke_indices']):write(out/'smoke.json',dict(passed=True,pages=protocol['smoke_indices']))
        if count%10==0:print('pages_completed',count,len(pages),'elapsed',round(time.monotonic()-started,1),flush=True)
    scores=[]
    for start in range(0,len(pages),16):
        embs=[torch.load(dest/f'{i:04d}.pt',map_location='cpu',weights_only=True) for i in range(start,min(start+16,len(pages)))]
        values=processor.score_multi_vector(qemb,embs,batch_size=4,device='cuda:0')
        if not torch.isfinite(values).all():raise RuntimeError('nonfinite retrieval score')
        for qi,q in enumerate(queries):
            for j,p in enumerate(pages[start:start+16]):scores.append(dict(question_id=q['question_id'],document_id=p['document_id'],page_number=p['page_number'],score=float(values[qi,j])))
    jsonl(out/'scores.jsonl',scores);report(out)
    write(out/'status.json',dict(complete=True,pages_completed=len(pages),elapsed_seconds=time.monotonic()-started))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','report']);p.add_argument('--output',type=Path,default=OUT)
    a=p.parse_args();{'prepare':prepare,'run':run,'report':report}[a.command](a.output)
