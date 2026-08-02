from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl


def esc(value): return html.escape(" ".join(str(value or "").split()))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--doc-id",required=True); parser.add_argument("--config",required=True)
    args=parser.parse_args(); config=load_config(args.config); root=Path(config["output"]["graph_root"])/args.doc_id
    nodes={n["node_id"]:n for n in read_jsonl(root/"evidence_nodes.jsonl")}
    segments=read_jsonl(root/"content_item_segments.jsonl"); assignments=read_jsonl(root/"content_item_assignments.jsonl")
    resumptions={r["segment_id"]:r for r in read_jsonl(root/"content_item_resumption_checkpoint.jsonl")}
    boundaries={r["right_id"]:r for r in read_jsonl(root/"content_item_boundary_checkpoint.jsonl") if r.get("right_id")}
    assignment={a["node_id"]:a for a in assignments}; by_item=defaultdict(list)
    for segment in segments:
        first=segment["node_ids"][0]; a=assignment[first]; by_item[a["content_item_id"]].append(segment)
    cards=[]
    for item_id,item_segments in by_item.items():
        kind=assignment[item_segments[0]["node_ids"][0]]["content_kind"]
        segment_html=[]
        for segment in item_segments:
            members=[nodes[n] for n in segment["node_ids"]]; first=members[0]; boundary=boundaries.get(first["node_id"],{})
            resume=resumptions.get(segment["segment_id"],{})
            resumed=resume.get("decision")=="RESUMES_PRIOR_ITEM"
            excerpts=members[:3]+(members[-2:] if len(members)>3 else [])
            rows="".join(f"<div class='node'><b>{esc(n['node_id'].rsplit('_EV_',1)[-1])}</b><span>{esc(', '.join(n.get('page_ids',[])))}</span><p>{esc(n.get('plain_text','')[:650])}</p></div>" for n in excerpts)
            rationale=(resume.get("rationale") if resumed else boundary.get("rationale")) or "Document start"
            badge="<span class='resume'>RESUMED</span>" if resumed else f"<span>{esc(segment['boundary_decision'])}</span>"
            segment_html.append(f"<section class='segment'><h3>{esc(segment['segment_id'])} {badge}</h3>"
                f"<div class='meta'>{len(members)} nodes · {esc(', '.join(segment['pages']))}</div>"
                f"<p class='rationale'>{esc(rationale)}</p><details><summary>Evidence excerpts</summary>{rows}</details></section>")
        cards.append(f"<article class='item {esc(kind)}' data-kind='{esc(kind)}'><header><h2>{esc(item_id)}</h2>"
            f"<span class='kind'>{esc(kind)}</span><span>{len(item_segments)} segment(s)</span></header>{''.join(segment_html)}</article>")
    summary=json.loads((root/"content_item_segmentation_summary.json").read_text())
    target=root/"content_item_review.html"
    target.write_text(f'''<!doctype html><html><head><meta charset="utf-8"><title>Content-item review</title><style>
body{{margin:0;background:#09101f;color:#e8eefc;font:14px/1.45 system-ui}}header.top{{position:sticky;top:0;background:#101a2d;padding:18px 28px;z-index:3;border-bottom:1px solid #304263}}main{{max-width:1200px;margin:auto;padding:20px}}.item{{border:1px solid #344665;border-radius:14px;background:#101a2d;margin:18px 0;padding:16px}}.item>header{{display:flex;gap:12px;align-items:center}}h2{{margin:0}}.kind,.segment h3 span{{padding:3px 8px;border-radius:9px;background:#263958;color:#72d4ee;font-size:12px}}.advertisement{{border-color:#f0a34a}}.advertisement .kind{{background:#5b3b17;color:#ffd395}}.segment{{margin:14px 0 0 20px;border-left:3px solid #3b557d;padding:8px 15px}}.segment h3{{margin:0}}.segment .resume{{background:#174e43;color:#8ff0d2}}.meta{{color:#9facbd}}.rationale{{color:#cbd5e6}}details{{background:#0b1425;padding:9px;border-radius:8px}}summary{{cursor:pointer;color:#65cce9}}.node{{border-top:1px solid #2b3d5b;padding:8px}}.node b{{color:#64d0ea;margin-right:12px}}.node span{{color:#9facbd}}.node p{{margin:4px 0}}select{{background:#17243b;color:#fff;padding:5px}} 
</style></head><body><header class="top"><h1>Direct content-item segmentation review</h1><div>{summary['nodes']} nodes · {summary['segments']} segments · {summary['content_items']} logical items · {summary['standalone_segments']} inserts · {summary['resumed_segments']} resumptions</div><label>Filter <select id="filter"><option value="">all</option><option>editorial</option><option>advertisement</option><option>front_matter</option><option>contents</option><option>cover</option><option>other</option></select></label></header><main>{''.join(cards)}</main><script>filter.onchange=()=>document.querySelectorAll('.item').forEach(x=>x.hidden=filter.value&&x.dataset.kind!==filter.value)</script></body></html>''',encoding="utf-8")
    print(json.dumps({"output":str(target),**summary},indent=2))


if __name__=="__main__": main()
