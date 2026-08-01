from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
from collections import Counter, defaultdict
from pathlib import Path

from .config import load_config
from .io_utils import read_json, read_jsonl


def data_uri(path: Path) -> str:
    mime=mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def page_image(config: dict, doc_id: str, page: str) -> Path | None:
    aligned=Path(config["input"]["aligned_root"]).resolve(); source=aligned/doc_id/f"{page}.json"
    if not source.exists(): return None
    raw=Path(str(read_json(source).get("page_image") or ""))
    for candidate in (raw,aligned.parents[2]/raw,source.parent/raw):
        if str(candidate) and candidate.exists(): return candidate.resolve()
    return None


def compact(node_id: str) -> str:
    suffix=node_id.rsplit("_EV_",1)[-1]
    return f"EV-{int(suffix)}" if suffix.isdigit() else node_id


def build(doc_id: str, config: dict, output: str | None=None) -> Path:
    root=Path(config["output"]["graph_root"])/doc_id; manifest=read_json(root/"pilot_manifest.json")
    selected=set(manifest["node_ids"]); nodes=[n for n in read_jsonl(root/"evidence_nodes.jsonl") if n["node_id"] in selected]
    edges=read_jsonl(root/"semantic_edges.jsonl"); rejected=read_jsonl(root/"rejected_semantic_candidates.jsonl")
    by_id={n["node_id"]:n for n in nodes}; by_page=defaultdict(list)
    for node in sorted(nodes,key=lambda n:n["document_order"]):
        for page in node.get("page_ids",[]) or ["unknown"]: by_page[page].append(node)
    pages=[]
    for page,members in sorted(by_page.items()):
        image=page_image(config,doc_id,page); pages.append({"id":page,"image":data_uri(image) if image else None,
            "nodes":[{"id":n["node_id"],"label":compact(n["node_id"]),"order":n["document_order"],
                      "summary":n.get("base_summary") or "","text":n.get("original_markdown","")} for n in members]})
    page_by_node={n["node_id"]:(n.get("page_ids") or ["unknown"])[0] for n in nodes}
    rows=[]
    for edge in edges:
        rows.append({**edge,"source_label":compact(edge["source"]),"target_label":compact(edge["target"]),
                     "source_page":page_by_node.get(edge["source"]),"target_page":page_by_node.get(edge["target"]),
                     "scope":"WITHIN_SLIDE" if page_by_node.get(edge["source"])==page_by_node.get(edge["target"]) else "CROSS_SLIDE"})
    relations=Counter(e["edge_type"] for e in rows); cross=sum(e["scope"]=="CROSS_SLIDE" for e in rows)
    data={"doc_id":doc_id,"pages":pages,"nodes":list(by_id),"edges":rows,"rejected":len(rejected),
          "summary":{"nodes":len(nodes),"accepted":len(rows),"rejected":len(rejected),"cross":cross,"relations":relations}}
    template=r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>EvidenceNet slide review</title><style>:root{--bg:#08101f;--panel:#111b2e;--line:#304261;--text:#edf3ff;--muted:#9eabc2;--accent:#58c8e5;--edge:#ffb454;--cross:#ff7185}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui}header{padding:18px 25px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;align-items:center}h1{font-size:21px;margin:0}.summary{color:var(--muted)}main{display:grid;grid-template-columns:minmax(600px,1fr) 430px;height:calc(100vh - 78px)}#slides{padding:22px;overflow:auto}.edge-map{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:24px;padding:12px}.edge-map h2{margin:0 0 8px}.graph{width:100%;min-width:850px}.lane{fill:#0c1628;stroke:#273a57}.g-edge{fill:none;stroke:var(--edge);stroke-width:2.2;opacity:.72;cursor:pointer}.g-edge.cross{stroke:var(--cross);stroke-width:3;stroke-dasharray:7 4}.g-node{fill:#243957;stroke:#8298ba;stroke-width:2;cursor:pointer}.g-node.involved{stroke:var(--edge);stroke-width:3}.g-label{fill:var(--text);font-size:10px}.g-slide{fill:var(--muted);font-size:12px;font-weight:700}.slide{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:24px;overflow:hidden}.slide h2{font-size:17px;margin:0;padding:12px 16px;background:#16243a}.slide-grid{display:grid;grid-template-columns:minmax(340px,55%) 1fr;gap:16px;padding:16px}.slide img{width:100%;border-radius:8px;border:1px solid var(--line)}.node{border:1px solid #2b3d5b;border-radius:8px;padding:9px;margin-bottom:7px;cursor:pointer}.node:hover,.node.active{border-color:var(--accent);background:#182942}.node b{color:var(--accent)}.node small{color:var(--muted);float:right}.node p{margin:5px 0;color:#cad5e7}aside{border-left:1px solid var(--line);padding:18px;overflow:auto;background:#0d1628}.filters button{border:1px solid var(--line);background:#17243a;color:var(--text);padding:6px 9px;border-radius:7px;margin:2px;cursor:pointer}.relation{border-left:3px solid var(--edge);background:var(--panel);padding:10px 12px;margin:9px 0;cursor:pointer}.relation.cross{border-color:var(--cross)}.relation .meta{color:var(--muted)}.badge{display:inline-block;background:#293a57;padding:3px 7px;border-radius:10px;margin:2px;font-size:12px}.spans{display:none;margin-top:8px;border-top:1px solid var(--line);padding-top:8px;color:#cdd7e8}.relation.open .spans{display:block}@media(max-width:1000px){main{display:block;height:auto}aside{border:0}.slide-grid{grid-template-columns:1fr}}</style></head><body><header><div><h1>EvidenceNet slide semantic review</h1><div class="summary" id="summary"></div></div><div>Slide → Evidence nodes → verified relations</div></header><main><section id="slides"><div class="edge-map"><h2>Semantic edge map</h2><div style="color:var(--muted)">Orange: within-slide · dashed red: cross-slide · click an edge for evidence</div><svg id="graph" class="graph"></svg></div><div id="slideCards"></div></section><aside><h2>Semantic relations</h2><div class="filters" id="filters"></div><div id="relations"></div></aside></main><script>const D=__DATA__;const esc=s=>{const x=document.createElement('div');x.textContent=s??'';return x.innerHTML};document.querySelector('#summary').textContent=`${D.pages.length} slides · ${D.summary.nodes} nodes · ${D.summary.accepted} accepted · ${D.summary.cross} cross-slide · ${D.summary.rejected} rejected`;document.querySelector('#slideCards').innerHTML=D.pages.map(p=>`<article class="slide"><h2>${esc(p.id)}</h2><div class="slide-grid"><div>${p.image?`<img src="${p.image}">`:'<p>Slide image unavailable</p>'}</div><div>${p.nodes.map(n=>`<div class="node" data-id="${n.id}"><b>${n.label}</b><small>order ${n.order}</small><p>${esc(n.summary)}</p><div>${esc(n.text)}</div></div>`).join('')}</div></div></article>`).join('');const types=['ALL',...Object.keys(D.summary.relations)];document.querySelector('#filters').innerHTML=types.map(t=>`<button onclick="render('${t}')">${t}${t==='ALL'?'':` (${D.summary.relations[t]})`}</button>`).join('');function render(type='ALL'){const es=type==='ALL'?D.edges:D.edges.filter(e=>e.edge_type===type);document.querySelector('#relations').innerHTML=es.map(e=>{const i=D.edges.indexOf(e);return `<div id="rel-${i}" class="relation ${e.scope==='CROSS_SLIDE'?'cross':''}" onclick="this.classList.toggle('open');focusNodes('${e.source}','${e.target}')"><b>${e.source_label} → ${e.target_label}</b><br><span class="badge">${e.edge_type}</span><span class="badge">${e.scope}</span><span class="badge">${e.confidence.toFixed(2)}</span><div class="meta">${esc(e.source_page)} → ${esc(e.target_page)}</div><div class="spans"><b>Rationale</b><p>${esc(e.rationale)}</p><b>${e.source_label}</b><p>${esc(e.source_supporting_span)}</p><b>${e.target_label}</b><p>${esc(e.target_supporting_span)}</p></div></div>`}).join('');drawGraph(es)}function drawGraph(edges){const svg=document.querySelector('#graph'),NS='http://www.w3.org/2000/svg',W=1100,laneH=180,H=D.pages.length*laneH,pos={};svg.innerHTML='';svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('height',H);const mk=(n,a={})=>{const x=document.createElementNS(NS,n);Object.entries(a).forEach(([k,v])=>x.setAttribute(k,v));return x};const defs=mk('defs');defs.innerHTML='<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ffb454"/></marker><marker id="crossarr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ff7185"/></marker>';svg.append(defs);D.pages.forEach((p,pi)=>{const y=pi*laneH+90;svg.append(mk('rect',{x:8,y:y-72,width:W-16,height:144,rx:12,class:'lane'}));const st=mk('text',{x:22,y:y-48,class:'g-slide'});st.textContent=p.id;svg.append(st);p.nodes.forEach((n,i)=>{const x=70+i*(W-140)/Math.max(1,p.nodes.length-1);pos[n.id]={x,y};})});edges.forEach((e,i)=>{const a=pos[e.source],b=pos[e.target];if(!a||!b)return;const bend=e.scope==='CROSS_SLIDE'?0:-35-(i%4)*12,d=`M${a.x},${a.y} Q${(a.x+b.x)/2},${(a.y+b.y)/2+bend} ${b.x},${b.y}`,p=mk('path',{d,class:'g-edge '+(e.scope==='CROSS_SLIDE'?'cross':''),'marker-end':e.scope==='CROSS_SLIDE'?'url(#crossarr)':'url(#arr)'});p.onclick=()=>{const idx=D.edges.indexOf(e),card=document.querySelector('#rel-'+idx);card?.classList.add('open');card?.scrollIntoView({behavior:'smooth',block:'center'});focusNodes(e.source,e.target)};const title=mk('title');title.textContent=`${e.source_label} → ${e.target_label}: ${e.edge_type}`;p.append(title);svg.append(p)});const involved=new Set(edges.flatMap(e=>[e.source,e.target]));D.pages.flatMap(p=>p.nodes).forEach(n=>{const p=pos[n.id],c=mk('circle',{cx:p.x,cy:p.y,r:10,class:'g-node '+(involved.has(n.id)?'involved':'')});c.onclick=()=>focusNodes(n.id,n.id);svg.append(c);const t=mk('text',{x:p.x,y:p.y+26,'text-anchor':'middle',class:'g-label'});t.textContent=n.label;svg.append(t)})}function focusNodes(a,b){document.querySelectorAll('.node').forEach(n=>n.classList.toggle('active',n.dataset.id===a||n.dataset.id===b));document.querySelector(`.node[data-id="${a}"]`)?.scrollIntoView({behavior:'smooth',block:'center'})}render();</script></body></html>'''
    target=Path(output) if output else root/"semantic_slide_review.html"
    target.write_text(template.replace("__DATA__",json.dumps(data,ensure_ascii=False).replace("</","<\/")),encoding="utf-8")
    return target


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--doc-id",required=True);p.add_argument("--config",required=True);p.add_argument("--output")
    a=p.parse_args(argv);print(build(a.doc_id,load_config(a.config),a.output))


if __name__=="__main__":main()
