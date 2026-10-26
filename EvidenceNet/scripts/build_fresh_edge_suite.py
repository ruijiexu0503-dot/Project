#!/usr/bin/env python3
"""Build/freeze a source-reviewed node-disjoint challenge set without tuning prompts."""
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re

from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
import run_routed_edge_context as routed
import run_relatedness_pilot as broad
import run_all_node_multimodal_relatedness as multimodal
from fresh_edge_specs_20261021 import SPECS, node

SUITE = ROOT / 'data/benchmarks/evidence_edges_fresh_v1_20261021'
OUT = ROOT / 'EvidenceNet/output/routed_edge_context_fresh_v1_20261021'
OLD = [routed.prior.SOURCE / 'inputs.jsonl',
       ROOT / 'data/benchmarks/evidence_edges_v1_20261014/cases.jsonl',
       ROOT / 'data/benchmarks/text_multimodal_edges_v2_20261015/cases.jsonl',
       ROOT / 'data/benchmarks/evidence_edges_relatedness_v2_20261018/six_cases.jsonl']

def node_ids(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith('node_id') and isinstance(item, str):
                yield item
            else:
                yield from node_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from node_ids(item)

def norm(text):
    return re.sub(r'\s+', '', text).casefold()

def prepare():
    if SUITE.exists():
        raise ValueError('Require fresh suite directory; never overwrite labels after inspection/inference')
    nodes = {n['id']: n for n in rows(routed.prior.CORPUS / 'corpus_nodes.jsonl')}
    policies = read(routed.prior.CORPUS / 'corpus_policies.json')
    old_ids = {i for p in OLD for row in rows(p) for i in node_ids(row)}
    chosen = {node(s) for spec in SPECS for s in spec[:2]}
    assert not chosen & old_ids, sorted(chosen & old_ids)
    old_quotes = {norm(m.get('text','')) for i in old_ids if i in nodes for m in nodes[i]['members']
                  if m['kind'] == 'atom' and len(norm(m.get('text',''))) >= 80}
    duplicate_text = [i for i in chosen for m in nodes[i]['members']
                      if m['kind'] == 'atom' and norm(m.get('text','')) in old_quotes]
    assert not duplicate_text, duplicate_text
    formula_nodes = {b['formula']['node_id'] for b in rows(routed.prior.FORMULAS)}
    entries, cases, refs, pairs = [], [], [], set()
    for index, (a, b, label, title, reason) in enumerate(SPECS, 1):
        ids = [node(a), node(b)]
        pair = tuple(sorted(ids))
        assert pair not in pairs
        pairs.add(pair)
        assert nodes[ids[0]]['document'] != nodes[ids[1]]['document']
        # Label-independent ordering and opaque IDs. Do not send F-case labels to model.
        ids.sort(key=lambda s: hashlib.sha256(s.encode()).hexdigest())
        task = {'task_id': broad.task_id(pair)}
        entry = {'task': task, 'images': [], 'lookups': {}}
        endpoints = {}
        for side, nid in zip(('A','B'), ids):
            n = copy.deepcopy(nodes[nid])
            n['eligible_members'] = policies[nid]['members']
            task[side], entry['lookups'][side] = broad.catalog(n, side, SUITE, entry['images'])
            assert entry['lookups'][side]
            crop = multimodal.node_crop(n, SUITE)
            assert crop is not None
            entry['images'].append(str(crop))
            task[side]['node_source_image_number'] = len(entry['images'])
            anchors = list(entry['lookups'][side].values())
            original = [x for x in anchors if x['kind'] in {'ORIGINAL_TEXT','ORIGINAL_TABLE_ROW'}]
            assert original, 'Need original text/caption anchors, not generated image descriptions alone'
            endpoints[side] = {'node_id': nid, 'document': n['document'], 'page': n['page'],
                 'article_id': n.get('article_id'), 'modality': routed.modality(n, formula_nodes),
                 'original_anchors': original, 'source_crop': str(crop.relative_to(SUITE)),
                 'source_page': str(multimodal.page_path(n)), 'source_page_sha256': sha(multimodal.page_path(n))}
        fid = f'F{index:03d}'
        decisions = {'E':['EVIDENCE_LINK'], 'N':['NAVIGATION_LINK'], 'X':['NO_LINK'],
                     'U':['NO_LINK','NAVIGATION_LINK','EVIDENCE_LINK','UNCERTAIN']}[label]
        ref = {'task_id':task['task_id'], 'suite_case_id':fid, 'allowed_levels':
               [2,3] if label in 'EN' else [0,1] if label == 'X' else [0,1,2,3],
               'cutoff_evaluable':label != 'U', 'allowed_decisions':decisions,
               'decision_evaluable':label != 'U', 'annotation_label':label}
        cases.append({**ref, 'title':title, 'rationale':reason, **endpoints,
              'direction':'UNDIRECTED', 'split':'fresh_node_disjoint_challenge',
              'reviewer':'assistant_source_review_provisional_not_independent_expert',
              'confidence':'boundary' if label == 'U' else 'provisional',
              'review_basis':'original_text_caption_table_and_source_crop; no fresh predictions'})
        refs.append(ref)
        entries.append(entry)
    jsonl(SUITE / 'inputs.jsonl', entries)
    jsonl(SUITE / 'cases.jsonl', cases)
    jsonl(SUITE / 'evaluation/reference.jsonl', refs)
    jsonl(SUITE / 'nodes.jsonl', [nodes[i] for i in sorted(chosen)])
    old_contexts = set()
    previous = ROOT / 'migration/horeka-edge-context-20261020/results/multimodal_context/inputs.jsonl'
    if previous.exists():
        for e in rows(previous):
            old_contexts.update(node_ids(e.get('contexts', {})))
    audit = {'pairs':len(cases), 'unique_nodes':len(chosen), 'labels':dict(Counter(c['annotation_label'] for c in cases)),
             'modalities':dict(Counter('visual_table' if any(c[s]['modality']=='visual_table' for s in ('A','B')) else
                         'formula' if any(c[s]['modality']=='formula' for s in ('A','B')) else 'prose' for c in cases)),
             'old_endpoint_overlap': sorted(chosen & old_ids), 'normalized_original_text_duplicates':duplicate_text,
             'old_supplemental_context_overlap':sorted(chosen & old_contexts),
             'old_document_overlap':sorted({nodes[i]['document'] for i in chosen} & {nodes[i]['document'] for i in old_ids if i in nodes}),
             'exclusion_sources':{str(p.relative_to(ROOT)):sha(p) for p in OLD},
             'scope':'All cross-document; endpoint-node-disjoint from listed prior evaluated sets, NOT document-disjoint. Shared context reported, not hidden. Matched endpoint reuse makes cases correlated. Purposive challenge set, not random prevalence sample.'}
    write(SUITE / 'overlap_audit.json', audit)
    render(cases, audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))

