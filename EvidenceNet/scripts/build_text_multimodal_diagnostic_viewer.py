#!/usr/bin/env python3
"""Standalone full-node case browser, retaining provisional labels and source-scope reviews."""
import argparse
import base64
import hashlib
import json
import mimetypes
from pathlib import Path

from run_text_multimodal_diagnostic_v2 import DATA,OUT
from run_node_context_edges import read,rows


def build(data,out):
    nodes={n['id']:n for n in rows(data/'nodes.jsonl')}
    cases=rows(data/'cases.jsonl');entries=rows(data/'inputs.jsonl')
    assets={};node_assets={}
    for e in entries:
        for look in e['lookups'].values():
            for a in look.values():
                if not a.get('crop'):continue
                p=Path(a['crop']);digest=hashlib.sha256(p.read_bytes()).hexdigest()
                if digest!=a['crop_sha256']:raise ValueError('Changed crop')
                node_assets.setdefault(a['node_id'],{})[a['member_id']]=digest
                if digest not in assets:assets[digest]='data:'+mimetypes.guess_type(p)[0]+';base64,'+base64.b64encode(p.read_bytes()).decode()
    predictions={p['task_id']:p for p in rows(out/'predictions.jsonl')} if (out/'predictions.jsonl').exists() else {}
    scope=read(data/'reference_scope_review.json') if (data/'reference_scope_review.json').exists() else []
    reviews=read(out/'source_review.json') if (out/'source_review.json').exists() else []
    payload=dict(nodes=nodes,cases=cases,predictions=predictions,node_assets=node_assets,assets=assets,
        scope={r['case_id']:r for r in scope},reviews={r['case_id']:r for r in reviews},
        summary=read(out/'summary.json') if (out/'summary.json').exists() else None)
    template=Path(__file__).with_name('text_multimodal_diagnostic_viewer.html').read_text()
    target=out/'viewer/index.html';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(template.replace('/*__DATA__*/null',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')))
    print(json.dumps(dict(html=str(target.resolve()),cases=len(cases),predictions=len(predictions),images=len(assets))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=DATA);p.add_argument('--output',type=Path,default=OUT)
    a=p.parse_args();build(a.data,a.output)
