"""HTML and page overlays for the reconstruction PoC."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json


def _boxes(node):
    members = node.get("source_members", []) or node.get("bbox_members", [])
    return [m.get("bbox") for m in members if isinstance(m.get("bbox"), list) and len(m["bbox"]) == 4]


def run(args):
    root = Path(args.graph_root) / args.doc_id; out = Path(args.output) / args.doc_id
    out.mkdir(parents=True, exist_ok=True)
    evidence_path = root / "evidence_nodes.jsonl"
    nodes = read_jsonl(evidence_path) if evidence_path.exists() else []
    ev_by_block = {}; ev_by_block_only = {}
    for ev in nodes:
        for member in ev.get("source_members", []):
            if member.get("block_id"):
                for page in ev.get("page_ids", []):
                    ev_by_block.setdefault((member["block_id"], page), []).append(ev["node_id"])
                ev_by_block_only.setdefault(member["block_id"], []).append(ev["node_id"])
    by_page = {}
    for node in nodes:
        for page in node.get("page_ids", []): by_page.setdefault(page, []).append(node)
    cards = []
    def lookup_ev(block_id, page):
        direct = ev_by_block.get((block_id, page), [])
        fallback = ev_by_block_only.get(block_id, [])
        return direct or (fallback if len(fallback) == 1 else [])
    from PIL import Image, ImageDraw
    for page_dir in sorted(p for p in out.glob("page_*") if p.is_dir()):
        page = page_dir.name; rep = json.loads((page_dir / "page_representation.json").read_text())
        result_path = page_dir / "qwen_parsed.json"; result = json.loads(result_path.read_text()) if result_path.exists() else None
        labels = {}; order = {}
        if result:
            for article in result.get("articles", []):
                aid = article.get("article_id", "A?")
                for number, node_id in enumerate(article.get("reading_order", []), 1): labels[node_id] = aid; order[node_id] = number
            for node_id in result.get("non_article_nodes", []): labels[node_id] = "NON_ARTICLE"
        image_path = rep.get("page_image"); overlay = out / f"{page}_reconstruction.png"
        if image_path and Path(image_path).exists():
            with Image.open(image_path).convert("RGB") as image:
                draw = ImageDraw.Draw(image)
                colors = {"NON_ARTICLE": (150, 150, 150)}
                for node in rep.get("nodes", []):
                    aid = labels.get(node["node_id"], "UNASSIGNED"); color = colors.get(aid)
                    if color is None:
                        color = colors.setdefault(aid, ((53 + 71 * len(colors)) % 230, (110 + 47 * len(colors)) % 230, (220 + 29 * len(colors)) % 230))
                    for bbox in _boxes(node):
                        box = tuple(int(round(x)) for x in bbox); draw.rectangle(box, outline=color, width=3)
                        ev_ids = lookup_ev(node["node_id"], page)
                        ev_tag = ev_ids[0].rsplit("_EV_", 1)[-1] if ev_ids else ("STRUCT" if node.get("node_type") == "heading" else "no-EV")
                        tag = f"EV{ev_tag} {aid}-{order[node['node_id']]}" if node["node_id"] in order else f"EV{ev_tag} {aid}"
                        draw.text((box[0] + 3, box[1] + 3), tag, fill=color)
                for visual in rep.get("visual_regions", []):
                    bbox = visual.get("bbox")
                    if not isinstance(bbox, list) or len(bbox) != 4: continue
                    aid = labels.get(visual["visual_node_id"], "UNASSIGNED"); color = colors.get(aid)
                    if color is None:
                        color = colors.setdefault(aid, ((53 + 71 * len(colors)) % 230, (110 + 47 * len(colors)) % 230, (220 + 29 * len(colors)) % 230))
                    box = tuple(int(round(x)) for x in bbox); draw.rectangle(box, outline=color, width=5)
                    tag = f"VIS {aid}-{order[visual['visual_node_id']]}" if visual["visual_node_id"] in order else f"VIS {aid}"
                    draw.text((box[0] + 3, box[1] + 3), tag, fill=color)
                image.save(overlay)
        page_rows = rep.get("nodes", [])
        def ev_for(row):
            vals = lookup_ev(row['node_id'], page)
            if vals: return ", ".join(vals)
            if row.get("node_type") == "heading": return "not generated (structural heading)"
            return "no EV mapping"
        rows = "".join(f"<tr><td>{html.escape(n['node_id'])}</td><td>{html.escape(ev_for(n))}</td><td>{html.escape(labels.get(n['node_id'], 'UNASSIGNED'))}</td><td>{order.get(n['node_id'], '')}</td><td>{html.escape((n.get('plain_text') or n.get('text') or '')[:180])}</td></tr>" for n in page_rows)
        rows += "".join(f"<tr><td>{html.escape(v['visual_node_id'])}</td><td>visual</td><td>{html.escape(labels.get(v['visual_node_id'], 'UNASSIGNED'))}</td><td>{order.get(v['visual_node_id'], '')}</td><td>{html.escape((v.get('content_summary') or v.get('visible_text') or '')[:180])}</td></tr>" for v in rep.get("visual_regions", []))
        validation_path = page_dir / "validation.json"
        validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
        status = "not run" if not result else f"{len(result.get('articles', []))} articles; valid={validation.get('valid', False)}"
        cards.append(f"<section><h2>{html.escape(page)} — {html.escape(status)}</h2><img src='{html.escape(overlay.name)}'><table><tr><th>split block</th><th>EvidenceNode</th><th>article</th><th>order</th><th>preview</th></tr>{rows}</table></section>")
    target = out / "reconstruction_report.html"
    target.write_text("<!doctype html><meta charset='utf-8'><title>Magazine reconstruction PoC</title><style>body{font:14px system-ui;background:#101827;color:#e8eefb;margin:24px}section{background:#18243a;padding:18px;margin:22px 0;border-radius:12px}img{max-width:760px;display:block;margin:10px 0}table{border-collapse:collapse;width:100%}td,th{border:1px solid #40516c;padding:5px;text-align:left}th{color:#79d7ed}</style>" + "".join(cards), encoding="utf-8")
    summary = {"doc_id": args.doc_id, "pages": len(cards), "html": str(target), "overlays": sorted(str(p) for p in out.glob("page_*_reconstruction.png")), "production_modified": False}
    write_json(out / "visualization_summary.json", summary); print(json.dumps(summary, indent=2))


def main():
    p = argparse.ArgumentParser(); p.add_argument("--doc-id", required=True); p.add_argument("--graph-root", default="EvidenceNet/output/evidence_graph"); p.add_argument("--output", default="EvidenceNet/output/magazine_article_reconstruction_poc"); run(p.parse_args())


if __name__ == "__main__": main()
