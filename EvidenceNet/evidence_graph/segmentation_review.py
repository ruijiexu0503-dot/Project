from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl


def clean(value: object, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def page_number(page_id: str) -> int | None:
    digits = "".join(c for c in str(page_id) if c.isdigit())
    return int(digits) if digits else None


def load_document(directory: Path) -> dict:
    nodes = sorted(read_jsonl(directory / "evidence_nodes.jsonl"), key=lambda n: n["document_order"])
    # Content-unit boundaries are soft hierarchy metadata. Never replace them with
    # document-level single/multi classification results.
    assignment_path = directory / "hybrid_content_unit_assignments.jsonl"
    assignments = {r["node_id"]: r["content_unit_id"] for r in read_jsonl(assignment_path)}
    edges = read_jsonl(directory / "hybrid_content_unit_edges.jsonl")
    checkpoints = read_jsonl(directory / "hybrid_boundary_checkpoint.jsonl")
    node_by_id = {n["node_id"]: n for n in nodes}
    accepted = {
        e["target"]: e for e in edges
        if e.get("edge_type") == "STARTS_NEW_CONTENT_UNIT" and float(e.get("confidence", 0)) >= .8
    }
    unresolved = [r for r in checkpoints if r.get("decision") == "UNRESOLVED"]
    units: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        units[assignments.get(node["node_id"], "UNASSIGNED")].append(node)

    rendered = []
    for unit_id, members in units.items():
        pages = sorted({p for n in members for p in n.get("page_ids", [])}, key=lambda p: page_number(p) or 0)
        boundary = accepted.get(members[0]["node_id"])
        first = members[:3]
        last = members[-3:] if len(members) > 3 else []
        types = sorted({n.get("evidence_type", "text") for n in members})
        warnings = []
        if len(members) <= 2:
            warnings.append("tiny unit")
        if len(members) >= 80:
            warnings.append("large unit—possible missed boundary")
        if boundary and float(boundary.get("confidence", 0)) < .9:
            warnings.append("review boundary confidence")
        if members[0].get("plain_text", "").lower().startswith(("this ", "these ", "those ", "they ", "their ", "such ")):
            warnings.append("anaphoric start—possible false split")
        rendered.append({
            "id": unit_id, "nodes": len(members), "pages": pages, "types": types,
            "kind": (boundary or {}).get("right_unit_kind") or ("front_matter" if unit_id == "UNIT_0001" else "unknown"),
            "boundary": boundary, "warnings": warnings, "first": first, "last": last,
        })
    return {"id": directory.name, "node_count": len(nodes), "units": rendered, "unresolved": unresolved,
            "assignment_source": assignment_path.name}


def node_row(node: dict) -> str:
    pages = ", ".join(node.get("page_ids", [])) or "no page"
    return (f"<div class='node'><span class='node-id'>{html.escape(node['node_id'].rsplit('_EV_', 1)[-1])}</span>"
            f"<span class='page'>{html.escape(pages)}</span><span>{html.escape(clean(node.get('plain_text')))}</span></div>")


def render(documents: list[dict], target: Path) -> None:
    nav = []
    sections = []
    total_units = sum(len(d["units"]) for d in documents)
    total_unresolved = sum(len(d["unresolved"]) for d in documents)
    for d_idx, doc in enumerate(documents):
        doc_anchor = f"doc-{d_idx}"
        nav.append(f"<button data-target='{doc_anchor}'>{html.escape(doc['id'])}<small>{len(doc['units'])} units</small></button>")
        cards = []
        for unit in doc["units"]:
            b = unit["boundary"] or {}
            warning_html = "".join(f"<span class='warning'>{html.escape(w)}</span>" for w in unit["warnings"])
            boundary_html = "<p class='muted'>Document start; no preceding boundary.</p>"
            if b:
                sig = b.get("embedding_signals", {})
                boundary_html = (f"<div class='boundary'><b>Boundary confidence {float(b.get('confidence', 0)):.2f}</b>"
                    f" · similarity {float(sig.get('cross_similarity', 0)):.3f} · prominence {float(sig.get('prominence', 0)):.3f}"
                    f"<p>{html.escape(clean(b.get('rationale'), 700))}</p>"
                    f"<p><i>Left:</i> {html.escape(clean(b.get('supporting_span_left')))}<br>"
                    f"<i>Right:</i> {html.escape(clean(b.get('supporting_span_right')))}</p></div>")
            rows = "".join(node_row(n) for n in unit["first"])
            if unit["last"]:
                rows += "<div class='ellipsis'>⋯</div>" + "".join(node_row(n) for n in unit["last"])
            page_label = f"{unit['pages'][0]}–{unit['pages'][-1]}" if unit["pages"] else "pages unknown"
            cards.append(f"<article class='unit' data-warning='{bool(unit['warnings'])}' data-kind='{html.escape(unit['kind'])}'>"
                f"<header><div><h3>{unit['id']} <span>{html.escape(unit['kind'])}</span></h3>"
                f"<p>{unit['nodes']} Evidence nodes · {html.escape(page_label)} · {html.escape(', '.join(unit['types']))}</p></div>"
                f"<div>{warning_html}</div></header>{boundary_html}<details open><summary>Boundary context</summary>{rows}</details></article>")
        unresolved = ""
        if doc["unresolved"]:
            unresolved = f"<div class='unresolved'><b>{len(doc['unresolved'])} unresolved candidate(s)</b>: " + ", ".join(
                f"index {r.get('boundary_index')} ({html.escape(clean(r.get('error'), 100))})" for r in doc["unresolved"]) + "</div>"
        sections.append(f"<section id='{doc_anchor}' class='document'><h2>{html.escape(doc['id'])}</h2>"
            f"<p class='doc-meta'>{doc['node_count']} Evidence nodes · {len(doc['units'])} soft content units · source: {html.escape(doc['assignment_source'])}</p>{unresolved}{''.join(cards)}</section>")

    payload = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>EvidenceNet content-unit review</title><style>
:root{{--bg:#09101f;--panel:#101a2d;--line:#304263;--text:#eef3ff;--muted:#9facc6;--accent:#54c8e8;--warn:#ffb454}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}}
aside{{position:fixed;inset:0 auto 0 0;width:310px;padding:22px;background:#0d1628;border-right:1px solid var(--line);overflow:auto}}
aside h1{{font-size:21px;margin:0 0 8px}}aside p{{color:var(--muted)}}nav button{{display:block;width:100%;text-align:left;border:0;border-radius:8px;padding:10px;margin:4px 0;background:transparent;color:var(--text);cursor:pointer}}
nav button:hover{{background:#17243b}}nav small{{display:block;color:var(--muted)}}main{{margin-left:310px;max-width:1200px;padding:30px 42px 80px}}
.toolbar{{position:sticky;top:0;z-index:2;background:rgba(9,16,31,.94);padding:12px 0;border-bottom:1px solid var(--line)}}label{{margin-right:20px}}h2{{font-size:27px;margin:45px 0 0}}.doc-meta,.muted{{color:var(--muted)}}
.unit{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin:18px 0}}.unit header{{display:flex;justify-content:space-between;gap:15px}}h3{{margin:0;font-size:20px}}h3 span{{font-size:12px;text-transform:uppercase;background:#20304d;color:var(--accent);padding:4px 7px;border-radius:9px}}header p{{margin:4px 0;color:var(--muted)}}
.warning{{display:inline-block;background:#553b19;color:#ffd9a0;padding:4px 8px;border-radius:8px;margin:2px;font-size:12px}}.boundary{{border-left:3px solid var(--accent);padding:8px 14px;margin:14px 0;background:#0c1526}}.boundary p{{margin:6px 0;color:#c9d3e8}}
details{{margin-top:10px}}summary{{cursor:pointer;color:var(--accent)}}.node{{display:grid;grid-template-columns:70px 110px 1fr;gap:10px;border-top:1px solid #243554;padding:9px 0}}.node-id{{font-family:monospace;color:var(--accent)}}.page{{color:var(--muted)}}.ellipsis{{text-align:center;color:var(--muted);font-size:24px}}.unresolved{{border:1px solid #8f5427;background:#382513;padding:12px;border-radius:9px;margin:14px 0}}
@media(max-width:800px){{aside{{position:static;width:auto}}main{{margin:0;padding:20px}}.node{{grid-template-columns:55px 1fr}}.node span:last-child{{grid-column:1/-1}}}}
</style></head><body><aside><h1>Content-unit review</h1><p>{len(documents)} documents · {total_units} units · {total_unresolved} unresolved</p><nav>{''.join(nav)}</nav></aside>
<main><div class='toolbar'><label><input id='warnings' type='checkbox'> show warnings only</label><label>Unit kind <select id='kind'><option value=''>all</option><option>editorial</option><option>front_matter</option><option>back_matter</option><option>other</option><option>unknown</option></select></label></div>{''.join(sections)}</main>
<script>document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>document.getElementById(b.dataset.target).scrollIntoView());
function filter(){{let w=document.getElementById('warnings').checked,k=document.getElementById('kind').value;document.querySelectorAll('.unit').forEach(x=>x.hidden=(w&&x.dataset.warning!=='true')||(k&&x.dataset.kind!==k));}}
document.getElementById('warnings').onchange=filter;document.getElementById('kind').onchange=filter;</script></body></html>"""
    target.write_text(payload, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    root = Path(config["output"]["graph_root"])
    directories = sorted({p.parent for p in root.glob("*/hybrid_content_unit_assignments.jsonl")})
    documents = [load_document(p) for p in directories]
    target = Path(args.output) if args.output else root / "content_unit_review.html"
    render(documents, target)
    print(json.dumps({"output": str(target), "documents": len(documents),
                      "units": sum(len(d["units"]) for d in documents),
                      "unresolved": sum(len(d["unresolved"]) for d in documents)}))


if __name__ == "__main__":
    main()
