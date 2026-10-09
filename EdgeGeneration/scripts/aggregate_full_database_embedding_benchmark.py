#!/usr/bin/env python3
"""Aggregate full-database embedding benchmark runs and model disagreements."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def load_json(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def load_jsonl(path): return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,required=True); ap.add_argument("inputs",nargs="+",type=Path)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    models=[]; detail_maps={}
    for folder in args.inputs:
        s=load_json(folder/"summary.json"); models.append({**s,"source":str(folder.resolve())})
        detail_maps[s["model"]]={x["unit_id"]:x for x in load_jsonl(folder/"details.jsonl")}
    models.sort(key=lambda x:x["overall"]["top1"],reverse=True)
    leader=models[0]["model"]
    comparisons=[]
    leader_rows=detail_maps[leader]
    for model in models[1:]:
        other=detail_maps[model["model"]]; lc=[]; oc=[]
        for uid,row in leader_rows.items():
            if row["rank"]==1 and other[uid]["rank"]>1: lc.append(uid)
            if row["rank"]>1 and other[uid]["rank"]==1: oc.append(uid)
        comparisons.append({"leader":leader,"other":model["model"],"leader_only_correct":lc,"other_only_correct":oc})
    result={"experiment":"full-database-embedding-cross-model-v1","leader_by_overall_top1":leader,
            "models":models,"disagreements":comparisons,
            "caveat":"Exact-unit recovery is a cohesion proxy, not relation GT; neighboring GW sections may be semantically related even when counted wrong.",
            "production_modified":False}
    (args.output/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    rows="".join(f"<tr><td>{html.escape(m['model'])}</td><td>{m['overall']['top1']:.3f}</td><td>{m['overall']['recall_at_5']:.3f}</td><td>{m['overall']['mrr']:.3f}</td><td>{m['overall']['mean_margin']:.4f}</td><td>{m['by_kind']['magazine_article']['top1']:.3f}</td><td>{m['by_kind']['paper_section']['top1']:.3f}</td><td>{m['top1_hub_max']}</td></tr>" for m in models)
    disag="".join(f"<tr><td>{html.escape(x['other'])}</td><td>{len(x['leader_only_correct'])}</td><td>{len(x['other_only_correct'])}</td><td>{html.escape(', '.join(x['other_only_correct'][:12]))}</td></tr>" for x in comparisons)
    (args.output/"report.html").write_text(f'''<!doctype html><meta charset="utf-8"><title>Full database embedding benchmark</title><style>body{{font:14px system-ui;margin:24px;color:#172033}}table{{border-collapse:collapse;width:100%;margin:18px 0}}th,td{{border:1px solid #ccd3df;padding:7px;text-align:left;vertical-align:top}}th{{background:#e8eef8}}</style><h1>Full database embedding benchmark</h1><p>94 eligible units: 55 magazine articles and 39 scientific-paper sections. Query and target contain disjoint member blocks/sentences.</p><table><tr><th>Model</th><th>Top-1</th><th>R@5</th><th>MRR</th><th>Margin</th><th>Magazine Top-1</th><th>Paper Top-1</th><th>Max hub</th></tr>{rows}</table><h2>Disagreements against {html.escape(leader)}</h2><table><tr><th>Other model</th><th>Leader only correct</th><th>Other only correct</th><th>Examples where other wins</th></tr>{disag}</table><p><b>Caveat:</b> Exact-section recovery is a cohesion proxy rather than relation gold. Closely related GW paper sections can be reasonable semantic neighbors while counted as incorrect here.</p>''',encoding="utf-8")
    print(json.dumps({"leader":leader,"models":[{"model":m["model"],"overall":m["overall"],"by_kind":m["by_kind"],"hub":m["top1_hub_max"]} for m in models],"disagreements":[{"other":x["other"],"leader_only":len(x["leader_only_correct"]),"other_only":len(x["other_only_correct"])} for x in comparisons]},ensure_ascii=False,indent=2))


if __name__=="__main__": main()
