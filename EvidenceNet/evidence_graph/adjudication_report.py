from __future__ import annotations

import argparse, html, json
from pathlib import Path
from .config import load_config
from .io_utils import read_json, read_jsonl


def build(doc_id, config):
    root=Path(config["output"]["graph_root"])/doc_id
    nodes={n["node_id"]:n for n in read_jsonl(root/"evidence_nodes.jsonl")}
    audits=read_jsonl(root/"semantic_edge_adjudications.jsonl")
    stats=read_json(root/"adjudication_statistics.json")
    cards=[]
    for i,a in enumerate(audits,1):
        e=a["proposed_edge"]; s=nodes[e["source"]]; t=nodes[e["target"]]
        failed=[k for k,v in a["checks"].items() if not v]
        verdict=a.get("verdict","REJECT"); status_class="accept" if verdict=="ACCEPT" else "reject"
        cards.append(f'''<details><summary><b>{i}. {html.escape(e['edge_type'])}</b> · {e['source'].split('_')[-1]} → {e['target'].split('_')[-1]} · proposed {e['confidence']:.2f} · audit {a['confidence']:.2f} · <span class="{status_class}">{verdict}</span></summary>
<div class="grid"><section><h3>Source: {html.escape(e['source'])}</h3><p>{html.escape(s.get('base_summary') or '')}</p><blockquote>{html.escape(e.get('source_supporting_span',''))}</blockquote><div class="text">{html.escape(s['original_markdown'])}</div></section>
<section><h3>Target: {html.escape(e['target'])}</h3><p>{html.escape(t.get('base_summary') or '')}</p><blockquote>{html.escape(e.get('target_supporting_span',''))}</blockquote><div class="text">{html.escape(t['original_markdown'])}</div></section></div>
<h3>Initial rationale</h3><p>{html.escape(e.get('rationale',''))}</p><h3>Adversarial rationale</h3><p>{html.escape(a.get('rationale',''))}</p>
<p><b>Failure modes:</b> {html.escape('; '.join(map(str,a.get('failure_modes',[]))) or 'none supplied')}</p><p><b>Failed automatic checks:</b> {html.escape(', '.join(failed))}</p></details>''')
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>EvidenceNet adjudication review</title><style>
body{{margin:0 auto;max-width:1400px;padding:28px;background:#0b1020;color:#e9eef9;font:14px/1.5 system-ui}}h1{{margin-bottom:4px}}.meta{{color:#9aabc7;margin-bottom:24px}}details{{background:#121a2d;border:1px solid #31405f;border-radius:8px;margin:10px 0;padding:12px}}summary{{cursor:pointer;font-size:15px}}.reject{{color:#ff7b88}}.accept{{color:#57d38c}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}section{{background:#0d1527;padding:12px;border-radius:7px}}h3{{font-size:13px;color:#69cce0}}blockquote{{border-left:3px solid #ffb454;margin:10px 0;padding:8px;background:#49351f}}.text{{white-space:pre-wrap;max-height:260px;overflow:auto;color:#cbd6e8}}@media(max-width:850px){{.grid{{grid-template-columns:1fr}}}}</style></head><body>
<h1>EvidenceNet adversarial adjudication</h1><div class="meta">{stats['proposed']} proposed · {stats['accepted']} accepted · {stats['rejected']} rejected · {stats['malformed']} malformed · threshold {stats['acceptance_threshold']}</div>{''.join(cards)}</body></html>'''
    target=root/"semantic_adjudication_review.html";target.write_text(page,encoding="utf-8");return target


def main():
    p=argparse.ArgumentParser();p.add_argument("--doc-id",required=True);p.add_argument("--config",required=True);a=p.parse_args()
    print(build(a.doc_id,load_config(a.config)))
if __name__=="__main__":main()
