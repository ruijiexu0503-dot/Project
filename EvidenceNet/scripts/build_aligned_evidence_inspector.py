#!/usr/bin/env python3
"""Create a source-page evidence inspector for an aligned graph shadow run."""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", required=True, type=Path)
    parser.add_argument("--page", required=True)
    parser.add_argument("--asset-root", type=Path, help="Root that resolves Markdown figure paths")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    nodes = [json.loads(line) for line in args.nodes.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [node for node in nodes if args.page in node.get("page_ids", [])]
    cards = []
    for index, node in enumerate(selected, start=1):
        members = node.get("source_members", [])
        provenance = "<br>".join(
            html.escape(f"{member.get('block_id')} | {member.get('bbox_source')} | {member.get('matched_region_label') or 'no layout match'}")
            for member in members
        )
        markdown = node.get("original_markdown", "")
        match = re.search(r"!\[[^]]*\]\(([^)]+)\)", markdown)
        component = f"<pre>{html.escape(node.get('plain_text', ''))}</pre>"
        if match and args.asset_root:
            asset = args.asset_root / match.group(1)
            if asset.exists():
                mime = "image/jpeg" if asset.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
                uri = f"data:{mime};base64," + base64.b64encode(asset.read_bytes()).decode("ascii")
                component = f"<figure><img src='{uri}' alt='Recovered evidence image'><figcaption>Recovered visual component</figcaption></figure>"
            else:
                component = "<p class='missing'>Image component unavailable.</p>"
        cards.append(
            f"<article class='node'><header><b>Evidence {index}</b><span>{html.escape(node.get('evidence_type', ''))}</span></header>"
            f"<div class='component'>{component}</div><small>{provenance}</small></article>"
        )
    document = f"""<!doctype html><meta charset='utf-8'><title>Evidence inspector {html.escape(args.page)}</title>
<style>body{{font:15px system-ui;margin:0;background:#f3f5f6;color:#17212b}}main{{max-width:1100px;margin:auto;padding:24px}}h1{{font-size:22px;margin:0 0 16px}}.node{{background:#fff;border-left:5px solid #0077a8;margin:14px 0;padding:14px 16px}}header{{display:flex;justify-content:space-between;gap:12px}}header span,small,figcaption{{color:#5b6873}}.component{{margin:12px 0}}pre{{margin:0;white-space:pre-wrap;font:15px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}}figure{{margin:0}}figure img{{display:block;max-width:100%;max-height:620px;object-fit:contain;background:#f8f9fa}}figcaption{{font-size:12px;margin-top:5px}}small{{font-family:ui-monospace,monospace;overflow-wrap:anywhere}}.missing{{color:#9a4d00}}</style>
<main><h1>{html.escape(args.page)}: evidence components</h1><section>{''.join(cards)}</section></main>"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
