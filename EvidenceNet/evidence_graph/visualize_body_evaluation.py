from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl


ROOT = Path("output/scientific_body_semantics")
DOC = "gw150914_detection"
MODELS = ("Qwen3.5-35B-A3B", "Qwen3.6-35B-A3B")


def pair(a, b):
    return tuple(sorted((a, b)))


def compact(node_id):
    return "EV-" + str(int(node_id.rsplit("_EV_", 1)[-1]))


def build_data():
    shared = ROOT / "shared_candidates" / DOC
    all_nodes = {row["node_id"]: row for row in read_jsonl(shared / "evidence_nodes.jsonl")}
    candidates = {pair(row["node_a"], row["node_b"]) for row in read_jsonl(shared / "candidates.jsonl")}
    gold_rows = read_jsonl(Path("evaluation/ground_truth") / DOC / "all_pairs_ground_truth.jsonl")
    reference_ids = sorted({value for row in gold_rows for value in (row["node_a"], row["node_b"])},
                           key=lambda value: all_nodes[value]["document_order"])
    gold = {pair(row["node_a"], row["node_b"]): row for row in gold_rows}
    positive = {key: row for key, row in gold.items() if row["gold_label"] == "RELATION"}
    nodes = []
    for node_id in reference_ids:
        node = all_nodes[node_id]
        nodes.append({"id": node_id, "label": compact(node_id), "order": node["document_order"],
                      "section": " / ".join(node.get("section_path") or ["Unsectioned"]),
                      "summary": node.get("base_summary") or "", "text": node.get("plain_text") or ""})
    model_data = {}
    for model in MODELS:
        accepted = read_jsonl(ROOT / model / DOC / "accepted_edges.jsonl")
        accepted_by_pair = {pair(row["source"], row["target"]): row for row in accepted}
        edges = []
        for key, row in positive.items():
            predicted = accepted_by_pair.get(key)
            if predicted:
                relation_ok = predicted["edge_type"] == row["gold_relation"]
                direction_ok = (predicted["source"] == row["gold_source"]
                                and predicted["target"] == row["gold_target"])
                if relation_ok and direction_ok:
                    status = "exact"
                elif not relation_ok and not direction_ok:
                    status = "wrong_both"
                elif not relation_ok:
                    status = "wrong_relation"
                else:
                    status = "wrong_direction"
                edges.append({"source": predicted["source"], "target": predicted["target"],
                              "predicted_relation": predicted["edge_type"], "gold_source": row["gold_source"],
                              "gold_target": row["gold_target"], "gold_relation": row["gold_relation"],
                              "status": status, "confidence": predicted.get("confidence"),
                              "rationale": predicted.get("rationale", "")})
            else:
                edges.append({"source": row["gold_source"], "target": row["gold_target"],
                              "predicted_relation": "NONE", "gold_source": row["gold_source"],
                              "gold_target": row["gold_target"], "gold_relation": row["gold_relation"],
                              "status": "missed_verifier" if key in candidates else "missed_candidate",
                              "confidence": None, "rationale": ""})
        unreviewed = sum(pair(row["source"], row["target"]) not in gold for row in accepted)
        model_data[model] = {"edges": edges, "accepted_total": len(accepted), "unreviewed": unreviewed}
    return {"doc": DOC, "nodes": nodes, "models": model_data}


