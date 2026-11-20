#!/usr/bin/env python3
"""CPU model audit on the full disjoint-view article/section benchmark."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def embed(texts, tokenizer, model, pooling, batch_size=4, max_length=512):
    out = []
    for start in range(0, len(texts), batch_size):
        batch = tokenizer(texts[start:start + batch_size], padding=True, truncation=True,
                          max_length=max_length, return_tensors="pt")
        with torch.inference_mode(): hidden = model(**batch).last_hidden_state
        if pooling == "mean":
            mask = batch["attention_mask"].unsqueeze(-1).bool()
            vec = hidden.masked_fill(~mask, 0).sum(1) / mask.sum(1).clamp_min(1)
        elif pooling == "last":
            vec = hidden[:, -1] if bool((batch["attention_mask"][:, -1] == 1).all()) else hidden[torch.arange(hidden.shape[0]), batch["attention_mask"].sum(1)-1]
        else: vec = hidden[:, 0]
        out.append(torch.nn.functional.normalize(vec.float(), p=2, dim=1))
    return torch.cat(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True); ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--model-name", required=True)
    ap.add_argument("--pooling", choices=("cls", "mean", "last"), default="cls")
    ap.add_argument("--query-instruction"); ap.add_argument("--adapter")
    ap.add_argument("--allow-remote-code-fetch", action="store_true")
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(args.input); local_only = not args.allow_remote_code_fetch
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=local_only, trust_remote_code=True,
                                              padding_side="left" if args.pooling == "last" else "right")
    if args.adapter:
        from adapters import AutoAdapterModel
        model = AutoAdapterModel.from_pretrained(args.model, local_files_only=True)
        name = model.load_adapter(args.adapter, load_as="proximity"); model.set_active_adapters(name)
    else:
        model = AutoModel.from_pretrained(args.model, local_files_only=local_only, trust_remote_code=True, dtype=torch.float32)
    model = model.cpu().eval()
    queries = [x["query_text"] for x in rows]
    if args.query_instruction: queries = [f"Instruct: {args.query_instruction}\nQuery: {x}" for x in queries]
    q = embed(queries, tokenizer, model, args.pooling); t = embed([x["target_text"] for x in rows], tokenizer, model, args.pooling)
    scores = q @ t.T; details=[]; ranks=[]; margins=[]; top1_targets=[]; by_kind=defaultdict(list)
    for i,row in enumerate(rows):
        order=torch.argsort(scores[i],descending=True).tolist(); rank=order.index(i)+1
        neg=max(float(scores[i,j]) for j in range(len(rows)) if j!=i); margin=float(scores[i,i])-neg
        ranks.append(rank); margins.append(margin); top1_targets.append(order[0]); by_kind[row["unit_kind"]].append((rank,margin))
        details.append({"unit_id":row["unit_id"],"doc_id":row["doc_id"],"unit_kind":row["unit_kind"],"rank":rank,
                        "positive_similarity":round(float(scores[i,i]),6),"margin":round(margin,6),
                        "top1_unit_id":rows[order[0]]["unit_id"],"top1_doc_id":rows[order[0]]["doc_id"],
                        "top5":[{"unit_id":rows[j]["unit_id"],"score":round(float(scores[i,j]),6)} for j in order[:5]]})
    def metric(vals):
        return {"count":len(vals),"top1":round(sum(r==1 for r,_ in vals)/len(vals),6),
                "recall_at_5":round(sum(r<=5 for r,_ in vals)/len(vals),6),
                "mrr":round(sum(1/r for r,_ in vals)/len(vals),6),"mean_margin":round(sum(m for _,m in vals)/len(vals),6),
                "positive_margin_count":sum(m>0 for _,m in vals)}
    hubs=Counter(top1_targets)
    summary={"model":args.model_name,"pooling":args.pooling,"units":len(rows),"overall":metric(list(zip(ranks,margins))),
             "by_kind":{k:metric(v) for k,v in by_kind.items()},
             "top1_hub_max":max(hubs.values()),"top_hubs":[{"unit_id":rows[i]["unit_id"],"top1_count":n} for i,n in hubs.most_common(10)],
             "production_modified":False}
    (args.output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (args.output/"details.jsonl").open("w",encoding="utf-8") as f:
        for x in details:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
