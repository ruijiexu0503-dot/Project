from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#08111f;--panel:#101c2e;--line:#2a3d59;--text:#edf4ff;--muted:#91a5c1;--ref:#ffb454;--related:#45d6c3;--support:#55b7ff;--explain:#c58cff;--modify:#ff7da8;--contrast:#ff6b6b;--order:#58708e;--continue:#66d6b1;--figure:#2c6e62;--table:#795b2e;--formula:#614f89;--plain:#243752}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif;overflow:hidden}
header{height:70px;padding:11px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:24px;background:#0c1727}h1{font-size:18px;margin:0}.stats{color:var(--muted);flex:1}.controls{display:flex;gap:15px;align-items:center}.controls label{color:var(--muted)}select{background:#14243a;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px}
main{display:grid;grid-template-columns:minmax(0,1fr) 390px;height:calc(100vh - 70px)}#wrap{overflow:auto;position:relative}svg{display:block}.lane{fill:#0d192a;stroke:#1d3049}.lane-title{fill:#9eb2cc;font-size:12px;font-weight:700}.ref,.sem{fill:none;stroke-width:2.5;opacity:.88;cursor:pointer}.ref{stroke:var(--ref)}.sem.RELATED,.sem.CONTRIBUTES_TO{stroke:var(--related)}.sem.PROFILED_RELATED{stroke:var(--related);stroke-dasharray:4 3}.sem.CONTRIBUTES_TO.EVIDENTIAL:not(.EXPLANATORY){stroke:var(--support)}.sem.CONTRIBUTES_TO.EXPLANATORY:not(.EVIDENTIAL){stroke:var(--explain)}.sem.CONTRIBUTES_TO.EVIDENTIAL.EXPLANATORY{stroke:var(--related);stroke-width:3.5}.sem.SUPPORTS{stroke:var(--support)}.sem.EXPLAINS_OR_ELABORATES{stroke:var(--explain)}.sem.MODIFIES{stroke:var(--modify)}.sem.CONTRASTS_WITH{stroke:var(--contrast);stroke-dasharray:7 4}.continue{stroke:var(--continue);stroke-width:1.7;opacity:.65;fill:none}.order{stroke:var(--order);stroke-width:1;opacity:.45}.node{stroke:#8fa7c5;stroke-width:1.5;cursor:pointer}.node.text{fill:var(--plain)}.node.figure{fill:var(--figure)}.node.table{fill:var(--table)}.node.formula{fill:var(--formula)}.node.missing{stroke:#ff7785;stroke-dasharray:5 3}.node.selected,.ref.selected,.sem.selected{stroke:#fff;stroke-width:4}.node-label{fill:var(--text);font-size:10px;pointer-events:none}.node-meta{fill:#c2cee0;font-size:9px;pointer-events:none}
aside{border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:18px}aside h2{font-size:17px;margin:0 0 10px}.empty{color:var(--muted);padding:35px 4px}.badge{display:inline-block;background:#223653;border-radius:14px;padding:3px 8px;margin:0 5px 6px 0;font-size:12px}.badge.warn{background:#5a2933;color:#ffc4cb}.badge.ref{background:#58401f;color:#ffd7a6;stroke:none}.card{border:1px solid var(--line);border-radius:9px;background:#0b1626;padding:12px;margin:12px 0}.card h3{font-size:12px;color:#79d6e9;margin:0 0 8px}.source{white-space:pre-wrap;max-height:310px;overflow:auto;color:#cfdaeb}.asset{width:100%;max-height:310px;object-fit:contain;background:#fff;border-radius:6px}.legend{position:sticky;left:14px;top:12px;z-index:3;width:max-content;padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:#101c2eee;color:var(--muted)}.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin:0 4px 0 10px}.dot:first-child{margin-left:0}
</style></head><body>
<header><div><h1>__TITLE__</h1><div class="stats" id="stats"></div></div><div class="stats" id="family-note">Discourse and semantic edge families are independent</div><div class="controls"><label>Section <select id="section"></select></label><label><input id="references" type="checkbox" checked> references</label><label id="semantic-control"><input id="semantic" type="checkbox" checked> semantic</label><label><input id="connected" type="checkbox" checked> connected only</label><label><input id="order" type="checkbox"> reading order</label><label><input id="continues" type="checkbox"> continues</label></div></header>
<main><div id="wrap"><div class="legend"><span class="dot" style="background:var(--figure)"></span>Figure <span class="dot" style="background:var(--table)"></span>Table <span class="dot" style="background:var(--ref)"></span>REFERENCES <span class="semantic-key"><span class="dot" style="background:var(--support)"></span>EVIDENTIAL <span class="dot" style="background:var(--explain)"></span>EXPLANATORY <span class="dot" style="background:var(--related)"></span>BOTH / RELATED <span class="dot" style="background:var(--modify)"></span>MODIFIES <span class="dot" style="background:var(--contrast)"></span>CONTRASTS</span></div><svg id="graph"></svg></div><aside id="details"><div class="empty">Select a node, discourse edge, or semantic edge.</div></aside></main>
<script>const DATA=__DATA__;const svg=document.querySelector('#graph'),details=document.querySelector('#details'),section=document.querySelector('#section');
if(!DATA.counts.semantic){document.querySelector('#semantic-control').hidden=true;document.querySelector('.semantic-key').hidden=true;document.querySelector('#family-note').textContent='Canonical Evidence and deterministic discourse grounding';details.innerHTML='<div class="empty">Select a node or REFERENCES edge.</div>'}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const short=s=>s.length>150?s.slice(0,147)+'…':s;const compact=id=>id.includes('_EV_')?'EV'+id.split('_EV_')[1].replace(/^0+/,''):id;
const refs=DATA.references,semantic=DATA.semantic;section.innerHTML='<option value="">All sections</option>'+DATA.sections.map(s=>`<option>${esc(s)}</option>`).join('');document.querySelector('#stats').textContent=`${DATA.counts.evidence} Evidence · ${DATA.counts.references} REFERENCES · ${DATA.counts.semantic} semantic · ${DATA.counts.multimodal} multimodal`;
function E(name,attrs={}){const x=document.createElementNS('http://www.w3.org/2000/svg',name);Object.entries(attrs).forEach(([k,v])=>x.setAttribute(k,v));return x}function defs(){const d=E('defs');d.innerHTML='<marker id="refArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ffb454"/></marker><marker id="contributeArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#45d6c3"/></marker><marker id="supportArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#55b7ff"/></marker><marker id="explainArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#c58cff"/></marker><marker id="modifyArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ff7da8"/></marker><marker id="thinArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#58708e"/></marker>';svg.append(d)}
function activeEdges(){return[...(document.querySelector('#references').checked?refs:[]),...(document.querySelector('#semantic').checked?semantic:[])]}function visible(){let n=DATA.nodes;if(section.value)n=n.filter(x=>x.section===section.value);if(document.querySelector('#connected').checked){const involved=new Set(activeEdges().flatMap(e=>[e.source,e.target]));n=n.filter(x=>involved.has(x.id))}return n}
function render(){svg.innerHTML='';defs();const nodes=visible(),active=new Set(nodes.map(n=>n.id)),groups={};nodes.forEach(n=>(groups[n.section||'Unsectioned']??=[]).push(n));const cols=8,dx=145,dy=88,left=85,top=55,width=1280,pos={};let y=top;Object.entries(groups).forEach(([name,rows])=>{const height=Math.ceil(rows.length/cols)*dy+55;svg.append(E('rect',{x:15,y:y-32,width:width-30,height,rx:10,class:'lane'}));const label=E('text',{x:30,y:y-10,class:'lane-title'});label.textContent=name;svg.append(label);rows.forEach((n,i)=>{pos[n.id]={x:left+(i%cols)*dx,y:y+Math.floor(i/cols)*dy};});y+=height+18});svg.setAttribute('width',width);svg.setAttribute('height',Math.max(650,y));svg.style.width=width+'px';svg.style.height=Math.max(650,y)+'px';
if(document.querySelector('#order').checked){const ordered=[...nodes].sort((a,b)=>a.order-b.order);for(let i=1;i<ordered.length;i++){const a=pos[ordered[i-1].id],b=pos[ordered[i].id];if(a&&b)svg.append(E('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'order','marker-end':'url(#thinArrow)'}))}}
if(document.querySelector('#continues').checked)DATA.continues.forEach(e=>{const a=pos[e.source],b=pos[e.target];if(a&&b)svg.append(E('path',{d:`M${a.x},${a.y} Q${(a.x+b.x)/2},${Math.min(a.y,b.y)-25} ${b.x},${b.y}`,class:'continue'}))});
if(document.querySelector('#references').checked)refs.forEach((e,i)=>{if(!active.has(e.source)||!active.has(e.target))return;const a=pos[e.source],b=pos[e.target],p=E('path',{d:`M${a.x},${a.y} Q${(a.x+b.x)/2},${Math.min(a.y,b.y)-35-(i%4)*9} ${b.x},${b.y}`,class:'ref','marker-end':'url(#refArrow)'});p.onclick=()=>showEdge(e,p);const t=E('title');t.textContent=`${compact(e.source)} → ${compact(e.target)} · ${e.cue}`;p.append(t);svg.append(p)});
if(document.querySelector('#semantic').checked)semantic.forEach((e,i)=>{if(!active.has(e.source)||!active.has(e.target))return;const a=pos[e.source],b=pos[e.target],modes=e.contribution_modes||[],modeClasses=modes.join(' '),markers={SUPPORTS:'supportArrow',EXPLAINS_OR_ELABORATES:'explainArrow',MODIFIES:'modifyArrow'},attrs={d:`M${a.x},${a.y} Q${(a.x+b.x)/2},${Math.max(a.y,b.y)+32+(i%4)*8} ${b.x},${b.y}`,class:`sem ${e.relation} ${modeClasses}`};if(e.relation==='CONTRIBUTES_TO'){markers.CONTRIBUTES_TO=modes.length===1?(modes[0]==='EVIDENTIAL'?'supportArrow':'explainArrow'):'contributeArrow'}if(e.directed!==false&&markers[e.relation])attrs['marker-end']=`url(#${markers[e.relation]})`;const p=E('path',attrs);p.onclick=()=>showSemantic(e,p);const t=E('title');t.textContent=`${e.relation}${modes.length?' ['+modes.join(' + ')+']':''}: ${compact(e.source)} → ${compact(e.target)}`;p.append(t);svg.append(p)});
nodes.forEach(n=>{const p=pos[n.id],kind=['figure','table','formula'].includes(n.type)?n.type:'text',r=E('rect',{x:p.x-55,y:p.y-25,width:110,height:50,rx:8,class:`node ${kind} ${n.missing_asset?'missing':''}`});r.onclick=()=>showNode(n,r);svg.append(r);const a=E('text',{x:p.x,y:p.y-4,'text-anchor':'middle',class:'node-label'});a.textContent=compact(n.id);svg.append(a);const b=E('text',{x:p.x,y:p.y+11,'text-anchor':'middle',class:'node-meta'});b.textContent=`#${n.order} · ${n.type}`;svg.append(b)})}
function clear(){document.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'))}function showNode(n,shape){clear();shape.classList.add('selected');details.innerHTML=`<h2>${esc(compact(n.id))}</h2><span class="badge">${esc(n.type)}</span><span class="badge">order ${n.order}</span>${n.missing_asset?'<span class="badge warn">missing visual asset</span>':''}<div class="card"><h3>${esc(n.section||'Unsectioned')}</h3><div>${esc(n.modalities.join(' · '))}</div></div>${n.asset?`<div class="card"><h3>Visual asset</h3><img class="asset" src="${n.asset}"></div>`:''}<div class="card"><h3>Canonical Evidence</h3><div class="source">${esc(n.text)}</div></div>${n.source_ids.length>1?`<div class="card"><h3>Materialized from</h3>${n.source_ids.map(x=>`<div>${esc(x)}</div>`).join('')}</div>`:''}`}
function showEdge(e,path){clear();path.classList.add('selected');const s=DATA.by_id[e.source],t=DATA.by_id[e.target];details.innerHTML=`<h2>REFERENCES</h2><span class="badge ref">explicit label</span><span class="badge">confidence ${e.confidence.toFixed(2)}</span><div class="card"><h3>Referential cue</h3>${esc(e.cue)}</div><div class="card"><h3>${esc(compact(e.source))} → ${esc(compact(e.target))}</h3><div class="source"><b>Source</b>\n${esc(short(s.text))}\n\n<b>Target</b>\n${esc(short(t.text))}</div></div>`}
function showSemantic(e,path){clear();path.classList.add('selected');const s=DATA.by_id[e.source],t=DATA.by_id[e.target],status=e.metadata?.semantic_status||'',model=(e.model||'').split('/').pop(),provenance=status.startsWith('legacy')?'legacy prediction · archived source':`${model||'configured model'} · not manually revalidated`,modes=e.contribution_modes||[],signals=e.semantic_signals||[],secondary=e.secondary_relation?[e.secondary_relation]:[],profileBadges=[...modes,...signals,...secondary.map(x=>'secondary: '+x)].map(x=>`<span class="badge">${esc(x)}</span>`).join(''),direction=e.direction_status||((e.directed===false)?'UNRESOLVED':'DIRECTED');details.innerHTML=`<h2>${esc(e.relation)}</h2><span class="badge">semantic</span>${profileBadges}<span class="badge">${esc(direction)}</span><span class="badge">confidence ${Number(e.confidence||0).toFixed(2)}</span><span class="badge warn">${esc(provenance)}</span><div class="card"><h3>Connection</h3>${esc(e.rationale||e.relation_description||'No rationale stored.')}</div><div class="card"><h3>${esc(compact(e.source))} → ${esc(compact(e.target))}</h3><div class="source"><b>Source</b>\n${esc(short(s.text))}\n\n<b>Target</b>\n${esc(short(t.text))}</div></div>`}
section.onchange=render;['references','semantic','connected','order','continues'].forEach(id=>document.querySelector('#'+id).onchange=render);render();</script></body></html>'''


def _asset_data(path: str | None) -> str | None:
    if not path:
        return None
    target = Path(path)
    if not target.exists():
        return None
    mime = mimetypes.guess_type(target.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(target.read_bytes()).decode('ascii')}"


def build_visualization(doc_id: str, config: dict, output_path: str | Path | None = None,
                        graph_root: str | Path | None = None, title: str | None = None) -> dict:
    if graph_root:
        root = Path(graph_root)
    else:
        canonical_root = Path((config.get("canonicalization") or {}).get("output_root")
                              or Path(config["output"]["graph_root"]).parent / "canonical_graph")
        root = canonical_root / doc_id
    nodes = sorted(read_jsonl(root / "evidence_nodes.jsonl"), key=lambda row: row["document_order"])
    references = read_jsonl(root / "discourse_edges.jsonl")
    semantic = read_jsonl(root / "semantic_edges.jsonl")
    structural = read_jsonl(root / "structural_edges.jsonl")
    rendered = []
    for node in nodes:
        canonical = (node.get("metadata") or {}).get("canonical_multimodal") or {}
        rendered.append({
            "id": node["node_id"],
            "order": node["document_order"],
            "type": node.get("evidence_type", "text"),
            "modalities": node.get("modalities") or ["text"],
            "section": (node.get("section_path") or ["Unsectioned"])[-1],
            "text": node.get("plain_text") or node.get("original_markdown") or "",
            "asset": _asset_data(node.get("asset_path")),
            "missing_asset": bool(canonical.get("missing_visual_asset")),
            "source_ids": canonical.get("source_node_ids") or [node["node_id"]],
        })
    data = {
        "doc_id": doc_id,
        "nodes": rendered,
        "by_id": {row["id"]: row for row in rendered},
        "references": references,
        "semantic": semantic,
        "continues": [row for row in structural if row.get("edge_type") == "CONTINUES_TO"],
        "sections": list(dict.fromkeys(row["section"] for row in rendered)),
        "counts": {
            "evidence": len(rendered),
            "references": len(references),
            "semantic": len(semantic),
            "multimodal": sum("image" in row["modalities"] for row in rendered),
        },
    }
    target = Path(output_path) if output_path else root / "canonical_graph.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    title = title or f"{doc_id} · canonical Evidence graph"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    target.write_text(
        TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload),
        encoding="utf-8",
    )
    return {"output": str(target), **data["counts"], "sections": len(data["sections"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize a canonical Evidence graph")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output")
    parser.add_argument("--graph-root", help="Read graph files directly from this isolated directory")
    parser.add_argument("--title")
    args = parser.parse_args()
    print(json.dumps(build_visualization(
        args.doc_id, load_config(args.config), args.output, args.graph_root, args.title,
    ), indent=2))


if __name__ == "__main__":
    main()
