#!/usr/bin/env python3
"""Frozen Qwen3 embeddings + supervised DynamicEdgeRanker pilot fit."""
from __future__ import annotations
import argparse, hashlib, json, math, random, sys, time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F

SRC=Path(__file__).resolve().parent
REPO_ROOT=SRC.parents[2]
sys.path.insert(0,str(SRC))
from model import DynamicEdgeConfig, DynamicEdgeRanker
from losses import masked_auxiliary_cross_entropy, multi_positive_ranking_loss
from checkpoint import save_checkpoint

def load_tokenizer(model_path, padding_side):
    from transformers import AutoTokenizer, PreTrainedTokenizerFast
    try:
        return AutoTokenizer.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=True,
            padding_side=padding_side)
    except ImportError:
        tokenizer_file = Path(model_path) / "tokenizer.json"
        config_file = Path(model_path) / "tokenizer_config.json"
        if not tokenizer_file.exists() or not config_file.exists():
            raise
        config=json.loads(config_file.read_text())
        special={key: config[key] for key in
                 ("bos_token","eos_token","unk_token","pad_token") if config.get(key)}
        tokenizer=PreTrainedTokenizerFast(tokenizer_file=str(tokenizer_file),**special)
        tokenizer.padding_side=padding_side
        tokenizer.model_max_length=config.get("model_max_length", tokenizer.model_max_length)
        return tokenizer

def pool_hidden(hidden, attention_mask, strategy):
    if strategy=="cls":
        return hidden[:,0]
    if strategy=="last_token":
        last=attention_mask.sum(dim=1)-1
        if attention_mask[:,-1].all():
            return hidden[:,-1]
        index=last[:,None,None].expand(-1,1,hidden.shape[-1])
        return hidden.gather(1,index).squeeze(1)
    if strategy=="mean":
        mask=attention_mask.unsqueeze(-1).to(hidden.dtype)
        return (hidden*mask).sum(dim=1)/mask.sum(dim=1).clamp_min(1)
    raise ValueError("unknown pooling strategy: "+strategy)

def rows(p): return [json.loads(x) for x in p.open(encoding="utf-8") if x.strip()]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def embed(texts, model_path, batch, device):
    from transformers import AutoModel
    tok=load_tokenizer(model_path,"left")
    kw=dict(local_files_only=True,trust_remote_code=True,torch_dtype=torch.bfloat16)
    try: model=AutoModel.from_pretrained(model_path,attn_implementation="sdpa",**kw)
    except (TypeError,ValueError): model=AutoModel.from_pretrained(model_path,**kw)
    model=model.to(device).eval(); out=[]
    for i in range(0,len(texts),batch):
        x=tok(texts[i:i+batch],padding=True,truncation=True,max_length=512,return_tensors="pt").to(device)
        with torch.inference_mode():
            f=dict(x)
            if getattr(model.config,"use_cache",None) is not None: f["use_cache"]=False
            h=model(**f).last_hidden_state
            z=F.normalize(pool_hidden(h,x["attention_mask"],"last_token").float(),p=2,dim=1)
        out.append(z.cpu())
    del model; torch.cuda.empty_cache(); return torch.cat(out)

def node_table(records):
    nodes={}
    for r in records:
        for e in r["gold_evidence_draft"]:
            nodes[e["canonical_node_id"]]={"id":e["canonical_node_id"],"text":e["evidence_text"],"doc":e["document_id"],"page":e["page_number"],"type":e["node_type"]}
    return nodes

def route_features(selected,candidates,node_meta,qsim,node_vec):
    R=max(1,len(selected)); C=len(candidates); feat=torch.zeros(C,R,12); mask=torch.zeros(C,R,dtype=torch.bool)
    for ci,t in enumerate(candidates):
        tm=node_meta[t]
        for ri,s in enumerate(selected):
            sm=node_meta[s]; delta=tm["page"]-sm["page"]; mask[ci,ri]=True
            feat[ci,ri]=torch.tensor([float(qsim[ci]),0.0,float(sm["type"]==tm["type"]),0.0,1.0,float(sm["doc"]==tm["doc"]),float(sm["doc"]==tm["doc"] and sm["page"]==tm["page"]),max(-1,min(1,delta/50)),float(sm["doc"]==tm["doc"]),1/(ri+1),1.0,len(selected)/5.0])
    return feat,mask

