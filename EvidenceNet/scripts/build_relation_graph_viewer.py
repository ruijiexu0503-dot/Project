#!/usr/bin/env python3
"""Build a self-contained interactive graph for one relation-first page."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def preview(text, limit=180):
    return " ".join((text or "").split())[:limit]


def build(page_dir: Path, output: Path):
    components = read(page_dir / "components.json")
    units = read(page_dir / "review_units.json") if (page_dir / "review_units.json").exists() else read(page_dir / "text_units.json")
    relations = read(page_dir / "relations.json")
    by_unit = {u["text_unit_id"]: u for u in units}
    component_ids = {n["node_id"] for n in components}
    parent = {cid: cid for cid in component_ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        if a in parent and b in parent and find(a) != find(b): parent[find(b)] = find(a)
    raw_edges = []
    for edge in relations:
        source, target = edge.get("source_node_id"), edge.get("target_node_id")
        if source in component_ids and target in component_ids:
            union(source, target)
            raw_edges.append({"source": source, "target": target, "relation": edge.get("relation_type"),
                          "visual_id": edge.get("visual_id"), "text_unit_id": edge.get("text_unit_id"),
                          "anchor": edge.get("anchor"), "basis": edge.get("basis"),
                          "quality": edge.get("text_quality"), "scope": edge.get("candidate_scope"),
                          "spans": edge.get("source_spans", [])})
    groups = {}
    for component in components: groups.setdefault(find(component["node_id"]), []).append(component)
    nodes = []
    for index, members in enumerate(groups.values(), 1):
        text_members, visual_members, structural_members = [], [], []
        for member in members:
            if member["node_type"] == "visual_component":
                visual_members.extend(member.get("visual_ids", []))
            else:
                tid = next((u["text_unit_id"] for u in units if member["node_id"].endswith("_" + u["text_unit_id"])), None)
                item = by_unit.get(tid, {})
                row = {"id": tid or member["node_id"], "text": item.get("text", ""), "fragments": member.get("fragment_ids", []), "role": member.get("role")}
                (structural_members if member["node_type"] == "structural_component" else text_members).append(row)
        kind = "multimodal" if text_members and visual_members else "visual_only" if visual_members else "text_only"
        nodes.append({"id": f"EV_{index:03d}", "kind": kind, "label": f"EV_{index:03d}",
                      "x": 150 + ((index - 1) % 3) * 410, "y": 100 + ((index - 1) // 3) * 210,
                      "texts": text_members, "visuals": visual_members, "structural": structural_members,
                      "relations": [], "color": "#34d399" if kind == "multimodal" else "#f59e0b" if visual_members else "#38bdf8"})
    component_to_evidence = {}
    for node, members in zip(nodes, groups.values()):
        for member in members: component_to_evidence[member["node_id"]] = node["id"]
    edges = []
    for edge in raw_edges:
        edge["evidence_node_id"] = component_to_evidence[edge["source"]]
        nodes[int(edge["evidence_node_id"].split("_")[1]) - 1]["relations"].append(edge)
        edges.append(edge)
    data = {"page": str(page_dir), "nodes": nodes, "edges": edges, "node_unit": "evidence_node"}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = f'''<!doctype html><meta charset="utf-8"><title>Evidence node graph</title>
<style>body{{margin:0;background:#0b1220;color:#e5edf8;font:14px system-ui}}header{{padding:14px 20px;background:#111b2e}}#layout{{display:grid;grid-template-columns:minmax(650px,1fr) 410px;height:calc(100vh - 104px)}}#stage{{overflow:auto;background:#07101e}}svg{{width:100%;min-height:700px}}aside{{padding:16px;overflow:auto;background:#111827;border-left:1px solid #334155}}.node{{cursor:pointer}}.node:hover{{stroke:#fff;stroke-width:3}}.edge{{cursor:pointer;opacity:.9}}.edge:hover{{stroke:#fff;stroke-width:5}}.legend span{{margin-right:18px}}.dot{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px}}pre{{white-space:pre-wrap;word-break:break-word}}button{{margin-left:10px;background:#243451;color:#fff;border:1px solid #4b638c;padding:5px 9px;border-radius:4px;cursor:pointer}}</style>
<header><b>Evidence node graph</b> · {len(nodes)} evidence nodes · {len(edges)} internal relations <span class="legend"><span><i class="dot" style="background:#34d399"></i>text + image</span><span><i class="dot" style="background:#f59e0b"></i>image-only</span><span><i class="dot" style="background:#38bdf8"></i>text-only</span></span><button onclick="fit()">fit</button></header>
<div id="layout"><div id="stage"><svg id="svg" viewBox="0 0 1230 1000"><g id="world"></g></svg></div><aside id="panel"><h3>点击 evidence node</h3><p>每个圆点现在是一个 evidence node；文字和图片是该节点的成员，不再单独作为图节点。</p></aside></div>
<script>const D={payload},W=document.getElementById('world'),P=document.getElementById('panel');const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const NS='http://www.w3.org/2000/svg';function show(x){{P.innerHTML='<h3>'+esc(x.label)+'</h3><pre>'+esc(JSON.stringify(x,null,2))+'</pre>'}}function el(tag,attrs){{const x=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs||{{}}))x.setAttribute(k,v);return x}}function render(){{W.innerHTML='';for(const n of D.nodes){{const g=el('g',{{transform:`translate(${{n.x}} ${{n.y}})`,class:'node'}});g.onclick=()=>show(n);const h=Math.max(112,74+(n.relations||[]).length*22);g.append(el('rect',{{x:-180,y:-58,width:360,height:h,rx:10,fill:'#16233a',stroke:n.color,'stroke-width':3}}));const title=el('text',{{x:-162,y:-36,fill:n.color,'font-weight':'700'}});title.textContent=n.label+'  '+(n.kind==='multimodal'?'text + image':n.kind);g.append(title);const left=el('text',{{x:-162,y:-10,fill:'#bae6fd','font-size':12}});left.textContent='TEXT: '+((n.texts||[]).map(x=>x.id).join(', ')||'—');g.append(left);const right=el('text',{{x:12,y:-10,fill:'#fed7aa','font-size':12}});right.textContent='IMAGE: '+((n.visuals||[]).join(', ')||'—');g.append(right);for(const [i,e] of (n.relations||[]).entries()){{const y=14+i*22;const line=el('line',{{x1:-72,y1:y,x2:72,y2:y,stroke:e.relation==='CAPTION_FOR'?'#fbbf24':'#86efac','stroke-width':3,'stroke-dasharray':e.relation==='ILLUSTRATES'?'8 6':''}});line.onclick=(ev)=>{{ev.stopPropagation();show(e)}};g.append(line);const label=el('text',{{x:0,y:y-4,'text-anchor':'middle',fill:'#e5e7eb','font-size':11}});label.textContent=e.relation;label.onclick=(ev)=>{{ev.stopPropagation();show(e)}};g.append(label)}}W.append(g)}}}}function fit(){{document.getElementById('svg').setAttribute('viewBox','0 0 1230 '+Math.max(700,Math.max(...D.nodes.map(n=>n.y))+220))}}render();fit();</script>'''
    output.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build(args.page_dir, args.output or args.page_dir / "relation_graph.html")
    print(args.output or args.page_dir / "relation_graph.html")
