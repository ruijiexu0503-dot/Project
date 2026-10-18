#!/usr/bin/env python3
"""Qwen page clustering and grounded cross-page article identity for hybrid nodes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'EvidenceNet'))
from evidence_graph.hybrid_article_clustering import (
    stable_id, page_prompt, validate_membership, reading_prompt, validate_reading, continuation_prompt, validate_continuations,
)
from evidence_graph.llm_client import create_llm, extract_json
from run_hybrid_node_v2 import audit
import build_evidence_node_graph_viewer as viewer

MODEL = ROOT / 'external/models/Qwen3.5-35B-A3B'
METADATA = {'header', 'foot', 'footer', 'page_num', 'page_number', 'watermark', 'reference', 'catalogue'}


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n'); tmp.replace(path)


def jsonl(path, values):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values)); tmp.replace(path)


def prepare(args):
    out = args.output
    if (out / 'manifest.json').exists():
        check(out)
        return
    viewer.PREPARED = args.source.resolve()
    pages, inputs, fingerprints = [], [], {}
    expected = set(read(args.source / 'manifest.json')['tasks'])
    selected, seen = set(), set()
    for path in sorted(args.nodes.glob('batch_*/hybrid/**/evidence_nodes.jsonl')):
        task = str(path.parent).split('/hybrid/', 1)[1]
        if args.include_task and task not in args.include_task:
            continue
        rep_path = args.source / task / 'input_representation.json'
        rep = read(rep_path)
        if args.include_document and rep['document_id'] not in args.include_document:
            continue
        if task in seen:
            raise ValueError('Duplicate hybrid page; provide one audited node run: ' + task)
        seen.add(task)
        if task not in expected:
            raise ValueError('Unexpected node page: ' + task)
        hybrid_root = Path(str(path.parent).split('/hybrid/', 1)[0]) / 'hybrid'
        if not audit(task, args.source, hybrid_root)['valid'] or not read(path.parent / 'run_summary.json')['decision_valid']:
            raise ValueError('Incomplete hybrid nodes: ' + task)
        page = viewer.build_page(path, out)
        page.pop('segmentation', None); page.pop('candidate_edges', None)
        page['document_mode'] = 'single_article' if page['document'] in args.single_document else 'multi_article'
        page['page_number'] = int(str(page['page']).replace('page_', ''))
        # Existing-render labels can differ from physical PDF pages. Never infer NEXT from those alone.
        page['source_page_space'] = rep.get('source_manifest_row', {}).get('page_space', 'UNVERIFIED')
        page['page_id'] = stable_id('PAGE_', [page['document'], page['page'], task])
        public_nodes, excluded = [], []
        for n in page['nodes']:
            for key in ('article_id', 'article_unit_id', 'article_mapping_status'):
                n.pop(key, None)
            eligible = [m for m in n['members'] if m.get('role') not in METADATA
                        and m.get('type') not in {'heading', 'furniture'}]
            n['eligible_members'] = [dict(kind=m['kind'], member_id=m['id'], eligible=m in eligible) for m in n['members']]
            if not eligible:
                excluded.append(n['id']); continue
            label = 'N%03d' % (len(public_nodes) + 1)
            public_nodes.append(dict(label=label, id=n['id'], type=n['unit_type'], bbox=n['bbox'],
                members=[dict(kind=m['kind'], member_id=m['id'], role=m.get('role'),
                              text=m.get('semantic_text', m.get('text', '')),
                              generated_description=m['kind'] == 'visual') for m in eligible]))
        public_titles = [dict(label='T%03d' % (i + 1), id=t['id'],
                              text=t.get('semantic_text', t['text']), bbox=t['bbox'])
                         for i, t in enumerate(page['titles'])]
        payload = dict(document=page['document'], page=page['page'], document_mode=page['document_mode'],
                       nodes=public_nodes, titles=public_titles)
        inputs.append(dict(page_id=page['page_id'], task=task, payload=payload,
                           image=str((out / page['image']).resolve()), excluded_node_ids=excluded,
                           prompt=page_prompt(payload)))
        pages.append(page); selected.add(page['document'])
        for f in [path, rep_path, path.parent / 'run_summary.json', args.source / task / 'original.png']:
            fingerprints[str(f.resolve())] = sha(f)
    expected_selected = {task for task in expected if (not args.include_document or any(
        d in Path(task).parts for d in args.include_document)) and (not args.include_task or task in args.include_task)}
    if seen != expected_selected or not pages or set(args.include_document) - selected:
        raise ValueError('Missing document/page input coverage')
    pages.sort(key=lambda p: (p['document'], p['page_number']))
    jsonl(out / 'pages.jsonl', pages); jsonl(out / 'page_inputs.jsonl', inputs)
    write(out / 'pages.json', pages)
    write(out / 'protocol.json', dict(stage='hybrid_qwen_article_clustering_v3', model=str(args.model),
        device=args.device, pages=len(pages), documents=sorted(selected),
        single_work_profiles=args.single_document, max_lookback_pages=3,
        ordering='Hybrid immutable nodes -> Qwen membership with structural titles -> reading flows within fixed clusters -> grounded cross-page identity -> downstream semantic candidates',
        membership_and_reading_validated_independently=True,
        semantic_edges_generated=False, legacy_segmentation_reused=False,
        caveat='Model proposals and structural coverage checks are not independently measured segmentation accuracy. Sparse pages cannot establish missing reading adjacency.'))
    files = [Path(__file__), ROOT / 'EvidenceNet/evidence_graph/hybrid_article_clustering.py',
             Path(viewer.__file__), ROOT / 'EvidenceNet/evidence_graph/llm_client.py',
             args.source / 'manifest.json', out / 'pages.jsonl', out / 'page_inputs.jsonl', out / 'protocol.json']
    files += [Path(i['image']) for i in inputs]
    fingerprints.update({str(f.resolve()): sha(f) for f in files})
    write(out / 'manifest.json', dict(files=fingerprints))
    print(json.dumps(dict(prepared_pages=len(pages), documents=sorted(selected))), flush=True)


def check(out):
    for p, h in read(out / 'manifest.json')['files'].items():
        if sha(p) != h:
            raise ValueError('Changed article input/code: ' + p)


def call(model, path, prompt, images, validator, tokens):
    fingerprint = stable_id('', [prompt, [sha(p) for p in images]])
    if path.exists():
        record = read(path)
        if record['input_sha256'] != fingerprint:
            raise ValueError('Stale article checkpoint: ' + str(path))
        return record
    attempts = []; value = None
    for _ in range(2):
        raw = None
        try:
            request = prompt if not attempts else (prompt + '\nPREVIOUS_RESPONSE:\n' + str(attempts[-1]['raw']) +
                '\nVALIDATION_ERROR:\n' + attempts[-1]['error'] +
                '\nReturn the complete corrected JSON. Preserve correct assignments, explicitly place every missing ID; '
                'never silently drop a paragraph or treat it as page context just to satisfy coverage.')
            raw = model.generate_raw_with_images('Reconstruct document articles from supplied sources. JSON only.', request, images, tokens).raw
            value = validator(extract_json(raw))
            attempts.append(dict(raw=raw, valid=True)); break
        except Exception as exc:
            attempts.append(dict(raw=raw, valid=False, error=str(exc)))
    record = dict(input_sha256=fingerprint, valid=value is not None, value=value, attempts=attempts)
    write(path, record)
    return record


def compact_node(n):
    allowed = {(m['kind'], m['member_id']) for m in n['eligible_members'] if m['eligible']}
    text = '\n'.join(m.get('text', '') for m in n['members'] if (m['kind'], m['id']) in allowed)
    return dict(id=n['id'], text=text if len(text) <= 1800 else text[:900] + '\n[...omitted middle...]\n' + text[-900:])


def materialize(out, model):
    pages = rows(out / 'pages.jsonl')
    inputs = {i['page_id']: i for i in rows(out / 'page_inputs.jsonl')}
    nodes, title_assignments, groups, reading, issues = [], [], [], [], []
    reading_issues = []
    active = {}; assignments = []
    for page in pages:
        inp = inputs[page['page_id']]; payload = inp['payload']
        local = call(model, out / 'page_decisions' / (page['page_id'] + '.json'), inp['prompt'], [inp['image']],
                     lambda value: validate_membership(value, payload), 2200) if payload['nodes'] else dict(valid=True,
                         value=dict(groups=[], page_context_title_ids=[t['label'] for t in payload['titles']], conflicted_nodes=[]))
        by_label = {n['label']: n['id'] for n in payload['nodes']}
        original_nodes = {n['id']: n for n in page['nodes']}
        title_lookup = {t['label']: t for t in payload['titles']}
        page_groups = []
        if local['valid']:
            membership = local['value']
            if membership['groups']:
                flow_result = call(model, out / 'reading_decisions' / (page['page_id'] + '.json'),
                    reading_prompt(payload, membership), [inp['image']],
                    lambda value: validate_reading(value, payload, membership), 1800)
                if flow_result['valid']:
                    local = dict(local, value=flow_result['value'])
                else:
                    reading_issues.append(dict(page_id=page['page_id'], type='PAGE_READING_UNRESOLVED'))
            for g in local['value']['groups']:
                cid = stable_id('CLUSTER_', [page['document'], page['page'], g['id']])
                ids = [by_label[n] for n in g['nodes']]
                flows = [dict(kind=f['kind'], nodes=[by_label[n] for n in f['nodes']]) for f in g['flows']]
                page_groups.append(dict(cluster_id=cid, document=page['document'], page_number=page['page_number'],
                    kind=g['kind'], node_ids=ids, nodes=[compact_node(original_nodes[nid]) for nid in ids],
                    titles=[title_lookup[t] for t in g['title_ids']], flows=flows,
                    body_heads=[f['nodes'][0] for f in flows if f['kind'] == 'body' and f['nodes']],
                    body_tails=[f['nodes'][-1] for f in flows if f['kind'] == 'body' and f['nodes']]))
        else:
            issues.append(dict(page_id=page['page_id'], type='PAGE_CLUSTER_FAILED'))
        eligible_current = [g for g in page_groups if g['kind'] == 'article']
        previous = [g for g in active.values() if g['document'] == page['document']
                    and 0 < page['page_number'] - g['page_number'] <= 3]
        choices = {}
        if eligible_current and previous and page['document_mode'] != 'single_article':
            cross_payload = dict(document=page['document'], page_number=page['page_number'],
                                 current=eligible_current, previous=previous,
                                 reading_adjacency_verified=False)
            cross = call(model, out / 'continuation_decisions' / (page['page_id'] + '.json'),
                         continuation_prompt(cross_payload), [], lambda v: validate_continuations(v, cross_payload), 1800)
            if cross['valid']:
                choices = {r['cluster_id']: r for r in cross['value']['decisions']}
            else:
                issues.append(dict(page_id=page['page_id'], type='CROSS_PAGE_UNRESOLVED'))
        conflict_ids = {by_label[n] for n in local['value']['conflicted_nodes']} if local['valid'] else set()
        assigned, assigned_titles = {}, {}
        for g in page_groups:
            choice = choices.get(g['cluster_id'])
            aid = stable_id(page['document'] + '::ARTICLE_', g['cluster_id'])
            status = 'MODEL_PAGE_CONTEXT' if g['kind'] == 'page_context' else 'UNRESOLVED' if g['kind'] == 'uncertain' else 'PAGE_LOCAL_ONLY'
            if g['kind'] == 'page_context':
                aid = None
            elif page['document_mode'] == 'single_article':
                aid = page['document'] + '::DOCUMENT_ARTICLE'; status = 'KNOWN_PAPER_DOCUMENT_PROFILE'
            elif choice and choice['decision'] == 'SAME_ARTICLE':
                aid = choice['previous_article_id']; status = 'QWEN_CROSS_PAGE_LINKED'
                for old in assignments:
                    if old['article_id'] == aid and old['assignment_status'] == 'PAGE_LOCAL_ONLY':
                        old['assignment_status'] = status
                if choice.get('reading_link'):
                    reading.append(dict(source=choice['reading_link']['source'], target=choice['reading_link']['target'],
                        type='NEXT', article_id=aid, cross_page=True, status='QWEN_DIRECT_SUCCESSOR_PROPOSAL'))
            for nid in g['node_ids']:
                row = dict(node_id=nid, article_id=None if nid in conflict_ids else aid,
                           assignment_status='UNRESOLVED' if nid in conflict_ids else status,
                           cluster_id=g['cluster_id'], document=page['document'], page=page['page'],
                           method='qwen_page_clustering_then_grounded_continuation')
                assignments.append(row); assigned[nid] = row
            for title in g['titles']:
                assigned_titles[title['label']] = aid
            for flow in g['flows']:
                for a, b in zip(flow['nodes'], flow['nodes'][1:]):
                    if a not in conflict_ids and b not in conflict_ids and status not in {'UNRESOLVED', 'MODEL_PAGE_CONTEXT'}:
                        reading.append(dict(source=a, target=b, type='NEXT', article_id=aid, flow_kind=flow['kind'],
                            cross_page=False, status='QWEN_PAGE_FLOW_PROPOSAL'))
            g.update(article_id=aid, assignment_status=status); groups.append(g)
            if g['kind'] == 'article' and not conflict_ids.intersection(g['node_ids']):
                active[aid] = dict(g)
        for nid, n in original_nodes.items():
            n.update(document=page['document'], page=page['page'], task=page['task'])
            if nid not in assigned:
                row = dict(node_id=nid, article_id=None, assignment_status='EXCLUDED_METADATA' if nid in inp['excluded_node_ids']
                           else 'UNRESOLVED', document=page['document'], page=page['page'])
                assignments.append(row)
            nodes.append(n)
        for t in payload['titles']:
            title_assignments.append(dict(title_id=stable_id('TITLE_', [page['document'], page['page'], t['id']]),
                source_title_id=t['id'], document=page['document'], page=page['page'],
                text=t['text'], bbox=t['bbox'], article_id=assigned_titles.get(t['label']),
                status='ASSIGNED_STRUCTURAL_TITLE' if assigned_titles.get(t['label']) else 'PAGE_CONTEXT_OR_UNRESOLVED'))
        print(json.dumps(dict(page=page['task'], clusters=len(page_groups), valid=local['valid'])), flush=True)
    amap = {a['node_id']: a for a in assignments}
    for n in nodes:
        n.update({k: amap[n['id']].get(k) for k in ('article_id', 'assignment_status', 'cluster_id')})
        if n['assignment_status'] == 'MODEL_PAGE_CONTEXT':
            n['eligible_members'] = [dict(m, eligible=False, reason='model_page_context_proposal_source_review_required')
                                     for m in n['eligible_members']]
    # Endpoints stay immutable; no NEXT edge may silently cross known article membership.
    for e in reading:
        if not amap[e['source']]['article_id'] or amap[e['source']]['article_id'] != amap[e['target']]['article_id']:
            raise ValueError('Reading edge crosses article boundary')
    jsonl(out / 'units.jsonl', nodes); jsonl(out / 'article_assignments.jsonl', assignments)
    jsonl(out / 'article_clusters.jsonl', groups); jsonl(out / 'title_assignments.jsonl', title_assignments)
    jsonl(out / 'reading_edges.jsonl', reading); jsonl(out / 'issues.jsonl', issues)
    jsonl(out / 'reading_issues.jsonl', reading_issues)
    jsonl(out / 'excluded_non_evidence_units.jsonl', [n for n in nodes
          if n['assignment_status'] in {'MODEL_PAGE_CONTEXT', 'EXCLUDED_METADATA'}])
    articles = {}
    for a in assignments:
        if not a['article_id']:
            continue
        article = articles.setdefault(a['article_id'], dict(article_id=a['article_id'], document=a['document'],
            node_ids=[], pages=set(), title_ids=[], assignment_statuses=set()))
        article['node_ids'].append(a['node_id']); article['pages'].add(a['page'])
        article['assignment_statuses'].add(a['assignment_status'])
    for t in title_assignments:
        if t['article_id'] in articles:
            articles[t['article_id']]['title_ids'].append(t['title_id'])
    for a in articles.values():
        a['pages'] = sorted(a['pages']); a['assignment_statuses'] = sorted(a['assignment_statuses'])
    jsonl(out / 'articles.jsonl', articles.values())
    write(out / 'eligibility.json', {n['id']: dict(eligible=any(m['eligible'] for m in n['eligible_members']),
          members=n['eligible_members']) for n in nodes})
    summary = dict(pages=len(pages), nodes=len(nodes), article_clusters=len(groups),
        article_identities=len({a['article_id'] for a in assignments if a['article_id']}),
        statuses=dict(Counter(a['assignment_status'] for a in assignments)),
        titles=len(title_assignments), assigned_titles=sum(bool(t['article_id']) for t in title_assignments),
        unresolved_nodes=sum(a['assignment_status'] == 'UNRESOLVED' for a in assignments),
        model_page_context_nodes=sum(a['assignment_status'] == 'MODEL_PAGE_CONTEXT' for a in assignments),
        reading_edges=len(reading), cross_page_reading_edges=sum(e['cross_page'] for e in reading),
        failures=issues, complete=not issues, article_membership_complete=not issues,
        reading_failures=reading_issues, reading_complete=not issues and not reading_issues, semantic_edges_generated=False,
        quality='Source coverage validated; article ownership and reading flows are model proposals pending source review.')
    write(out / 'summary.json', summary)
    outputs = ['units.jsonl', 'article_assignments.jsonl', 'article_clusters.jsonl', 'articles.jsonl',
               'title_assignments.jsonl', 'reading_edges.jsonl', 'eligibility.json', 'issues.jsonl', 'summary.json',
               'excluded_non_evidence_units.jsonl', 'reading_issues.jsonl']
    write(out / 'article_graph_manifest.json', dict(ready_for_downstream=not issues,
          reading_ready=not issues and not reading_issues,
          input_manifest_sha256=sha(out / 'manifest.json'),
          files={name: sha(out / name) for name in outputs},
          graph_contract='Exact hybrid EvidenceNode IDs; structural titles separate; reading NEXT separate from semantic edges.'))
    if issues:
        raise RuntimeError('Article reconstruction incomplete; inspect issues, do not proceed to semantic edges')
    return summary


def run(args):
    prepare(args); check(args.output)
    if args.device == 'cpu':
        import torch
        torch.set_num_threads(32)
    model = create_llm(dict(provider='transformers', model=str(args.model), dtype='bfloat16',
        device_map='cpu' if args.device == 'cpu' else 'auto', require_cuda=args.device != 'cpu', enable_thinking=False))
    return materialize(args.output, model)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'run'])
    p.add_argument('--source', type=Path, required=True, help='Prepared hybrid source pages')
    p.add_argument('--nodes', type=Path, required=True, help='Root with batch_*/hybrid outputs')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', type=Path, default=MODEL)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--include-document', action='append', default=[])
    p.add_argument('--include-task', action='append', default=[], help='Exact page task for a bounded smoke test')
    p.add_argument('--single-document', action='append', default=[], help='Explicit known single-work profile')
    return p


if __name__ == '__main__':
    args = parser().parse_args()
    result = globals()[args.command](args)
    if result is not None:
        print(json.dumps(result), flush=True)
