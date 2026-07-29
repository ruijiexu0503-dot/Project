from __future__ import annotations

import argparse
import html
import json
import math
import re
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl, write_json

ANAPHOR = re.compile(r"^\s*(?:these|this|those|such|they|it|the former|the latter)\b", re.I)
PLACEHOLDER = re.compile(r"^\s*(?:image|figure|photo|page\s*\d+)\s*$", re.I)
NON_TITLE = re.compile(r"^(?:fig(?:ure)?\.?\s*\d+|table\s*\d+|volume\s+\d+|cern courier|january|february|www\.|https?://)", re.I)


def quantile(values, q):
    values = sorted(values)
    if not values: return 0.0
    pos = (len(values) - 1) * q; lo = int(pos); hi = min(len(values) - 1, lo + 1)
    if lo == hi: return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def mean(values): return sum(values) / len(values) if values else 0.0


def median(values): return quantile(values, .5)


def embed(texts, model_path, batch_size=12):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModel.from_pretrained(model_path, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
    rows = []
    for offset in range(0, len(texts), batch_size):
        batch = tokenizer(texts[offset:offset + batch_size], padding=True, truncation=True,
                          max_length=512, return_tensors="pt")
        batch = {k: v.cuda() for k, v in batch.items()}
        with torch.inference_mode(): hidden = model(**batch).last_hidden_state.float()
        mask = batch["attention_mask"].unsqueeze(-1); pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        rows.extend(pooled.cpu().tolist())
    return rows


def cosine(a, b): return sum(x*y for x, y in zip(a, b))


def unit_sizes(count, boundaries):
    cuts = [-1] + sorted(boundaries) + [count - 1]
    return [cuts[i + 1] - cuts[i] for i in range(len(cuts) - 1)]


def title_anchors(nodes):
    """High-precision, layout-independent title baseline."""
    boundaries=set()
    for i,node in enumerate(nodes[:-1]):
        text=" ".join(node.get("plain_text","").split()).strip(); words=re.findall(r"[A-Za-z][A-Za-z0-9'-]*",text)
        if not 1<=len(words)<=14 or len(text)>120 or NON_TITLE.search(text) or text.endswith(('.',':',';','?','!')):
            continue
        letters=[c for c in text if c.isalpha()]
        upper_ratio=sum(c.isupper() for c in letters)/max(1,len(letters))
        title_case=sum(w[:1].isupper() for w in words)/len(words)
        title_like=upper_ratio>=.72 or title_case>=.75
        next_text=" ".join(nodes[i+1].get("plain_text","").split())
        # A short byline may intervene between title and substantial body prose.
        following_long=len(next_text)>=180
        if not following_long and i+2<len(nodes) and len(next_text)<100:
            following_long=len(" ".join(nodes[i+2].get("plain_text","").split()))>=180
        if i and title_like and following_long and not PLACEHOLDER.match(text):
            boundaries.add(i-1)
    return {x for x in boundaries if x>=0}


def analyze(doc_id, root, model_path):
    out = root / doc_id; nodes = sorted(read_jsonl(out / "evidence_nodes.jsonl"), key=lambda n:n["document_order"])
    texts = [n.get("plain_text", "") or "[empty]" for n in nodes]
    vectors = embed(texts, model_path); sims = [cosine(a,b) for a,b in zip(vectors,vectors[1:])]
    meaningful = [s for i,s in enumerate(sims) if not PLACEHOLDER.match(texts[i]) and not PLACEHOLDER.match(texts[i+1])]
    raw_threshold = quantile(meaningful, .10)
    raw = {i for i,s in enumerate(sims) if s <= raw_threshold and not PLACEHOLDER.match(texts[i+1])}
    smooth = [median(sims[max(0,i-3):min(len(sims),i+4)]) for i in range(len(sims))]
    prominence=[]
    for i,s in enumerate(sims):
        left=mean(sims[max(0,i-3):i]); right=mean(sims[i+1:min(len(sims),i+4)])
        prominence.append(((left+right)/2)-s if left and right else 0)
    prominence_threshold=max(.08,quantile(prominence,.90))
    trend={i for i,p in enumerate(prominence) if p>=prominence_threshold
           and mean(sims[i+1:min(len(sims),i+4)])>sims[i]
           and not PLACEHOLDER.match(texts[i+1])}
    checkpoint=read_jsonl(out/"content_unit_checkpoint.jsonl") if (out/"content_unit_checkpoint.jsonl").exists() else []
    ids={n["node_id"]:i for i,n in enumerate(nodes)}
    llm={ids[r["left_id"]] for r in checkpoint if r.get("decision")=="STARTS_NEW_CONTENT_UNIT" and r.get("left_id") in ids}
    hybrid={i for i in trend if i in llm} | {i for i in trend if prominence[i]>=max(.16,prominence_threshold*1.5)}
    titles=title_anchors(nodes)
    title_trend=titles | {i for i in trend if prominence[i]>=max(.18,prominence_threshold*1.75)}
    methods={"title_only":titles,"raw_threshold":raw,"smoothed_trend":trend,"llm_only":llm,
             "hybrid":hybrid,"title_plus_strong_trend":title_trend}
    diagnostics={}
    for name,bounds in methods.items():
        sizes=unit_sizes(len(nodes),bounds)
        diagnostics[name]={"boundaries":len(bounds),"units":len(sizes),"median_unit_size":median(sizes),
            "tiny_units_le_2":sum(x<=2 for x in sizes),
            "anaphoric_boundary_violations":sum(bool(ANAPHOR.search(texts[i+1])) for i in bounds)}
    return {"doc_id":doc_id,"node_count":len(nodes),"raw_threshold":raw_threshold,
            "prominence_threshold":prominence_threshold,"similarities":sims,"smoothed":smooth,
            "prominence":prominence,"methods":{k:sorted(v) for k,v in methods.items()},"diagnostics":diagnostics,
            "boundary_examples":{k:[{"left":nodes[i]["node_id"],"right":nodes[i+1]["node_id"],
                "similarity":round(sims[i],4),"prominence":round(prominence[i],4),
                "right_text":texts[i+1][:100]} for i in sorted(v)[:30]] for k,v in methods.items()}}


def report(results, target):
    rows=[]
    for r in results:
        for method,d in r["diagnostics"].items():
            rows.append(f"<tr><td>{html.escape(r['doc_id'])}</td><td>{method}</td><td>{d['boundaries']}</td>"
                        f"<td>{d['median_unit_size']:.1f}</td><td>{d['tiny_units_le_2']}</td>"
                        f"<td>{d['anaphoric_boundary_violations']}</td></tr>")
    target.write_text("""<!doctype html><meta charset='utf-8'><title>Boundary method comparison</title>
<style>body{font:14px system-ui;margin:28px;background:#0b1020;color:#e9eef9}table{border-collapse:collapse;width:100%}th,td{border:1px solid #31405f;padding:8px}th{background:#18233a}</style>
<h1>Content-unit boundary method comparison</h1><p>Lower tiny-unit and anaphoric-boundary counts are better; boundary counts must remain plausible for the document.</p>
<table><tr><th>Document</th><th>Method</th><th>Boundaries</th><th>Median unit size</th><th>Tiny units ≤2</th><th>Anaphoric violations</th></tr>"""+"".join(rows)+"</table>",encoding="utf-8")


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--model",required=True);p.add_argument("--docs",nargs="+",required=True)
    a=p.parse_args(argv);cfg=load_config(a.config);root=Path(cfg["output"]["graph_root"])
    results=[analyze(d,root,a.model) for d in a.docs]
    write_json(root/"boundary_method_comparison.json",{"model":a.model,"documents":results})
    report(results,root/"boundary_method_comparison.html")
    print(json.dumps({r["doc_id"]:r["diagnostics"] for r in results},indent=2))


if __name__=="__main__": main()
