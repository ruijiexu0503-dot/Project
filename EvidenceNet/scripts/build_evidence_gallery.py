#!/usr/bin/env python3
"""Render EvidenceUnits as source-object cards, never as page bounding boxes."""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any

COLORS = ["#c62848", "#0077a8", "#14866d", "#c47d00", "#a34c86", "#4f5d9b", "#a34f22"]


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def uri(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists() or path.stat().st_size > 12_000_000:
        return None
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    page = Path(args.page_dir); rep = read(page / "input_representation.json")
    nodes = jsonl(page / "evidence_nodes.jsonl")
    assembly = read(page / "assembly.json")
    fragments = {fragment["fragment_id"]: fragment for atom in rep["atoms"] for fragment in atom.get("text_fragments", [])}
    visuals = {visual["visual_bundle_id"]: visual for visual in rep["visual_bundles"]}
    presentation_path = page / 'visual_presentations.json'
    presentations = {v['panel_id']: v for v in read(presentation_path)} if presentation_path.exists() else None
    structural = [entry for item in read(page / "flow.json").get("content_items", []) for entry in item.get("structural_fragments", [])]
    relations = assembly.get("relations", [])
    cards = []
    for index, node in enumerate(nodes):
        color = COLORS[index % len(COLORS)]
        fragments_html = "".join(
            f"<article class='fragment'><code>{html.escape(fragment_id)}</code><p>{html.escape(fragments[fragment_id]['text'])}</p></article>"
            for fragment_id in node.get("source_fragment_ids", []) if fragment_id in fragments
        ) or "<p class='empty'>No text fragments.</p>"
        visual_html = []
        for visual_id in node.get("source_visual_panel_ids", []):
            if presentations is not None:
                presentation = presentations.get(visual_id, {})
                image = uri(presentation.get('image'))
                if image:
                    visual_html.append(f"<figure style='max-width:100%'><img src='{image}'><figcaption>{html.escape(visual_id)} · {html.escape(presentation.get('mode', 'presentation'))}</figcaption></figure>")
                else:
                    visual_html.append(f"<p>Visual presentation needs review: {html.escape(visual_id)}</p>")
                continue
            visual = visuals.get(visual_id, {})
            components = visual.get("native_components", [])
            if not components:
                visual_html.append(f"<p class='empty'>No recovered native component for {html.escape(visual_id)}.</p>")
            for component in components:
                source = uri(component.get("source_object_path")); visible = uri(component.get("visible_mask_path"))
                images = "".join(f"<figure><img src='{src}'><figcaption>{label}</figcaption></figure>"
                                 for label, src in (("Recovered PDF object", source), ("Visible support", visible)) if src)
                visual_html.append(f"<article class='component'><code>{html.escape(component.get('member_id', 'unknown'))}</code><div class='media'>{images}</div></article>")
        related = [row for row in relations if node["node_id"].endswith("_" + str(row.get("source_id", ""))) or node["node_id"].endswith("_" + str(row.get("target_id", "")))]
        relation_html = "".join(f"<li>{html.escape(row.get('relation_type', ''))}: <code>{html.escape(row.get('source_id', ''))}</code> -> <code>{html.escape(row.get('target_id', ''))}</code></li>" for row in related)
        review_html = ''
        if node.get('status'):
            review_html = '<p><strong>' + html.escape(node['status']) + '</strong> · Text: ' + html.escape(node.get('text_quality', 'UNVERIFIED')) + '</p>'
            review_html += '<p>' + html.escape(node.get('association_basis', '')) + '</p>'
            review_html += ''.join('<p><code>' + html.escape(link['visual_id']) + '</code>: ' + html.escape(link['anchor']) + '</p>' for link in node.get('visual_text_links', []))
            review_html += ''.join('<p><strong>Pending geometry association</strong>: ' + html.escape(link['visual_id']) + ' / ' + html.escape(link['text_unit_id']) + ' (not merged)</p>' for link in node.get('pending_associations', []))
        fragments_html = review_html + fragments_html
        cards.append(f"<section class='card' style='--accent:{color}'><header><span class='dot'></span><div><h2>{html.escape(node['node_id'].rsplit('_', 1)[-1])}</h2><p>{html.escape(str(node.get('unit_type')))} · {html.escape(str(node.get('flow_id')))}</p></div></header><div class='text'>{fragments_html}</div><div class='visual'>{''.join(visual_html)}</div>{'<ul class=relations>' + relation_html + '</ul>' if relation_html else ''}</section>")
    structural_html = "".join(f"<li><code>{html.escape(row['fragment_id'])}</code> · {html.escape(row.get('role', ''))} · {html.escape(fragments.get(row['fragment_id'], {}).get('text', ''))}</li>" for row in structural)
    document = f"""<!doctype html><meta charset='utf-8'><title>Evidence gallery</title>
<style>body{{font:15px system-ui;margin:0;background:#eef1f4;color:#16212d}}main{{max-width:1280px;margin:auto;padding:28px}}h1,h2,p{{margin:0}}.intro{{margin:8px 0 24px;color:#52616f}}.structural{{background:#fff;border-left:4px solid #7d8791;padding:14px 18px;margin-bottom:20px}}.structural ul{{margin:8px 0 0;padding-left:20px}}.card{{background:#fff;border-left:6px solid var(--accent);margin:14px 0;padding:18px}}.card header{{display:flex;gap:10px;align-items:center;margin-bottom:14px}}.dot{{width:14px;height:14px;background:var(--accent);display:block;flex:none}}h2{{font-size:18px}}header p,.empty{{font-size:13px;color:#687786}}.fragment{{border-top:1px solid #dbe1e6;padding:12px 0}}.fragment p{{white-space:pre-wrap;line-height:1.45;margin-top:6px}}.component{{border-top:1px solid #dbe1e6;padding-top:12px;margin-top:12px}}.media{{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px}}figure{{margin:0;max-width:48%}}figure img{{max-width:100%;max-height:480px;object-fit:contain;background:#f4f6f8}}figcaption{{font-size:12px;color:#687786}}.relations{{font-size:13px;color:#52616f;padding-left:18px}}code{{overflow-wrap:anywhere}}</style>
<main><h1>Evidence gallery: {html.escape(rep['document_id'])} {html.escape(rep['page'])}</h1><p class='intro'>Every card is source membership, not a page rectangle. Text cards contain exact recovered fragments. Visual cards contain recovered PDF-native objects and their visible support.</p><section class='structural'><strong>Structural context, intentionally not EvidenceUnit</strong><ul>{structural_html}</ul></section>{''.join(cards)}</main>"""
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(document, encoding="utf-8")


if __name__ == "__main__": main()
