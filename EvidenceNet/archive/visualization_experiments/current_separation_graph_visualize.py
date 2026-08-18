from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl
from .non_llm_magazine_experiment import DOCS, _labels, _reference


STRONG_RELATION_SIGNALS = {
    "shared_entities",
    "anaphoric_reference_signal",
    "evidence_claim_signal",
    "explains_language_signal",
    "qualifies_language_signal",
    "depends_on_language_signal",
    "contrasts_with_language_signal",
    "results_in_language_signal",
    "shared_anchor_signal",
}


TEMPLATE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EvidenceNet current separation graph</title><style>
:root{--bg:#09101f;--panel:#111b2e;--panel2:#17243a;--line:#304361;--text:#edf3ff;--muted:#9cabc4;--accent:#59c8e5;--semantic:#ffb454;--supported:#55d6a5;--relabel:#f0ab32;--rejected:#7c8798;--article:#347fbc;--ad:#d96b29;--mixed:#c94962;--front:#7557b8;--order:#657792}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 system-ui,-apple-system,sans-serif}header{height:72px;padding:13px 21px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:20px}h1{font-size:19px;margin:0}header p{margin:3px 0;color:var(--muted)}select,button{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:7px 9px;border-radius:7px}button{cursor:pointer}
main{display:grid;grid-template-columns:290px minmax(600px,1fr) 390px;height:calc(100vh - 72px)}aside.left{border-right:1px solid var(--line);background:#0d1628;overflow:auto;padding:14px}.overview-button{width:100%;text-align:left;margin-bottom:9px}.item-button{width:100%;border:0;border-left:3px solid var(--line);border-radius:0;background:transparent;text-align:left;padding:8px 9px;margin:1px 0}.item-button:hover,.item-button.active{background:#192740}.item-button.commercial{border-color:var(--ad)}.item-button.mixed{border-color:var(--mixed)}.item-button.front_matter,.item-button.cover,.item-button.contents{border-color:var(--front)}.item-button small{display:block;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tree-summary{color:var(--muted);font-size:12px;margin:8px 2px 13px}.legend{border-top:1px solid var(--line);margin-top:13px;padding-top:10px;color:var(--muted);font-size:12px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}.dot.article{background:var(--article)}.dot.commercial{background:var(--ad)}.dot.mixed{background:var(--mixed)}.dot.front{background:var(--front)}
.workspace{min-width:0;overflow:auto;position:relative}.toolbar{position:sticky;top:0;z-index:6;background:#09101fee;border-bottom:1px solid var(--line);padding:9px 14px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}.toolbar span{color:var(--muted)}.policy{width:100%;font-size:11px;color:#b7c8df!important;margin-top:-5px}.paper-mark{color:var(--supported);font-weight:700}svg{display:block}.lane{fill:#0d1728;stroke:#22334c}.item-node{stroke-width:2;cursor:pointer}.item-node.article{fill:#173554;stroke:var(--article)}.item-node.commercial{fill:#4f2b1b;stroke:var(--ad)}.item-node.mixed{fill:#4f2630;stroke:var(--mixed)}.item-node.front_matter,.item-node.cover,.item-node.contents{fill:#302750;stroke:var(--front)}.item-node.other{fill:#1d304b;stroke:#7186a6}.item-node:hover,.item-node.selected{stroke:white;stroke-width:4}.item-label{fill:var(--text);font-size:10px;pointer-events:none}.item-sub{fill:var(--muted);font-size:8.5px;pointer-events:none}.order-edge{stroke:var(--order);stroke-width:1.2;opacity:.48;fill:none}.semantic-edge{stroke:var(--semantic);stroke-width:2.5;fill:none;cursor:pointer}.semantic-edge.supported{stroke:var(--supported)}.semantic-edge.relabel{stroke:var(--relabel);stroke-dasharray:7 4}.semantic-edge.reject{stroke:var(--rejected);stroke-dasharray:3 5;opacity:.36}.semantic-edge.proposed{stroke:#bb83e8;stroke-dasharray:7 5;opacity:.67}.semantic-edge.selected{stroke:white;stroke-width:5;opacity:1}.evidence-node{fill:#203452;stroke:#7d92b2;stroke-width:1.7;cursor:pointer}.evidence-node.commercial{fill:#57301d;stroke:var(--ad)}.evidence-node.involved{stroke:var(--semantic);stroke-width:3}.evidence-node.selected{stroke:white;stroke-width:4}.node-label{fill:var(--text);font-size:9.5px;pointer-events:none}.section-title{fill:var(--muted);font-size:12px;font-weight:700}
aside.right{border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:17px}aside.right h2{font-size:16px;margin:0 0 10px}.empty{color:var(--muted);padding:35px 3px}.badge{display:inline-block;padding:3px 7px;border-radius:11px;background:#273955;color:#d9e5f7;margin:2px 4px 2px 0;font-size:11px}.badge.commercial{background:#61351d;color:#ffc89f}.badge.mixed{background:#612a39;color:#ffc2cf}.badge.supported{background:#185044;color:#a9f2da}.badge.relabel{background:#584214;color:#ffdfa0}.badge.reject{background:#3b424c;color:#d8dce2}.badge.proposed{background:#49305e;color:#e4bfff}.card{background:#0c1626;border:1px solid var(--line);border-radius:8px;padding:11px;margin:10px 0}.card h3{font-size:12px;color:var(--accent);margin:0 0 7px}.source{white-space:pre-wrap;color:#d2ddec;max-height:310px;overflow:auto}.meta{color:var(--muted);font-size:12px}.reason{color:#f1d7a8}.stats{width:100%;border-collapse:collapse}.stats td{border-bottom:1px solid var(--line);padding:5px}.stats td:last-child{text-align:right;font-weight:700}
@media(max-width:1050px){main{grid-template-columns:235px minmax(560px,1fr)}aside.right{position:fixed;right:0;top:72px;bottom:0;width:380px;z-index:10;box-shadow:-10px 0 30px #0008}.left{font-size:12px}}
</style></head><body><header><div><h1>EvidenceNet scientific relation graph</h1><p>Publication view of non-LLM content separation and evidence relations</p></div><label>Magazine <select id="docSelect"></select></label></header><main><aside class="left"><button class="overview-button" id="fullGraphButton">◉ Full Evidence graph</button><button class="overview-button" id="overviewButton">▾ Content-item overview</button><div class="tree-summary" id="treeSummary"></div><div id="tree"></div><div class="legend"><div><span class="dot article"></span>editorial/scientific item</div><div><span class="dot commercial"></span>commercial item</div><div><span class="dot mixed"></span>mixed predicted item</div><div><span class="dot front"></span>front matter</div></div></aside><section class="workspace"><div class="toolbar"><button id="backButton" hidden>← Full graph</button><b id="viewTitle">Full Evidence graph</b><span id="viewSummary"></span><label>Relation set <select id="edgeMode"><option value="paper">Paper (strict)</option><option value="expanded">Expanded high-confidence</option><option value="raw">Raw verifier output</option></select></label><label><input type="checkbox" id="showOrder"> reading order</label><label><input type="checkbox" id="showSemantic" checked> semantic</label><label><input type="checkbox" id="showProposed"> proposed</label><label><input type="checkbox" id="showRejected"> audited rejects</label><span class="policy" id="edgePolicy"></span></div><svg id="graph"></svg></section><aside class="right" id="details"><div class="empty">Select a content item, Evidence node, or semantic edge.</div></aside></main>
<script>const D=__DATA__,DEFAULT_EDGE_MODE='__DEFAULT_EDGE_MODE__',NS='http://www.w3.org/2000/svg';let doc=null,currentItem=null,fullView=true;const svg=document.querySelector('#graph');function el(n,a={}){const x=document.createElementNS(NS,n);for(const[k,v]of Object.entries(a))x.setAttribute(k,v);return x}function esc(s){const x=document.createElement('div');x.textContent=s??'';return x.innerHTML}function compact(id){const m=id.match(/EV_0*(\d+)$/);return m?'EV-'+m[1]:id}function short(s,n=38){s=(s||'').replace(/\s+/g,' ');return s.length>n?s.slice(0,n-1)+'…':s}function kindClass(k){return['commercial','mixed','front_matter','cover','contents'].includes(k)?k:'article'}
const select=document.querySelector('#docSelect');select.innerHTML=D.documents.map((d,i)=>`<option value="${i}">${d.short_name}</option>`).join('');select.onchange=()=>loadDocument(Number(select.value));document.querySelector('#fullGraphButton').onclick=fullGraph;document.querySelector('#overviewButton').onclick=overview;document.querySelector('#backButton').onclick=fullGraph;for(const id of ['showOrder','showSemantic','showProposed','showRejected'])document.querySelector('#'+id).onchange=render;
const edgeMode=document.querySelector('#edgeMode');edgeMode.value=DEFAULT_EDGE_MODE;edgeMode.onchange=render;function filteredVerified(){const mode=edgeMode.value;if(mode==='paper')return doc.semantic.filter(e=>e.paper_grade);if(mode==='expanded')return doc.semantic.filter(e=>e.expanded_grade);return doc.semantic}function policyText(){if(edgeMode.value==='paper')return 'Paper rule: confidence ≥ 0.90 · within one separated item · no commercial endpoint · explicit linguistic/entity signal.';if(edgeMode.value==='expanded')return 'Expanded rule: confidence ≥ 0.90 · within one separated item · no commercial endpoint.';return 'Raw view: every first-pass verifier acceptance; use for diagnosis, not as the publication figure.'}
function loadDocument(index){doc=D.documents[index];currentItem=null;fullView=true;document.querySelector('#treeSummary').innerHTML=`${doc.nodes.length} Evidence nodes · ${doc.items.length} separated items<br><span class="paper-mark">${doc.paper_edge_count} paper-grade relations</span> · ${doc.expanded_edge_count} expanded · ${doc.semantic.length} raw`;document.querySelector('#tree').innerHTML=doc.items.map((u,i)=>`<button class="item-button ${kindClass(u.kind)}" data-index="${i}"><b>${u.display_id}</b><small>${esc(u.label)}</small><small>${u.node_ids.length} nodes · ${esc(u.pages.join(', '))}</small></button>`).join('');document.querySelectorAll('.item-button').forEach(b=>b.onclick=()=>showItem(Number(b.dataset.index)));fullGraph()}
function setActive(){document.querySelector('#fullGraphButton').classList.toggle('active',fullView);document.querySelector('#overviewButton').classList.toggle('active',!fullView&&currentItem===null);document.querySelectorAll('.item-button').forEach((b,i)=>b.classList.toggle('active',!fullView&&currentItem===i))}
function clearDetails(){document.querySelector('#details').innerHTML='<div class="empty">Select a content item, Evidence node, or semantic edge.</div>'}function visibleSemantic(){return[...(document.querySelector('#showSemantic').checked?filteredVerified():[]),...(document.querySelector('#showProposed').checked?doc.proposed:[])]}function updatePolicy(){document.querySelector('#edgePolicy').textContent=policyText();const visible=visibleSemantic().filter(acceptedEdge).length;if(fullView)document.querySelector('#viewTitle').textContent=edgeMode.value==='paper'?'Paper relation graph':'Full Evidence graph';document.querySelector('#viewSummary').textContent=`${doc.nodes.length} nodes · ${visible} visible relations`;}function render(){updatePolicy();if(fullView)renderFull();else if(currentItem===null)renderOverview();else renderItem(currentItem)}
function fullGraph(){currentItem=null;fullView=true;setActive();document.querySelector('#backButton').hidden=true;document.querySelector('#viewTitle').textContent=edgeMode.value==='paper'?'Paper relation graph':'Full Evidence graph';clearDetails();render()}
function overview(){currentItem=null;fullView=false;setActive();document.querySelector('#backButton').hidden=false;document.querySelector('#viewTitle').textContent='Content-item overview';document.querySelector('#viewSummary').textContent=`${doc.items.length} separated items · ${doc.bridges.length} verified cross-item semantic links`;clearDetails();renderOverview()}
function defs(){const d=el('defs');d.innerHTML='<marker id="orderArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#657792"/></marker><marker id="semArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ffb454"/></marker>';svg.append(d)}
function acceptedEdge(e){return e.audit_status!=='reject'||document.querySelector('#showRejected').checked}
function renderFull(){svg.innerHTML='';defs();const items=doc.items,edges=visibleSemantic().filter(acceptedEdge),maxNodes=Math.max(...items.map(u=>u.node_ids.length),1),dx=66,dy=94,left=245,top=76,W=Math.max(1050,left+maxNodes*dx+80),H=Math.max(650,top+items.length*dy);svg.setAttribute('width',W);svg.setAttribute('height',H);svg.style.width=W+'px';svg.style.height=H+'px';const pos={},itemByNode={};items.forEach((u,i)=>{const y=top+i*dy;svg.append(el('rect',{x:12,y:y-37,width:W-24,height:74,rx:9,class:'lane'}));const label=el('text',{x:27,y:y-10,class:'section-title'});label.textContent=u.display_id+(u.kind==='commercial'?' · AD':u.kind==='mixed'?' · MIXED':'')+' · '+short(u.label,28);svg.append(label);const meta=el('text',{x:27,y:y+10,class:'item-sub'});meta.textContent=u.node_ids.length+' nodes · '+short(u.pages.join(','),24);svg.append(meta);u.node_ids.forEach((id,j)=>{pos[id]={x:left+j*dx,y};itemByNode[id]=u})});if(document.querySelector('#showOrder').checked)items.forEach(u=>{for(let i=1;i<u.node_ids.length;i++){const a=pos[u.node_ids[i-1]],b=pos[u.node_ids[i]];svg.append(el('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'order-edge','marker-end':'url(#orderArrow)'}))}});edges.forEach((e,i)=>{const a=pos[e.source],b=pos[e.target];if(!a||!b)return;const cross=Math.abs(a.y-b.y)>1,controlX=(a.x+b.x)/2,controlY=cross?(a.y+b.y)/2:a.y-24-(i%5)*8,p=el('path',{d:`M${a.x},${a.y} Q${controlX},${controlY} ${b.x},${b.y}`,class:'semantic-edge '+(e.audit_status||''),'marker-end':'url(#semArrow)'});p.onclick=()=>showEdge(e,p);const t=el('title');t.textContent=`${e.edge_type}: ${compact(e.source)} → ${compact(e.target)}`;p.append(t);svg.append(p)});const involved=new Set(edges.flatMap(e=>[e.source,e.target]));doc.nodes.forEach(n=>{const p=pos[n.id],u=itemByNode[n.id],c=el('circle',{cx:p.x,cy:p.y,r:9,class:'evidence-node '+(u.kind==='commercial'?'commercial ':'')+(involved.has(n.id)?'involved':''),'data-id':n.id});c.onclick=()=>showNode(n,c,u);svg.append(c);const t=el('text',{x:p.x,y:p.y+22,'text-anchor':'middle',class:'node-label'});t.textContent=compact(n.id);svg.append(t)})}
function renderOverview(){svg.innerHTML='';defs();const items=doc.items,bridges=visibleSemantic().filter(e=>e.source_item!==e.target_item&&acceptedEdge(e)),cols=5,dx=175,dy=118,left=105,top=90,W=Math.max(950,left*2+(Math.min(cols,Math.max(1,items.length))-1)*dx),H=Math.max(650,top+Math.ceil(items.length/cols)*dy);svg.setAttribute('width',W);svg.setAttribute('height',H);svg.style.width=W+'px';svg.style.height=H+'px';svg.append(el('rect',{x:15,y:25,width:W-30,height:H-50,rx:14,class:'lane'}));const title=el('text',{x:34,y:53,class:'section-title'});title.textContent=doc.short_name+' · current non-LLM separation';svg.append(title);const pos={};items.forEach((u,i)=>pos[u.id]={x:left+(i%cols)*dx,y:top+Math.floor(i/cols)*dy});if(document.querySelector('#showOrder').checked)for(let i=1;i<items.length;i++){const a=pos[items[i-1].id],b=pos[items[i].id];svg.append(el('line',{x1:a.x+57,y1:a.y,x2:b.x-57,y2:b.y,class:'order-edge','marker-end':'url(#orderArrow)'}))}bridges.forEach((e,i)=>{const a=pos[e.source_item],b=pos[e.target_item];if(!a||!b)return;const p=el('path',{d:`M${a.x},${a.y} Q${(a.x+b.x)/2},${(a.y+b.y)/2-35-(i%3)*12} ${b.x},${b.y}`,class:'semantic-edge '+(e.audit_status||''),'marker-end':'url(#semArrow)'});p.onclick=()=>showEdge(e,p);const t=el('title');t.textContent=`${e.edge_type}: ${e.source_order} → ${e.target_order}`;p.append(t);svg.append(p)});const internal={};visibleSemantic().filter(acceptedEdge).forEach(e=>{if(e.source_item===e.target_item)internal[e.source_item]=(internal[e.source_item]||0)+1});items.forEach((u,i)=>{const p=pos[u.id],r=el('rect',{x:p.x-65,y:p.y-31,width:130,height:62,rx:9,class:'item-node '+kindClass(u.kind),'data-index':i});r.onclick=()=>showItem(i);svg.append(r);const a=el('text',{x:p.x,y:p.y-12,'text-anchor':'middle',class:'item-label'});a.textContent=u.display_id+(u.kind==='commercial'?' · AD':u.kind==='mixed'?' · MIXED':'');svg.append(a);const b=el('text',{x:p.x,y:p.y+3,'text-anchor':'middle',class:'item-sub'});b.textContent=short(u.label,24);svg.append(b);const c=el('text',{x:p.x,y:p.y+17,'text-anchor':'middle',class:'item-sub'});c.textContent=u.node_ids.length+' nodes · '+(internal[u.id]||0)+' semantic';svg.append(c)})}
function showItem(index){currentItem=index;fullView=false;setActive();const u=doc.items[index];document.querySelector('#backButton').hidden=false;document.querySelector('#viewTitle').textContent=u.display_id+' · '+u.label;document.querySelector('#viewSummary').textContent=`${u.node_ids.length} nodes · ${u.pages.join(', ')}`;showItemDetails(u);renderItem(index)}
function renderItem(index){svg.innerHTML='';defs();const u=doc.items[index],nodes=u.node_ids.map(id=>doc.node_by_id[id]),inside=new Set(u.node_ids),edges=visibleSemantic().filter(e=>inside.has(e.source)&&inside.has(e.target)&&acceptedEdge(e)),cols=5,dx=155,dy=115,left=90,top=95,W=Math.max(900,left*2+(Math.min(cols,Math.max(1,nodes.length))-1)*dx),H=Math.max(590,top+Math.ceil(nodes.length/cols)*dy);svg.setAttribute('width',W);svg.setAttribute('height',H);svg.style.width=W+'px';svg.style.height=H+'px';svg.append(el('rect',{x:15,y:25,width:W-30,height:H-50,rx:14,class:'lane'}));const title=el('text',{x:34,y:54,class:'section-title'});title.textContent=u.display_id+' · '+u.label;svg.append(title);const pos={};nodes.forEach((n,i)=>pos[n.id]={x:left+(i%cols)*dx,y:top+Math.floor(i/cols)*dy});if(document.querySelector('#showOrder').checked)for(let i=1;i<nodes.length;i++){const a=pos[nodes[i-1].id],b=pos[nodes[i].id],line=el('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'order-edge','marker-end':'url(#orderArrow)'});svg.append(line)}edges.forEach((e,i)=>{const a=pos[e.source],b=pos[e.target],p=el('path',{d:`M${a.x},${a.y} Q${(a.x+b.x)/2},${(a.y+b.y)/2-30-(i%3)*10} ${b.x},${b.y}`,class:'semantic-edge '+(e.audit_status||''),'marker-end':'url(#semArrow)'});p.onclick=()=>showEdge(e,p);svg.append(p)});const involved=new Set(edges.flatMap(e=>[e.source,e.target]));nodes.forEach(n=>{const p=pos[n.id],c=el('circle',{cx:p.x,cy:p.y,r:13,class:'evidence-node '+(u.kind==='commercial'?'commercial ':'')+(involved.has(n.id)?'involved':''),'data-id':n.id});c.onclick=()=>showNode(n,c,u);svg.append(c);const t=el('text',{x:p.x,y:p.y+29,'text-anchor':'middle',class:'node-label'});t.textContent=compact(n.id);svg.append(t);const q=el('text',{x:p.x,y:p.y+42,'text-anchor':'middle',class:'item-sub'});q.textContent='order '+n.order;svg.append(q)})}
function deselect(){document.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'))}function showItemDetails(u){document.querySelector('#details').innerHTML=`<h2>${esc(u.display_id)}</h2><span class="badge ${kindClass(u.kind)}">${esc(u.kind)}</span>${u.reference_clean===false?'<span class="badge mixed">boundary error</span>':''}<div class="card"><h3>${esc(u.label)}</h3><div class="meta">${u.node_ids.length} Evidence nodes · orders ${u.start_order}–${u.end_order}<br>${esc(u.pages.join(', '))}</div></div><div class="card"><h3>Reference items overlapping this predicted item</h3>${u.references.map(r=>`<p><b>${esc(r.label)}</b><br><span class="meta">${esc(r.kind)} · ${esc(r.source_page)} · ${r.cleanly_separated?'clean':'not clean'}</span></p>`).join('')}</div>`}
function showNode(n,c,u){deselect();c.classList.add('selected');document.querySelector('#details').innerHTML=`<h2>${esc(compact(n.id))}</h2>${u.kind==='commercial'?'<span class="badge commercial">commercial item</span>':''}<div class="card"><h3>Evidence node</h3><div class="meta">order ${n.order} · ${esc(n.pages.join(', '))} · ${esc(n.evidence_type)}</div><p><b>${esc(n.summary)}</b></p><div class="source">${esc(n.text)}</div></div>`}
function showEdge(e,p){deselect();p.classList.add('selected');document.querySelectorAll('.evidence-node').forEach(n=>{if(n.dataset.id===e.source||n.dataset.id===e.target)n.classList.add('selected')});document.querySelector('#details').innerHTML=`<h2>${esc(e.edge_type)}</h2><span class="badge ${e.audit_status||''}">${esc(e.audit_status||'accepted')}</span><span class="badge">confidence ${e.confidence.toFixed(2)}</span><div class="card"><h3>Connection</h3><div class="reason">${esc(e.audit_reason||e.rationale)}</div></div><div class="card"><h3>${esc(compact(e.source))} · order ${e.source_order}</h3><div class="source">${esc(e.source_text)}</div></div><div class="card"><h3>${esc(compact(e.target))} · order ${e.target_order}</h3><div class="source">${esc(e.target_text)}</div></div>`}
select.value='1';loadDocument(1);</script></body></html>'''


def _short_name(doc: str) -> str:
    return {DOCS[0]: "2022 Nov/Dec", DOCS[1]: "2025 Jan/Feb", DOCS[2]: "2026 May/Jun"}[doc]


def _build_document(output_root: Path, experiment: Path, audit_by_key: dict, doc: str) -> dict:
    graph_root = output_root / "evidence_graph" / doc
    nodes = sorted(read_jsonl(graph_root / "evidence_nodes.jsonl"), key=lambda row: row["document_order"])
    node_by_id = {row["node_id"]: row for row in nodes}
    _, reference_tuples = _reference(doc, nodes)
    commercial_labels = _labels(reference_tuples, len(nodes))
    commercial_by_node = {
        row["node_id"]: bool(commercial_labels[row["document_order"] - 1]) for row in nodes
    }
    assignments = read_jsonl(experiment / doc / "assignments.jsonl")
    item_rows = read_jsonl(experiment / doc / "item_evaluation.jsonl")
    full_semantic_path = graph_root / "semantic_full_edges.jsonl"
    semantic_path = full_semantic_path if full_semantic_path.exists() else graph_root / "semantic_edges.jsonl"
    semantic_rows = read_jsonl(semantic_path)
    proposed_rows = read_jsonl(graph_root / "proposed_semantic_edges.jsonl")

    item_by_node = {row["node_id"]: row["content_item_id"] for row in assignments}
    members: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        members[item_by_node[node["node_id"]]].append(node)
    ordered_items = sorted(members, key=lambda item_id: members[item_id][0]["document_order"])

    rendered_items = []
    for number, item_id in enumerate(ordered_items, 1):
        item_nodes = members[item_id]
        start = item_nodes[0]["document_order"]
        end = item_nodes[-1]["document_order"]
        references = [row for row in item_rows
                      if row["start_document_order"] <= end and row["end_document_order"] >= start]
        kinds = {row["kind"] for row in references}
        if kinds == {"commercial"}:
            kind = "commercial"
        elif "commercial" in kinds:
            kind = "mixed"
        elif references:
            kind = references[0]["kind"]
        else:
            kind = "other"
        labels = [row["label"] for row in references]
        label = " + ".join(labels[:2]) + (f" + {len(labels) - 2} more" if len(labels) > 2 else "")
        pages = []
        for node in item_nodes:
            for page in node.get("page_ids") or []:
                if page not in pages:
                    pages.append(page)
        rendered_items.append({
            "id": item_id,
            "display_id": f"ITEM {number:03d}",
            "kind": kind,
            "label": label or (item_nodes[0].get("base_summary") or "Unlabelled item")[:100],
            "node_ids": [row["node_id"] for row in item_nodes],
            "start_order": start,
            "end_order": end,
            "pages": pages,
            "reference_clean": all(row["cleanly_separated"] for row in references),
            "references": [{key: row[key] for key in (
                "label", "kind", "source_page", "cleanly_separated")} for row in references],
        })

    def enrich_edge(row: dict, default_status: str) -> dict:
        source = node_by_id[row["source"]]
        target = node_by_id[row["target"]]
        audit = audit_by_key.get((doc, row["source"], row["target"], row["edge_type"]), {})
        within_current_item = item_by_node[row["source"]] == item_by_node[row["target"]]
        touches_commercial = commercial_by_node[row["source"]] or commercial_by_node[row["target"]]
        strong_signal = bool(STRONG_RELATION_SIGNALS.intersection(row.get("candidate_reasons") or []))
        expanded_grade = (
            row.get("confidence", 0) >= 0.9 and within_current_item and not touches_commercial
        )
        return {
            **row,
            "source_order": source["document_order"],
            "target_order": target["document_order"],
            "source_text": source.get("plain_text") or source.get("original_markdown") or "",
            "target_text": target.get("plain_text") or target.get("original_markdown") or "",
            "source_item": item_by_node[row["source"]],
            "target_item": item_by_node[row["target"]],
            "within_current_item": within_current_item,
            "touches_commercial": touches_commercial,
            "strong_signal": strong_signal,
            "expanded_grade": expanded_grade,
            "paper_grade": expanded_grade and strong_signal,
            "audit_status": audit.get("status", default_status),
            "audit_reason": audit.get("reason", ""),
        }

    semantic = [enrich_edge(row, "verified") for row in semantic_rows]
    semantic_keys = {(row["source"], row["target"], row["edge_type"]) for row in semantic}
    proposed = [enrich_edge(row, "proposed") for row in proposed_rows
                if (row["source"], row["target"], row["edge_type"]) not in semantic_keys]
    return {
        "doc_id": doc,
        "short_name": _short_name(doc),
        "nodes": [
            {"id": row["node_id"], "order": row["document_order"],
             "pages": row.get("page_ids") or [], "evidence_type": row.get("evidence_type", "text"),
             "summary": row.get("base_summary") or "",
             "text": row.get("plain_text") or row.get("original_markdown") or ""}
            for row in nodes],
        "node_by_id": {
            row["node_id"]: {"id": row["node_id"], "order": row["document_order"],
                             "pages": row.get("page_ids") or [],
                             "evidence_type": row.get("evidence_type", "text"),
                             "summary": row.get("base_summary") or "",
                             "text": row.get("plain_text") or row.get("original_markdown") or ""}
            for row in nodes},
        "items": rendered_items,
        "semantic": semantic,
        "paper_edge_count": sum(row["paper_grade"] for row in semantic),
        "expanded_edge_count": sum(row["expanded_grade"] for row in semantic),
        "semantic_scope": "full-document" if full_semantic_path.exists() else "pilot",
        "proposed": proposed,
        "bridges": [row for row in semantic if row["source_item"] != row["target_item"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize current non-LLM separation as a hierarchical graph")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--experiment-dir", default="output/non_llm_commercial_experiment")
    parser.add_argument("--audit-review", default="output/publication_graph_audit/semantic_edge_review.jsonl")
    parser.add_argument("--output", default="output/non_llm_commercial_experiment/current_separation_graph.html")
    parser.add_argument("--default-edge-mode", choices=("paper", "expanded", "raw"), default="raw")
    args = parser.parse_args()
    reviews = read_jsonl(args.audit_review) if Path(args.audit_review).exists() else []
    audit_by_key = {
        (row["doc_id"], row["source"], row["target"], row["edge_type"]): row for row in reviews}
    data = {"documents": [
        _build_document(Path(args.output_root), Path(args.experiment_dir), audit_by_key, doc)
        for doc in DOCS]}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    html = html.replace("__DEFAULT_EDGE_MODE__", args.default_edge_mode)
    target.write_text(html, encoding="utf-8")
    print(json.dumps({"output": str(target), "documents": len(data["documents"]),
                      "items": sum(len(row["items"]) for row in data["documents"]),
                      "nodes": sum(len(row["nodes"]) for row in data["documents"]),
                      "semantic_edges": sum(len(row["semantic"]) for row in data["documents"]),
                      "proposed_edges": sum(len(row["proposed"]) for row in data["documents"])}, indent=2))


if __name__ == "__main__":
    main()