def render(cases, audit):
    esc = html.escape
    cards = []
    for c in cases:
        panels = []
        for s in ('A','B'):
            e = c[s]
            raw = '\n\n'.join(a['quote'] for a in e['original_anchors'])
            page = os.path.relpath(e['source_page'], SUITE)
            panels.append(f'<section><h3>{s} · {esc(e["modality"])}</h3><small>{esc(e["node_id"])}</small>'
                f'<p><a href="{esc(page)}">打开完整原页</a></p><img loading="lazy" src="{esc(e["source_crop"])}">'
                f'<details><summary>原始文字/图注/表格（未清洗）</summary><pre>{esc(raw)}</pre></details></section>')
        cards.append(f'<article data-label="{c["annotation_label"]}"><h2>{c["suite_case_id"]} · {esc(c["title"])} · {c["annotation_label"]}</h2>'
           f'<p>{esc(c["rationale"])}</p><div class="pair">{"".join(panels)}</div></article>')
    (SUITE / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Fresh edge review · 20261021</title>'
       '<style>body{max-width:1500px;margin:auto;padding:24px;font-family:system-ui;background:#f4f6f8}article{background:white;margin:24px 0;padding:20px;border-radius:12px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}img{max-width:100%;max-height:650px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{overflow-wrap:anywhere}button{margin:4px;padding:10px}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>'
       '<h1>新样本 · 40 对 · 初步标注复核</h1><p>E 证据对应；N 仅导航；X 不连接；U 边界待复核（不计分）。所有关系无方向要求。</p>'
       '<p>模型预测前依据原文标注，非独立专家金标准。与旧集端点不重叠，但文档可能重叠；复用端点的配对并非独立样本。</p>'
       + ''.join(f'<button onclick="document.querySelectorAll(\'article\').forEach(e=>e.hidden=\'{x}\'!==\'ALL\'&&e.dataset.label!==\'{x}\')">{x}</button>' for x in ['ALL','E','N','X','U'])
       + f'<details><summary>重叠审计</summary><pre>{esc(json.dumps(audit,ensure_ascii=False,indent=2))}</pre></details>' + ''.join(cards))

def freeze():
    if (SUITE / 'manifest.json').exists() or OUT.exists():
        raise ValueError('Already frozen/prepared; never silently refreeze')
    cases = rows(SUITE / 'cases.jsonl')
    assert len(cases) == 40
    # Final source-image review may clarify rationale before (never after) freezing.
    for c, spec in zip(cases, SPECS):
        assert {c[s]['node_id'] for s in ('A','B')} == {node(s) for s in spec[:2]}
        assert c['annotation_label'] == spec[2]
        c['title'], c['rationale'] = spec[3:]
    jsonl(SUITE / 'cases.jsonl', cases)
    render(cases, read(SUITE / 'overlap_audit.json'))
    write(SUITE / 'protocol.json', {'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'annotation_status':'provisional assistant annotations reviewed before fresh predictions; user review pending',
        'selection':'purposive source-reviewed challenge pairs; 4 boundary cases excluded; not random sample',
        'evaluation':'Report broad relatedness AND strict allowed_decisions; no prompt tuning on this set; no retrieval recall claim',
        'source_review':'original text/captions/tables plus visual inspection of multimodal/formula source crops',
        'code':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),Path(__file__).with_name('fresh_edge_specs_20261021.py')]}})
    write(SUITE / 'manifest.json', {'files':{str(p.relative_to(SUITE)):sha(p) for p in sorted(SUITE.rglob('*')) if p.is_file()}})
    original_source = routed.prior.SOURCE
    try:
        routed.prior.SOURCE = SUITE
        routed.prepare(OUT)
    finally:
        routed.prior.SOURCE = original_source
    protocol = read(OUT / 'protocol.json')
    protocol.update(experiment='routed_edge_context_fresh_v1',
        evaluation='Fresh endpoint-node-disjoint provisional challenge labels; 4 boundary cases excluded. Not document-held-out; not retrieval evaluation.',
        annotation_manifest_sha256=sha(SUITE/'manifest.json'),
        strict_decision_reference='reference.jsonl: allowed_decisions; NAVIGATION must not count as evidence promotion')
    write(OUT / 'protocol.json', protocol)
    routed.freeze(OUT)
    routed.verify(OUT, routed.gate.MODEL)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare','freeze'])
    args = parser.parse_args()
    prepare() if args.stage == 'prepare' else freeze()