TEMPLATE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scientific-body relation evaluation</title><style>
:root{--bg:#08101f;--panel:#101b30;--line:#304260;--text:#eaf0fb;--muted:#9cabc4;--green:#4bd18b;--amber:#ffb454;--red:#ff6678;--gray:#687890;--purple:#ba8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}header{padding:15px 22px;border-bottom:1px solid var(--line);display:flex;gap:22px;align-items:center;flex-wrap:wrap}h1{font-size:19px;margin:0}select,label{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:7px}.legend span{margin-right:14px}.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px}.layout{display:grid;grid-template-columns:minmax(650px,1fr) 430px;height:calc(100vh - 78px)}#graphWrap{overflow:auto;padding:12px}svg{background:#0b1528;border:1px solid var(--line);border-radius:10px}.node{fill:#1b2b49;stroke:#7890b5;stroke-width:2;cursor:pointer}.node.active{stroke:#fff;stroke-width:4}.node-label{fill:var(--text);font-size:12px;text-anchor:middle;pointer-events:none}.edge{fill:none;stroke-width:3;opacity:.85;cursor:pointer}.edge.exact{stroke:var(--green)}.edge.wrong_relation{stroke:var(--amber)}.edge.wrong_direction,.edge.wrong_both{stroke:var(--red)}.edge.missed_verifier{stroke:var(--gray);stroke-dasharray:7 5;opacity:.45}.edge.missed_candidate{stroke:var(--purple);stroke-dasharray:3 6;opacity:.45}.edge.active{stroke:#fff;stroke-width:6;opacity:1}aside{border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:17px}.card{border:1px solid var(--line);background:#0b1528;border-radius:9px;padding:12px;margin-bottom:13px}.muted{color:var(--muted)}.badge{display:inline-block;padding:3px 7px;border-radius:10px;margin:2px;background:#263956}.bad{color:#ff98a5}.good{color:#78e4ab}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:7px 5px}tr{cursor:pointer}tr:hover{background:#172641}.summary{color:var(--muted)}
@media(max-width:1000px){.layout{grid-template-columns:1fr}aside{border-left:0;height:auto}.layout{height:auto}}
</style></head><body><header><h1>GW150914 scientific-body relation evaluation</h1><select id="model"></select><label><input type="checkbox" id="showMissed"> show missed gold relations</label><div class="legend"><span><i class="dot" style="background:var(--green)"></i>exact</span><span><i class="dot" style="background:var(--amber)"></i>wrong relation</span><span><i class="dot" style="background:var(--red)"></i>wrong direction/both</span><span><i class="dot" style="background:var(--gray)"></i>missed</span></div><div class="summary" id="summary"></div></header><div class="layout"><div id="graphWrap"><svg id="graph" width="1250" height="650"></svg></div><aside><div id="detail" class="card muted">Click an edge to inspect the predicted and reference relations.</div><div class="card"><h3>Wrong accepted relations</h3><table><thead><tr><th>Pair</th><th>Predicted</th><th>Reference</th><th>Error</th></tr></thead><tbody id="errors"></tbody></table></div><div class="card"><h3>Interpretation</h3><p>A red or amber line does not mean the nodes are unrelated. It means the accepted pair has an incorrect direction, relation label, or both. Dashed edges are gold relations that the pipeline missed.</p><p class="muted">Accepted edges outside the 22-node reference are not shown because their correctness has not been annotated.</p></div></aside></div>
<script>const DATA=__DATA__,svg=document.querySelector('#graph'),NS='http://www.w3.org/2000/svg',nodeById=Object.fromEntries(DATA.nodes.map(x=>[x.id,x]));let visibleEdges=[];
for(const name of Object.keys(DATA.models)){const o=document.createElement('option');o.value=o.textContent=name;model.append(o)}
function el(n,a={}){const x=document.createElementNS(NS,n);for(const[k,v]of Object.entries(a))x.setAttribute(k,v);return x}function esc(s){const d=document.createElement('div');d.textContent=s??'';return d.innerHTML}function short(s,n=280){s=(s||'').replace(/\s+/g,' ');return s.length>n?s.slice(0,n-1)+'…':s}
function positions(){const p={},cols=11,x0=70,y0=100,dx=110,dy=370;DATA.nodes.forEach((n,i)=>p[n.id]={x:x0+(i%cols)*dx,y:y0+Math.floor(i/cols)*dy});return p}
function edgePath(a,b,index){const dx=b.x-a.x,dy=b.y-a.y,curve=35+18*(index%5),cx=(a.x+b.x)/2-dy/Math.max(1,Math.hypot(dx,dy))*curve,cy=(a.y+b.y)/2+dx/Math.max(1,Math.hypot(dx,dy))*curve;return`M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`}
function render(){svg.innerHTML='';const p=positions(),all=DATA.models[model.value].edges,show=showMissed.checked;visibleEdges=all.filter(e=>show||!e.status.startsWith('missed'));const defs=el('defs');defs.innerHTML='<marker id="green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#4bd18b"/></marker><marker id="amber" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ffb454"/></marker><marker id="red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#ff6678"/></marker>';svg.append(defs);visibleEdges.forEach((e,i)=>{const path=el('path',{d:edgePath(p[e.source],p[e.target],i),class:'edge '+e.status,'data-i':i});if(e.status==='exact')path.setAttribute('marker-end','url(#green)');else if(e.status==='wrong_relation')path.setAttribute('marker-end','url(#amber)');else if(['wrong_direction','wrong_both'].includes(e.status))path.setAttribute('marker-end','url(#red)');path.onclick=()=>showEdge(e,path);const t=el('title');t.textContent=`${nodeById[e.source].label} ${e.predicted_relation} ${nodeById[e.target].label}`;path.append(t);svg.append(path)});DATA.nodes.forEach(n=>{const g=el('g'),c=el('circle',{cx:p[n.id].x,cy:p[n.id].y,r:18,class:'node'});c.onclick=()=>showNode(n,c);g.append(c);const t=el('text',{x:p[n.id].x,y:p[n.id].y+38,class:'node-label'});t.textContent=n.label;g.append(t);svg.append(g)});renderTable(all);const m=DATA.models[model.value],counts=Object.fromEntries(['exact','wrong_relation','wrong_direction','wrong_both','missed_verifier','missed_candidate'].map(s=>[s,all.filter(e=>e.status===s).length]));summary.textContent=`${m.accepted_total} accepted total · ${counts.exact} exact · ${counts.wrong_relation+counts.wrong_direction+counts.wrong_both} wrong annotations · ${m.unreviewed} unreviewed`}
function clear(){document.querySelectorAll('.active').forEach(x=>x.classList.remove('active'))}function showEdge(e,path){clear();path.classList.add('active');const status=e.status.replaceAll('_',' ');detail.innerHTML=`<h2 class="${e.status==='exact'?'good':'bad'}">${esc(status)}</h2><p><b>Predicted:</b> ${esc(nodeById[e.source].label)} → ${esc(e.predicted_relation)} → ${esc(nodeById[e.target].label)}</p><p><b>Reference:</b> ${esc(nodeById[e.gold_source].label)} → ${esc(e.gold_relation)} → ${esc(nodeById[e.gold_target].label)}</p>${e.confidence!=null?`<p>Confidence: ${Number(e.confidence).toFixed(2)}</p>`:''}<p class="muted">${esc(e.rationale||'No accepted-edge rationale: the gold relation was missed.')}</p>`}function showNode(n,c){clear();c.classList.add('active');detail.innerHTML=`<h2>${esc(n.label)}</h2><p class="muted">${esc(n.section)} · order ${n.order}</p><p><b>${esc(n.summary)}</b></p><p>${esc(short(n.text))}</p>`}
function renderTable(edges){errors.innerHTML='';edges.filter(e=>e.status.startsWith('wrong')).forEach(e=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${esc(nodeById[e.source].label)}–${esc(nodeById[e.target].label)}</td><td>${esc(e.predicted_relation)}</td><td>${esc(e.gold_relation)}</td><td>${esc(e.status.replaceAll('_',' '))}</td>`;tr.onclick=()=>{const i=visibleEdges.indexOf(e);if(i<0){showMissed.checked=false;render()}const path=[...document.querySelectorAll('.edge')][visibleEdges.indexOf(e)];showEdge(e,path)};errors.append(tr)})}
model.onchange=render;showMissed.onchange=render;model.value=Object.keys(DATA.models)[0];render();</script></body></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "scientific_body_relation_evaluation.html"))
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE.replace("__DATA__", json.dumps(build_data(), ensure_ascii=False).replace("</", "<\\/")),
                      encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
