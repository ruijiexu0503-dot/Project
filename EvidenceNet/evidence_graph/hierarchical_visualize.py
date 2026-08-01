from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl

TEMPLATE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>EvidenceNet hierarchical magazine graph</title><style>
:root{--bg:#09101f;--panel:#111b2e;--line:#304361;--text:#edf3ff;--muted:#9cabc4;--accent:#59c8e5;--edge:#ffb454;--bridge:#ff7185}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 system-ui}header{height:70px;padding:14px 22px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}h1{font-size:19px;margin:0}header span{color:var(--muted)}
main{display:grid;grid-template-columns:300px 1fr;height:calc(100vh - 70px)}aside{border-right:1px solid var(--line);overflow:auto;padding:16px;background:#0d1628}.document{color:var(--accent);font-weight:700;margin-bottom:12px}.unit-button{width:100%;border:0;border-left:2px solid var(--line);background:transparent;color:var(--text);padding:8px 10px;text-align:left;cursor:pointer}.unit-button:hover,.unit-button.active{background:#19263d;border-color:var(--accent)}.unit-button small{display:block;color:var(--muted)}
#content{overflow:auto;padding:24px}.overview{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}.unit-card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:13px;cursor:pointer}.unit-card:hover{border-color:var(--accent)}.unit-card b{color:var(--accent)}.unit-card p{color:var(--muted);margin:6px 0}.bridge-list{margin-top:25px}.bridge{border-left:3px solid var(--bridge);background:var(--panel);padding:9px 12px;margin:7px 0}
.toolbar{position:sticky;top:-24px;background:#09101fee;padding:12px 0;z-index:2}.back{border:1px solid var(--line);background:#18253c;color:var(--text);padding:7px 10px;border-radius:7px;cursor:pointer}svg{background:#0c1425;border:1px solid var(--line);border-radius:12px}.node{fill:#203252;stroke:#7890b5;stroke-width:2;cursor:pointer}.node.involved{stroke:var(--edge);stroke-width:3}.label{fill:var(--text);font-size:10px;pointer-events:none}.semantic{stroke:var(--edge);stroke-width:2.4;fill:none;opacity:.8}.details{position:fixed;right:18px;bottom:18px;width:min(430px,45vw);max-height:45vh;overflow:auto;background:#111b2ef2;border:1px solid var(--line);border-radius:10px;padding:13px;display:none}.source{white-space:pre-wrap;color:#ced8ea}.badge{display:inline-block;background:#2a3a57;padding:3px 7px;border-radius:10px;margin:2px;color:#dce7f7}
</style></head><body><header><div><h1>EvidenceNet hierarchical semantic graph</h1><span id="summary"></span></div><span>Document → soft content units → Evidence nodes</span></header><main><aside><div class="document" id="doc"></div><button class="unit-button" onclick="overview()">▾ Whole document overview</button><div id="tree"></div></aside><section id="content"></section></main><div class="details" id="details"></div>
<script>const D=__DATA__,content=document.querySelector('#content'),details=document.querySelector('#details');
document.querySelector('#doc').textContent=D.doc_id;document.querySelector('#summary').textContent=`${D.nodes.length} Evidence nodes · ${D.units.length} content units · ${D.edges.length} semantic edges · ${D.bridges.length} bridges`;
const byId=Object.fromEntries(D.nodes.map(n=>[n.node_id,n]));const tree=document.querySelector('#tree');
function esc(s){const x=document.createElement('div');x.textContent=s??'';return x.innerHTML}function compact(id){const m=id.match(/EV_0*(\d+)$/);return m?'EV-'+m[1]:id}
D.units.forEach(u=>{const b=document.createElement('button');b.className='unit-button';b.innerHTML=`${u.id}<small>${u.node_ids.length} nodes · ${u.edge_count} edges</small>`;b.onclick=()=>showUnit(u.id);tree.appendChild(b)});
function overview(){details.style.display='none';document.querySelectorAll('.unit-button').forEach(x=>x.classList.remove('active'));content.innerHTML=`<h2>Whole document</h2><p>Content units are soft hierarchy groups. Semantic bridges may connect Evidence across groups.</p><div class="overview">${D.units.map(u=>`<div class="unit-card" onclick="showUnit('${u.id}')"><b>${u.id}</b><p>${u.node_ids.length} Evidence nodes</p><p>${u.edge_count} internal semantic edges</p></div>`).join('')}</div><div class="bridge-list"><h2>Cross-unit semantic bridges (${D.bridges.length})</h2>${D.bridges.length?D.bridges.map(e=>`<div class="bridge"><b>${esc(e.source_content_unit_id)} → ${esc(e.target_content_unit_id)}</b> · ${esc(e.edge_type)} (${e.confidence.toFixed(2)})<br>${esc(compact(e.source))} → ${esc(compact(e.target))}</div>`).join(''):'<p>No verified cross-unit bridges.</p>'}</div>`}
function showUnit(id){details.style.display='none';document.querySelectorAll('.unit-button').forEach((x,i)=>x.classList.toggle('active',D.units[i]?.id===id));const u=D.units.find(x=>x.id===id),nodes=u.node_ids.map(x=>byId[x]),edges=D.edges.filter(e=>e.source_content_unit_id===id&&e.target_content_unit_id===id);const cols=5,dx=190,dy=115,w=cols*dx+70,h=Math.ceil(nodes.length/cols)*dy+80,pos={};nodes.forEach((n,i)=>pos[n.node_id]={x:70+(i%cols)*dx,y:60+Math.floor(i/cols)*dy});content.innerHTML=`<div class="toolbar"><button class="back" onclick="overview()">← Document overview</button> <b>${id}</b> · ${nodes.length} nodes · ${edges.length} semantic edges</div><svg id="svg" width="${w}" height="${h}"></svg>`;const svg=document.querySelector('#svg'),NS='http://www.w3.org/2000/svg';function el(n,a){const x=document.createElementNS(NS,n);Object.entries(a||{}).forEach(([k,v])=>x.setAttribute(k,v));return x}edges.forEach(e=>{const a=pos[e.source],b=pos[e.target];if(!a||!b)return;const line=el('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'semantic'});line.onclick=()=>edgeDetails(e);svg.appendChild(line)});const involved=new Set(edges.flatMap(e=>[e.source,e.target]));nodes.forEach(n=>{const p=pos[n.node_id],c=el('circle',{cx:p.x,cy:p.y,r:11,class:'node '+(involved.has(n.node_id)?'involved':'')});c.onclick=()=>nodeDetails(n);svg.appendChild(c);const t=el('text',{x:p.x,y:p.y+27,'text-anchor':'middle',class:'label'});t.textContent=compact(n.node_id);svg.appendChild(t)})}
function nodeDetails(n){details.style.display='block';details.innerHTML=`<b>${esc(compact(n.node_id))}</b><p>${esc(n.base_summary||'')}</p><div class="source">${esc(n.original_markdown)}</div>`}function edgeDetails(e){details.style.display='block';details.innerHTML=`<b>${esc(e.edge_type)} · ${e.confidence.toFixed(2)}</b><div>${e.candidate_reasons.map(x=>`<span class="badge">${esc(x)}</span>`).join('')}</div><p>${esc(e.rationale)}</p><hr><b>${esc(compact(e.source))}</b><div class="source">${esc(e.source_supporting_span)}</div><hr><b>${esc(compact(e.target))}</b><div class="source">${esc(e.target_supporting_span)}</div>`}overview();</script></body></html>'''


def build(doc_id: str, config: dict, output: str | None = None) -> Path:
    root=Path(config["output"]["graph_root"])/doc_id
    nodes=read_jsonl(root/"evidence_nodes.jsonl"); assignments=read_jsonl(root/"hybrid_content_unit_assignments.jsonl")
    edges=read_jsonl(root/"semantic_full_edges.jsonl") if (root/"semantic_full_edges.jsonl").exists() else []
    unit_by_node={r["node_id"]:r["content_unit_id"] for r in assignments}; by_unit=defaultdict(list)
    for n in sorted(nodes,key=lambda x:x["document_order"]): by_unit[unit_by_node[n["node_id"]]].append(n["node_id"])
    units=[]
    for unit,ids in by_unit.items():
        count=sum(e.get("source_content_unit_id")==unit and e.get("target_content_unit_id")==unit for e in edges)
        units.append({"id":unit,"node_ids":ids,"edge_count":count})
    bridges=[e for e in edges if e.get("content_unit_scope")=="CROSS_CONTENT_UNIT"]
    data={"doc_id":doc_id,"nodes":nodes,"units":units,"edges":edges,"bridges":bridges}
    target=Path(output) if output else root/"semantic_full_hierarchical_review.html"
    target.write_text(TEMPLATE.replace("__DATA__",json.dumps(data,ensure_ascii=False).replace("</","<\/")),encoding="utf-8")
    return target


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--doc-id",required=True);p.add_argument("--config",required=True);p.add_argument("--output")
    a=p.parse_args(argv);print(build(a.doc_id,load_config(a.config),a.output))


if __name__=="__main__":main()