def gain_labels_for_state(gold,candidates,selected):
    gold_set=set(gold)
    selected_set=set(selected)
    gain_labels=torch.tensor([0]*len(candidates),dtype=torch.long)
    gain_mask=torch.zeros(len(candidates),dtype=torch.bool)
    for ci,candidate in enumerate(candidates):
        if candidate not in gold_set or candidate in selected_set:
            continue
        gain_mask[ci]=True
        candidate_set=selected_set|{candidate}
        gain_labels[ci]=2 if candidate_set==gold_set else 1
    return gain_labels,gain_mask

def make_samples(records,node_ids,node_index,node_vec,query_vec,negatives=48):
    samples=[]; sims=query_vec@node_vec.T
    for qi,r in enumerate(records):
        gold=[e["canonical_node_id"] for e in r["gold_evidence_draft"]]
        ranked=torch.argsort(sims[qi],descending=True).tolist()
        neg=[node_ids[j] for j in ranked if node_ids[j] not in gold][:negatives]
        for step in range(len(gold)):
            selected=gold[:step]; positive=gold[step:]; candidates=positive+neg
            gain_labels,gain_mask=gain_labels_for_state(gold,candidates,selected)
            samples.append((qi,selected,candidates,set(positive),sims[qi,[node_index[x] for x in candidates]],gain_labels,gain_mask))
    return samples

def forward_sample(model,sample,qvec,node_ids,node_index,node_meta,node_vec,device):
    qi,selected,candidates,positive,qsim=sample[:5]; C=len(candidates); S=len(selected); R=max(1,S)
    cand=node_vec[[node_index[x] for x in candidates]].to(device)
    sel=node_vec[[node_index[x] for x in selected]].to(device) if S else torch.empty(0,node_vec.shape[1],device=device)
    source=torch.zeros(1,C,R,node_vec.shape[1],device=device)
    if S:
        source[0,:,:S]=sel.unsqueeze(0).expand(C,S,-1)
    rf,rm=route_features(selected,candidates,node_meta,qsim,node_vec)
    result=model(query_embedding=qvec[qi:qi+1].to(device),selected_content=sel.unsqueeze(0),selected_mask=torch.ones(1,S,dtype=torch.bool,device=device),target_content=cand.unsqueeze(0),source_content=source,route_features=rf.unsqueeze(0).to(device),route_mask=rm.unsqueeze(0).to(device),candidate_mask=torch.ones(1,C,dtype=torch.bool,device=device),dense_similarity=qsim.unsqueeze(0).to(device),dense_similarity_mask=torch.ones(1,C,dtype=torch.bool,device=device),context_mask=torch.zeros(1,C,dtype=torch.bool,device=device),return_diagnostics=False)
    pos=torch.tensor([[x in positive for x in candidates]],dtype=torch.bool,device=device); neg=~pos
    if len(sample)>=7:
        gain_labels=sample[5].unsqueeze(0).to(device)
        gain_mask=sample[6].unsqueeze(0).to(device)
    else:
        gain_labels=torch.zeros(1,C,dtype=torch.long,device=device)
        gain_mask=torch.zeros(1,C,dtype=torch.bool,device=device)
    return result["scores"],pos,neg,gain_labels,gain_mask,result

def evaluate(model,records,node_ids,node_index,node_meta,node_vec,qvec,device):
    model.eval(); totals=CounterLike(); sims=qvec@node_vec.T
    with torch.inference_mode():
        for qi,r in enumerate(records):
            gold={e["canonical_node_id"] for e in r["gold_evidence_draft"]}; ranked=torch.argsort(sims[qi],descending=True).tolist(); candidates=[node_ids[j] for j in ranked]
            sample=(qi,[],candidates,gold,sims[qi,ranked]); scores,*_=forward_sample(model,sample,qvec,node_ids,node_index,node_meta,node_vec,device)
            dense_rank=candidates; learned=[candidates[j] for j in torch.argsort(scores[0],descending=True).tolist()]
            for k in (1,5,10):
                totals[f"dense_r{k}"]+=len(gold & set(dense_rank[:k]))/len(gold); totals[f"model_r{k}"]+=len(gold & set(learned[:k]))/len(gold)
            totals["n"]+=1
    return {k:(v/totals["n"] if k!="n" else int(v)) for k,v in totals.items()}

