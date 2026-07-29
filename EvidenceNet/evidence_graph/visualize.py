from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

from .config import load_config
from .io_utils import read_json, read_jsonl


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EvidenceNet semantic pilot review</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#31405f;--text:#e9eef9;--muted:#95a4bf;--accent:#58c4dc;--semantic:#ffb454;--proposal:#c78cff;--struct:#7184a5;--visual-edge:#55d6a5;--good:#57d38c;--bad:#ff6b7a}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}
header{min-height:64px;padding:12px 20px;border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(220px,1fr) auto auto;align-items:center;gap:24px} h1{font-size:18px;margin:0}.summary{color:var(--muted)}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,420px);height:calc(100vh - 64px)} #canvasWrap{position:relative;overflow:auto}.toolbar{position:sticky;z-index:2;left:16px;top:14px;width:max-content;background:#121a2ddd;border:1px solid var(--line);border-radius:8px;padding:9px 12px;display:flex;gap:14px}
label{color:var(--muted)} input{vertical-align:middle} svg{width:100%;height:100%}.edge{stroke:var(--struct);stroke-width:1.4;opacity:.52}.edge.visual-structural{stroke:var(--visual-edge);stroke-width:2.6;opacity:.95;cursor:pointer}.edge.semantic{stroke:var(--semantic);stroke-width:3;opacity:.9;cursor:pointer}.edge.proposal{stroke:var(--proposal);stroke-width:2;stroke-dasharray:7 5;opacity:.72;cursor:pointer}.edge.selected{stroke:#fff;stroke-width:5}.node{fill:#1c2944;stroke:#7589ae;stroke-width:1.5;cursor:pointer}.node.visual-node{fill:#254a3b;stroke:#66d3a0;stroke-width:3}.node.formula-node{fill:#3b315d;stroke:#b596ff;stroke-width:3}.node.semantic{stroke:var(--semantic);stroke-width:3}.node.selected{fill:#29476c;stroke:#fff}.label{fill:var(--text);font-size:11px;pointer-events:none}.section-label{fill:var(--muted);font-size:12px;font-weight:700}
aside{border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:18px} aside h2{font-size:16px;margin:0 0 12px}.empty{color:var(--muted);padding:30px 5px}.badge{display:inline-block;padding:3px 7px;border-radius:12px;background:#24334f;color:#c9d6ec;margin:0 5px 5px 0;font-size:12px}.badge.semantic{background:#573d22;color:#ffd39a}.confidence{color:var(--semantic);font-weight:700}.card{border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0;background:#0e1628}.card h3{font-size:13px;margin:0 0 8px;color:var(--accent)}.source{white-space:pre-wrap;max-height:230px;overflow:auto;color:#cbd6e8}.span{background:#563f21;color:#ffe0ad;padding:2px 4px}.meta{color:var(--muted);font-size:12px}.actions{display:flex;gap:8px;margin:14px 0}.actions button,.export{border:1px solid var(--line);background:#1b2943;color:var(--text);padding:7px 10px;border-radius:6px;cursor:pointer}.actions .accept{border-color:var(--good)}.actions .reject{border-color:var(--bad)}textarea{width:100%;min-height:65px;background:#0a1120;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:8px}.review-status{font-weight:700}.review-status.accept{color:var(--good)}.review-status.reject{color:var(--bad)}.lane{fill:#0e1628;stroke:#202e49;stroke-width:1}.hint{fill:var(--muted);font-size:11px}
@media(max-width:900px){header{grid-template-columns:1fr}.summary{display:none}main{grid-template-columns:1fr}aside{position:fixed;right:0;top:64px;bottom:0;width:min(420px,90vw);z-index:5;box-shadow:-8px 0 24px #0008}}
</style></head><body>
<header><h1>EvidenceNet semantic pilot review</h1><div class="summary" id="summary"></div><button class="export" onclick="exportReviews()">Export reviews</button></header>
<main><div id="canvasWrap"><div class="toolbar"><label><input id="showVisualLinks" type="checkbox" checked> figure/formula links</label><label><input id="showReadingOrder" type="checkbox"> reading order</label><label><input id="showProposed" type="checkbox"> first-pass proposals</label><label><input id="showRejected" type="checkbox"> rejected candidates</label></div><svg id="graph"></svg></div><aside id="details"><div class="empty">Select an orange accepted edge, purple proposal, or green figure link.</div></aside></main>
<script>const DATA=__DATA__; const reviews={};
const nodes=Object.fromEntries(DATA.nodes.map(n=>[n.node_id,n])); const acceptedKeys=new Set(DATA.semantic.map(e=>[e.source,e.target].sort().join('|')));
document.querySelector('#summary').textContent=`${DATA.nodes.length} nodes · ${DATA.semantic.length} final accepted · ${DATA.proposed.length} first-pass proposals · ${DATA.rejected.length} rejected`;
const svg=document.querySelector('#graph'), NS='http://www.w3.org/2000/svg'; let selected=null;
function el(name,attrs={}){const x=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs))x.setAttribute(k,v);return x}
function esc(s){const d=document.createElement('div');d.textContent=s??'';return d.innerHTML}
function short(s,n=80){s=(s||'').replace(/\s+/g,' ');return s.length>n?s.slice(0,n-1)+'…':s}
function compactId(id){let m=id.match(/EV_(\d+)$/);if(m)return'EV-'+Number(m[1]);m=id.match(/_(FIG|TABLE)_0*(\d+)$/);return m?m[1]+'-'+Number(m[2]):id}
function layout(){const bySec={};DATA.nodes.forEach(n=>(bySec[n.section_path?.join(' / ')||'Unsectioned']??=[]).push(n));Object.values(bySec).forEach(a=>a.sort((x,y)=>(x.document_order??1e9)-(y.document_order??1e9)||(x.node_type==='visual'?1:-1)));const sections=Object.entries(bySec),spacing=128,left=95,laneHeight=190;const maxCount=Math.max(...sections.map(x=>x[1].length));const W=Math.max(900,left+maxCount*spacing+100),H=sections.length*laneHeight+90,pos={};sections.forEach(([name,arr],si)=>{const y=100+si*laneHeight;arr.forEach((n,i)=>{pos[n.node_id]={x:left+i*spacing,y}})});svg.setAttribute('width',W);svg.setAttribute('height',H);svg.style.width=W+'px';svg.style.height=H+'px';return{pos,sections,W,H,laneHeight}}
function render(){svg.innerHTML='';const{pos,sections,W,laneHeight}=layout(),showV=document.querySelector('#showVisualLinks').checked,showO=document.querySelector('#showReadingOrder').checked,showP=document.querySelector('#showProposed').checked,showR=document.querySelector('#showRejected').checked;
const defs=el('defs');defs.innerHTML='<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#ffb454"/></marker><marker id="structArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#55d6a5"/></marker><marker id="proposalArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#c78cff"/></marker>';svg.append(defs);
sections.forEach(([name,arr],i)=>{const y=pos[arr[0].node_id].y;svg.append(el('rect',{x:12,y:y-68,width:W-24,height:136,rx:12,class:'lane'}));const t=el('text',{x:28,y:y-40,class:'section-label'});t.textContent=name;svg.append(t)});
const visualTypes=['REFERENCES_FIGURE','REFERENCES_TABLE','REFERENCES_FORMULA','CAPTION_OF','HAS_CAPTION','TABLE_CONTENT_OF','HAS_TABLE_CONTENT','COLOCATED_WITH_VISUAL'];
if(showO) DATA.structural.filter(e=>['NEXT','CONTINUES_TO'].includes(e.edge_type)&&pos[e.source]&&pos[e.target]).forEach(e=>drawEdge(e,false,pos));
if(showV) DATA.structural.filter(e=>visualTypes.includes(e.edge_type)&&pos[e.source]&&pos[e.target]).forEach(e=>drawEdge(e,false,pos));
if(showR) DATA.rejected.forEach(r=>{const c=r.candidate;if(c&&pos[c.node_a]&&pos[c.node_b])drawEdge({source:c.node_a,target:c.node_b,edge_type:'REJECTED'},false,pos,.08)});
if(showP) DATA.proposed.filter(e=>!DATA.semantic.some(a=>a.source===e.source&&a.target===e.target&&a.edge_type===e.edge_type)).forEach(e=>{if(pos[e.source]&&pos[e.target])drawEdge(e,'proposal',pos)});
DATA.semantic.forEach(e=>drawEdge(e,true,pos));DATA.nodes.forEach(n=>drawNode(n,pos[n.node_id]));}
function drawEdge(e,kind,pos,opacity){const a=pos[e.source],b=pos[e.target],dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,target=nodes[e.target],r=target?.node_type==='visual'?17:(DATA.semantic.some(x=>x.source===e.target||x.target===e.target)?15:12),x2=b.x-dx/d*r,y2=b.y-dy/d*r,visualStruct=['REFERENCES_FIGURE','REFERENCES_TABLE','REFERENCES_FORMULA','CAPTION_OF','HAS_CAPTION','TABLE_CONTENT_OF','HAS_TABLE_CONTENT','COLOCATED_WITH_VISUAL'].includes(e.edge_type),cls=kind===true?'semantic':kind==='proposal'?'proposal':visualStruct?'visual-structural':'',line=el('line',{x1:a.x,y1:a.y,x2,y2,class:'edge '+cls,'data-key':[e.source,e.target].join('|')});const title=el('title');title.textContent=`${compactId(e.source)} → ${compactId(e.target)} · ${e.edge_type}`;line.append(title);if(opacity)line.style.opacity=opacity;if(kind===true&&e.edge_type!=='CONTRASTS_WITH')line.setAttribute('marker-end','url(#arrow)');else if(kind==='proposal'&&e.edge_type!=='CONTRASTS_WITH')line.setAttribute('marker-end','url(#proposalArrow)');else if(visualStruct)line.setAttribute('marker-end','url(#structArrow)');if(kind===true||kind==='proposal')line.onclick=()=>selectEdge(e);else if(visualStruct)line.onclick=()=>showStructuralEdge(e);svg.append(line)}
function drawNode(n,p){const involved=DATA.semantic.some(e=>e.source===n.node_id||e.target===n.node_id),g=el('g');const title=el('title');title.textContent=compactId(n.node_id)+' — '+short(n.caption_text||n.base_summary||n.plain_text,220);g.append(title);let c;if(n.node_type==='visual')c=el('rect',{x:p.x-12,y:p.y-10,width:24,height:20,rx:3,class:'node visual-node','data-id':n.node_id});else c=el('circle',{cx:p.x,cy:p.y,r:involved?12:9,class:'node '+(n.evidence_type==='formula'?'formula-node ':'')+(involved?'semantic':''),'data-id':n.node_id});c.onclick=()=>showNode(n);g.append(c);const t=el('text',{x:p.x,y:p.y+31,class:'label','text-anchor':'middle'});t.textContent=compactId(n.node_id);g.append(t);svg.append(g)}
function mark(a,b){document.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));document.querySelectorAll('.node').forEach(x=>{if([a,b].includes(x.dataset.id))x.classList.add('selected')});document.querySelectorAll('.edge.semantic').forEach(x=>{if(x.dataset.key===[a,b].join('|'))x.classList.add('selected')})}
function highlighted(text,span){if(!span)return esc(text);const i=text.toLowerCase().indexOf(span.toLowerCase());if(i<0)return esc(text);return esc(text.slice(0,i))+'<span class="span">'+esc(text.slice(i,i+span.length))+'</span>'+esc(text.slice(i+span.length))}
function visualGallery(n){const links=DATA.structural.filter(e=>e.source===n.node_id&&['COLOCATED_WITH_VISUAL','REFERENCES_FIGURE','REFERENCES_TABLE'].includes(e.edge_type)),seen=new Set(),items=[];for(const e of links){const v=nodes[e.target];if(!v||v.node_type!=='visual'||seen.has(v.node_id))continue;seen.add(v.node_id);items.push(`<div style="margin-top:10px"><div class="meta">${esc(compactId(v.node_id))} · ${esc(v.page||'')}</div>${v.asset_data?`<img src="${v.asset_data}" style="width:100%;margin-top:6px;border-radius:6px">`:'<p>Visual asset unavailable</p>'}</div>`)}return items.length?`<div class="card"><h3>Related visuals on this page</h3>${items.join('')}</div>`:''}
function nodeCard(title,n,span){return `<div class="card"><h3>${title}: ${esc(n.node_id)}</h3><div class="meta">${esc(n.section_path?.join(' / ')||'No section')} · order ${n.document_order} · ${esc(n.discourse_role||'unclassified')} · block ${esc(n.source_members?.[0]?.block_id)}</div><p><b>${esc(n.base_summary||'')}</b></p><div class="source">${highlighted(n.original_markdown,span)}</div></div>${visualGallery(n)}`}
function selectEdge(e){selected=e;mark(e.source,e.target);const key=[e.source,e.target,e.edge_type].join('|'),r=reviews[key]||{};document.querySelector('#details').innerHTML=`<h2><span class="badge semantic">${esc(e.edge_type)}</span> <span class="confidence">${e.confidence.toFixed(2)}</span></h2><div>${e.candidate_reasons.map(x=>`<span class="badge">${esc(x)}</span>`).join('')}</div><div class="card"><h3>Verifier rationale</h3>${esc(e.rationale)}</div>${nodeCard('Source',nodes[e.source],e.source_supporting_span)}${nodeCard('Target',nodes[e.target],e.target_supporting_span)}<div class="actions"><button class="accept" onclick="review('accept')">Accept</button><button class="reject" onclick="review('reject')">Reject</button><button onclick="review('revise')">Needs revision</button></div><textarea id="note" placeholder="Reviewer note">${esc(r.note||'')}</textarea><p id="reviewStatus" class="review-status ${r.decision||''}">${r.decision?`Current decision: ${r.decision}`:''}</p>`}
function showStructuralEdge(e){mark(e.source,e.target);document.querySelector('#details').innerHTML=`<h2><span class="badge">structural</span> ${esc(e.edge_type)}</h2><div class="card"><h3>${esc(compactId(e.source))} → ${esc(compactId(e.target))}</h3><p>Confidence ${esc(e.confidence)}</p><p>${esc(e.metadata?.reference_span||e.metadata?.reason||'Deterministic document structure')}</p></div>`}
function showNode(n){if(n.node_type==='visual'){document.querySelector('#details').innerHTML=`<h2>${esc(n.node_id)}</h2><div class="card"><h3>${esc(n.visual_type)}</h3><div class="meta">${esc(n.page)} · bbox ${esc(JSON.stringify(n.bbox))}</div>${n.asset_data?`<img src="${n.asset_data}" style="width:100%;margin-top:12px;border-radius:6px">`:''}<p>${esc(n.caption_text||'No caption text')}</p></div>`;return}const fs=n.metadata?.formula_semantics,defs=fs?.symbol_definitions||{};document.querySelector('#details').innerHTML=`<h2>${esc(n.node_id)}</h2>${nodeCard('Evidence',n,'')}<div class="card"><h3>Key points</h3><ul>${(n.key_points||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h3>Concepts and entities</h3>${(n.entities||[]).map(x=>`<span class="badge">${esc(x)}</span>`).join('')}<h3>Keywords</h3>${(n.keywords||[]).map(x=>`<span class="badge">${esc(x)}</span>`).join('')}</div>${fs?`<div class="card"><h3>Formula semantics: ${esc(fs.formula_name||'')}</h3><p><b>Concept:</b> ${esc(fs.concept_definition||'')}</p><p><b>Physical interpretation:</b> ${esc(fs.physical_interpretation||'')}</p><p><b>Observational role:</b> ${esc(fs.observational_role||'')}</p><h3>Inference chain</h3><ol>${(fs.inference_chain||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ol><h3>Scientific concepts</h3>${(fs.concepts||[]).map(x=>`<span class="badge">${esc(x)}</span>`).join('')}<h3>Symbol definitions</h3><ul>${Object.entries(defs).map(([s,m])=>`<li><code>${esc(s)}</code> — ${esc(m)}</li>`).join('')}</ul></div>`:''}`}
function review(decision){if(!selected)return;const key=[selected.source,selected.target,selected.edge_type].join('|');reviews[key]={decision,note:document.querySelector('#note').value,source:selected.source,target:selected.target,edge_type:selected.edge_type};const s=document.querySelector('#reviewStatus');s.className='review-status '+decision;s.textContent='Current decision: '+decision}
function exportReviews(){const blob=new Blob([JSON.stringify({doc_id:DATA.doc_id,reviews:Object.values(reviews)},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='semantic_edge_reviews.json';a.click();URL.revokeObjectURL(a.href)}
document.querySelector('#showVisualLinks').onchange=render;document.querySelector('#showReadingOrder').onchange=render;document.querySelector('#showProposed').onchange=render;document.querySelector('#showRejected').onchange=render;window.onresize=render;render();</script></body></html>'''


def build_visualization(doc_id: str, config: dict, output: str | None = None) -> Path:
    root = Path(config["output"]["graph_root"]) / doc_id
    manifest = read_json(root / "pilot_manifest.json")
    selected = set(manifest["node_ids"])
    nodes = [n for n in read_jsonl(root / "evidence_nodes.jsonl") if n["node_id"] in selected]
    semantic = read_jsonl(root / "semantic_edges.jsonl")
    proposed = read_jsonl(root / "proposed_semantic_edges.jsonl") if (root / "proposed_semantic_edges.jsonl").exists() else semantic
    structural = read_jsonl(root / "structural_edges.jsonl")
    rejected = read_jsonl(root / "rejected_semantic_candidates.jsonl")
    validation = read_json(root / "semantic_validation_report.json")
    visuals=read_jsonl(root/"visual_nodes.jsonl") if (root/"visual_nodes.jsonl").exists() else []
    connected_visual_ids={e["source"] for e in structural if e["target"] in selected and e["source"].endswith(tuple(f"_{x:04d}" for x in range(1,100)))}
    connected_visual_ids|={e["target"] for e in structural if e["source"] in selected and ("_FIG_" in e["target"] or "_TABLE_" in e["target"])}
    visuals=[v for v in visuals if v["node_id"] in connected_visual_ids]
    for visual in visuals:
        path=Path(visual["asset_path"]) if visual.get("asset_path") else None
        if path and path.exists(): visual["asset_data"]="data:image/png;base64,"+base64.b64encode(path.read_bytes()).decode("ascii")
    data = {"doc_id": doc_id, "nodes": nodes+visuals, "semantic": semantic, "proposed": proposed, "structural": structural,
            "rejected": rejected, "malformed": validation["summary"]["malformed_llm_output_count"]}
    target = Path(output) if output else root / "semantic_pilot_review.html"
    target.write_text(TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", required=True); parser.add_argument("--config", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    print(build_visualization(args.doc_id, load_config(args.config), args.output))


if __name__ == "__main__": main()
