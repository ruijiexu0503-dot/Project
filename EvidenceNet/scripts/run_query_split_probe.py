"""Query-only, hand-split one-case diagnostic; frozen corpus, no new edges.

Gold is opened only by report(). This is a previously inspected development
case, NOT a general automatic splitter or a held-out aggregate evaluation.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from run_node_context_edges import rows, read, write, jsonl
from evaluate_vldocir import page, metrics
from evaluate_vldocir_ap import average_precision
from retrieve_vldocir import query_model_input

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'migration/vldocir_trace_inputs_20261023'
QID = '4ba09a15-c394-4b0c-b9c4-3307beec5a61'
SUBQUERIES = [
    'What is the maximum intrinsic outflow velocity measured in the warm H₂ gas of NGC 3256?',
    'What is the central value of the best H₀ measurement from the SN H0pe study?',
]
DEFAULT_MODEL = ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B'
DEFAULT_OUT = ROOT/'EvidenceNet/output/vldocir_query_split_probe_v1_20261028'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def merge_round_robin(rankings, budget):
    if budget < 1 or not rankings: raise ValueError('positive budget and rankings required')
    selected=[]; seen=set(); paths=[]
    for rank in range(max(map(len,rankings))):
        for branch, ranking in enumerate(rankings):
            if rank >= len(ranking): continue
            target=ranking[rank]
            if target in seen: continue
            selected.append(target);seen.add(target)
            paths.append(dict(page=target,branch=branch,branch_rank=rank+1,merged_rank=len(selected)))
            if len(selected)==budget:return selected,paths
    return selected,paths


def prepare(out,model):
    if out.exists():raise ValueError('fresh output required')
    from tokenizers import Tokenizer
    tokenizer=Tokenizer.from_file(str(model/'tokenizer.json'))
    queries=rows(SOURCE/'queries.jsonl')
    qi=next(i for i,q in enumerate(queries) if q['question_id']==QID)
    question=queries[qi]['question']
    texts=[question]+SUBQUERIES
    tokens=[tokenizer.encode(query_model_input({'question':q})).ids for q in texts]
    assert tokens[0]==rows(SOURCE/'query_tokens.jsonl')[qi]['input_ids'], 'query tokenizer contract differs'
    assert all(len(t)<=512 for t in tokens)
    jsonl(out/'queries.jsonl',[dict(branch=i,question=q,input_ids=t) for i,(q,t) in enumerate(zip(texts,tokens))])
    write(out/'protocol.json',dict(question_id=QID,split_method='manual query-only clauses; inspected development case',
        queries=texts,corpus_pages=518,windows=10301,candidate_budget=20,per_page_windows=2,
        fusion='round-robin original/sub1/sub2, deduplicated, no label-based selection',
        reranking='shared original-query top2 windows; original-query BGE control; separate three-query RRF60 diagnostic',
        edges_changed=False,query_split_only=True,no_answer_or_gold_in_generation=True))
    sources=['queries.jsonl','query_tokens.jsonl','units.jsonl','windows.jsonl','window_tokens.jsonl']
    write(out/'manifest.json',dict(sources={n:sha(SOURCE/n) for n in sources},
        prepared={n:sha(out/n) for n in ['queries.jsonl','protocol.json']},
        model={n:sha(model/n) for n in ['config.json','tokenizer.json','model.safetensors']},
        code={n:sha(Path(__file__).with_name(n)) for n in [Path(__file__).name,'run_cached_query_reranker.py','evaluate_vldocir.py','evaluate_vldocir_ap.py','retrieve_vldocir.py']}))
    write(out/'status.json',dict(stage='prepared',complete=False))


def check(out,model=None):
    m=read(out/'manifest.json')
    for n,d in m['sources'].items():
        if sha(SOURCE/n)!=d:raise ValueError('changed source '+n)
    for n,d in m['prepared'].items():
        if sha(out/n)!=d:raise ValueError('changed protocol '+n)
    for n,d in m['code'].items():
        if sha(Path(__file__).with_name(n))!=d:raise ValueError('changed code '+n)
    if model:
        for n,d in m['model'].items():
            if sha(model/n)!=d:raise ValueError('changed model '+n)


def encode(out,model,minutes):
    check(out,model)
    if minutes <= 0:raise ValueError('positive time budget required')
    import torch
    from transformers import AutoModel, AutoTokenizer
    if not torch.cuda.is_available():raise RuntimeError('GPU allocation required; do not run on login CPU')
    if (out/'scores.npy').exists() and (out/'encoding.json').exists():
        if sha(out/'scores.npy')!=read(out/'encoding.json')['sha256']:raise ValueError('changed score cache')
        return
    tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True,padding_side='left')
    net=AutoModel.from_pretrained(model,local_files_only=True,torch_dtype=torch.bfloat16).cuda().eval()
    def vectors(records):
        batch=tokenizer.pad({'input_ids':[r['input_ids'] for r in records]},padding=True,return_tensors='pt').to('cuda')
        with torch.inference_mode():
            result=net(**batch).last_hidden_state[:,-1].float()
            return torch.nn.functional.normalize(result,p=2,dim=1).cpu().numpy()
    qv=vectors(rows(out/'queries.jsonl')); records=rows(SOURCE/'window_tokens.jsonl')
    assert len(records)==10301
    chunks=out/'encoding_chunks';chunks.mkdir(exist_ok=True)
    start=time.monotonic(); pieces=[]; document_pieces=[]
    for i in range(0,len(records),16):
        path=chunks/f'vectors_{i:05d}.npy'; stamp=chunks/f'vectors_{i:05d}.json'
        if path.exists() and stamp.exists():
            if sha(path)!=read(stamp)['sha256']:raise ValueError('changed encoding chunk')
            document_vectors=np.load(path,allow_pickle=False)
        else:
            if time.monotonic()-start>minutes*60:
                write(out/'status.json',dict(stage='encode_partial',complete=False,windows=i,total=len(records)))
                raise SystemExit(75)
            document_vectors=vectors(records[i:i+16])
            np.save(path,document_vectors);write(stamp,dict(sha256=sha(path)))
        assert document_vectors.shape==(min(16,len(records)-i),qv.shape[1])
        score=qv@document_vectors.T
        assert score.shape==(3,min(16,len(records)-i)) and np.isfinite(score).all()
        pieces.append(score);document_pieces.append(document_vectors)
        if i%512==0:print(f'Encoded {i}/{len(records)}',flush=True)
    np.save(out/'document_vectors.npy',np.concatenate(document_pieces))
    np.save(out/'query_vectors.npy',qv)
    np.save(out/'scores.npy',np.concatenate(pieces,axis=1))
    write(out/'encoding.json',dict(sha256=sha(out/'scores.npy'),device=torch.cuda.get_device_name(),
        document_vectors_sha256=sha(out/'document_vectors.npy'),query_vectors_sha256=sha(out/'query_vectors.npy'),
        document_vectors_query_independent=True,
        dtype='bfloat16',batch=16,matched_control_recomputed=True))
    write(out/'status.json',dict(stage='encoded',complete=False))


def select(out,model):
    check(out)
    from tokenizers import Tokenizer
    if sha(model/'tokenizer.json')!=read(out/'manifest.json')['model']['tokenizer.json']:raise ValueError('changed tokenizer')
    tokenizer=Tokenizer.from_file(str(model/'tokenizer.json'))
    if sha(out/'scores.npy')!=read(out/'encoding.json')['sha256']:raise ValueError('changed scores')
    sim=np.load(out/'scores.npy',allow_pickle=False)
    units=rows(SOURCE/'units.jsonl'); windows=rows(SOURCE/'windows.jsonl'); tokens=rows(SOURCE/'window_tokens.jsonl')
    per_page=defaultdict(list)
    for wi,w in enumerate(windows):per_page[page(units[w['unit_input_line']-1])].append(wi)
    assert len(per_page)==518 and sim.shape==(3,len(windows))
    ranks=[sorted(per_page,key=lambda p:(-float(sim[i,per_page[p]].max()),p)) for i in range(3)]
    split,paths=merge_round_robin(ranks,20)
    selected={'original':ranks[0][:20],'split':split}
    write(out/'selection.json',dict(selected=selected,branch_rankings=ranks,paths=paths))
    q=rows(out/'queries.jsonl'); inputs=[]; evidence=[]
    for p in sorted(set(selected['original'])|set(split)):
        # Same evidence selection for every arm: isolates candidate versus reranker changes.
        ids=sorted(per_page[p],key=lambda wi:(-float(sim[0,wi]),wi))[:2]
        for wi in ids:
            text=tokenizer.decode(tokens[wi]['input_ids'],skip_special_tokens=True)
            for branch in range(3):
                rid=hashlib.sha256(json.dumps([q[branch]['question'],wi]).encode()).hexdigest()
                inputs.append(dict(id=rid,query=q[branch]['question'],text=text))
                evidence.append(dict(id=rid,page=p,branch=branch,window_input_line=wi+1))
    jsonl(out/'reranker_inputs.jsonl',inputs);jsonl(out/'evidence.jsonl',evidence)
    write(out/'selection_manifest.json',{n:sha(out/n) for n in ['selection.json','reranker_inputs.jsonl','evidence.jsonl']})
    write(out/'status.json',dict(stage='reranker_ready',complete=False,reranker_total=len(inputs)))


def report(out):
    check(out)
    from run_cached_query_reranker import load_inputs,load_scores
    for n,d in read(out/'selection_manifest.json').items():
        if sha(out/n)!=d:raise ValueError('changed selection '+n)
    scores=load_scores(out/'reranker_scores.jsonl',load_inputs(out/'reranker_inputs.jsonl'),require_complete=True)
    lookup={r['id']:r['score'] for r in scores}; evidence=rows(out/'evidence.jsonl')
    per=defaultdict(list)
    for r in evidence:per[r['branch'],tuple(r['page'])].append(lookup[r['id']])
    s=read(out/'selection.json'); candidates={k:list(map(tuple,v)) for k,v in s['selected'].items()}
    ranked={k:sorted(v,key=lambda p:(-max(per[0,p]),p)) for k,v in candidates.items()}
    subrank=[sorted(candidates['split'],key=lambda p:(-max(per[b,p]),p)) for b in range(3)]
    rrf={p:sum(1/(60+r.index(p)+1) for r in subrank) for p in candidates['split']}
    ranked['split_rerank_rrf60']=sorted(candidates['split'],key=lambda p:(-rrf[p],p))
    # Official gold is accessed only here, after all candidate/ranking choices.
    gold_file=SOURCE/'gold_evidence.jsonl'
    gold={page(r) for r in rows(gold_file) if r['question_id']==QID}
    assert gold and gold<=set(map(tuple,s['branch_rankings'][0]))
    results={}
    for name,rank in ranked.items():
        results[name]=dict(metrics={**metrics(rank,gold,5),**metrics(rank,gold,20),'AP@5':average_precision(rank,gold,5)},
            top5=rank[:5],gold_ranks=[dict(page=p,rank=rank.index(p)+1 if p in rank else None) for p in sorted(gold)])
    dense_gold=[dict(page=p,branch_ranks=[list(map(tuple,r)).index(p)+1 for r in s['branch_rankings']]) for p in sorted(gold)]
    result=dict(complete=True,protocol=read(out/'protocol.json'),results=results,dense_gold_ranks=dense_gold,
        gold_sha256=sha(gold_file),note='One manually split development query. No aggregate/generalization claim; no edge gain claim.')
    write(out/'results.json',result);write(out/'status.json',dict(stage='complete',complete=True))
    (out/'REPORT.md').write_text('# Query split 单例对照\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['prepare','encode','select','report','check'])
    ap.add_argument('--output',type=Path,default=DEFAULT_OUT)
    ap.add_argument('--model',type=Path,default=DEFAULT_MODEL)
    ap.add_argument('--minutes',type=float,default=35)
    a=ap.parse_args()
    if a.stage=='prepare':prepare(a.output,a.model)
    elif a.stage=='encode':encode(a.output,a.model,a.minutes)
    elif a.stage=='select':select(a.output,a.model)
    elif a.stage=='report':report(a.output)
    else:check(a.output,a.model)


if __name__=='__main__':main()