class CounterLike(dict):
    def __missing__(self,k): return 0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); ap.add_argument("--model",type=Path,required=True); ap.add_argument("--epochs",type=int,default=12); ap.add_argument("--seed",type=int,default=17); ap.add_argument("--batch-size",type=int,default=64); ap.add_argument("--enable-a-head",action="store_true"); ap.add_argument("--gain-weight",type=float,default=0.2); a=ap.parse_args()
    if a.gain_weight<0:
        raise ValueError("--gain-weight must be non-negative")
    a.out.mkdir(parents=True,exist_ok=True); random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed); device="cuda"
    train,test=rows(a.data/"train.jsonl"),rows(a.data/"test.jsonl"); allr=train+test
    train_nodes=node_table(train); test_nodes=node_table(test); all_nodes={**train_nodes,**test_nodes}
    node_ids=sorted(all_nodes); node_index={x:i for i,x in enumerate(node_ids)}; texts=[all_nodes[x]["text"] for x in node_ids]
    questions=[r["question"] for r in allr]
    node_vec=embed(texts,a.model,a.batch_size,device); query_vec=embed(questions,a.model,a.batch_size,device)
    torch.save({"node_ids":node_ids,"node_vectors":node_vec,"query_vectors":query_vec},a.out/"frozen_embeddings.pt")
    train_node_ids=sorted(train_nodes); ti=[node_index[x] for x in train_node_ids]; train_vec=node_vec[ti]; train_index={x:i for i,x in enumerate(train_node_ids)}
    train_q=query_vec[:len(train)]; test_q=query_vec[len(train):]
    samples=make_samples(train,train_node_ids,train_index,train_vec,train_q)
    cfg=DynamicEdgeConfig(input_dim=node_vec.shape[1],context_dim=node_vec.shape[1],dim=128,hidden=256,dropout=.1,output_k=5,enable_a_head=a.enable_a_head)
    net=DynamicEdgeRanker(config=cfg).to(device); opt=torch.optim.AdamW(net.parameters(),lr=2e-4,weight_decay=.01)
    test_node_ids=sorted(test_nodes)
    xi=[node_index[x] for x in test_node_ids]
    test_vec=node_vec[xi]
    test_index={x:i for i,x in enumerate(test_node_ids)}
    untrained_metrics=evaluate(net,test,test_node_ids,test_index,test_nodes,test_vec,test_q,device)
    history=[]; started=time.time()
    for epoch in range(1,a.epochs+1):
        random.shuffle(samples); net.train(); running=0
        gain_valid_total=0
        for sample in samples:
            scores,pos,neg,gain_labels,gain_mask,result=forward_sample(net,sample,train_q,train_node_ids,train_index,train_nodes,train_vec,device)
            rank_loss,_=multi_positive_ranking_loss(scores,pos,neg)
            if a.enable_a_head:
                gain_loss,gain_info=masked_auxiliary_cross_entropy(
                    result["a_logits"],gain_labels,gain_mask
                )
                gain_valid_total+=gain_info["valid_labels"]
                loss=rank_loss+a.gain_weight*gain_loss
            else:
                loss=rank_loss
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1.0)
            opt.step()
            running+=loss.item()
        row={"epoch":epoch,"loss":running/len(samples),"a_head_enabled":a.enable_a_head,
             "gain_weight":a.gain_weight,"gain_labels_seen":gain_valid_total}
        history.append(row); print(json.dumps(row),flush=True)
    trained_metrics=evaluate(net,test,test_node_ids,test_index,test_nodes,test_vec,test_q,device)
    metadata={"encoder_hash":sha(a.model/"config.json"),"graph_hash":sha(a.data/"split_manifest.json"),"data_hash":sha(a.data/"train.jsonl"),"random_seed":a.seed,"epochs":a.epochs,"train_samples":len(samples),"a_head_enabled":a.enable_a_head,"gain_weight":a.gain_weight,"gain_label_policy":"gold_completion_v1; non-gold candidates unknown"}
    save_checkpoint(a.out/"final_checkpoint.pt",net,metadata=metadata,optimizer=opt)
    report={"status":"complete","train_queries":len(train),"test_queries":len(test),"train_states":len(samples),"untrained_metrics":untrained_metrics,"trained_metrics":trained_metrics,"metrics":trained_metrics,"history":history,"elapsed_seconds":time.time()-started,"encoder":str(a.model),"encoder_frozen":True,"test_evaluated_once_before_training":True,"test_evaluated_once_after_training":True,"a_head_enabled":a.enable_a_head,"gain_weight":a.gain_weight,"gain_label_policy":"gold_completion_v1; non-gold candidates unknown"}
    (a.out/"training_report.json").write_text(json.dumps(report,indent=2)+"\n"); print(json.dumps(report,indent=2))
if __name__=="__main__": main()
