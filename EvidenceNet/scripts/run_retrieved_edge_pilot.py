#!/usr/bin/env python3
"""Build a bounded evidence graph from natural 76411-replay candidates."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from run_split_taxonomy_suite import (
    ROOT, MODEL, SYSTEM, node_input, pair_prompt, validate_result,
    create_llm, extract_json, read, rows, write, jsonl, sha,
)
from build_evidence_edge_review_suite import PAGE_OVERRIDES

SOURCE = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
OUT = ROOT / 'EvidenceNet/output/retrieved_evidence_edges_pilot_v2_20261015'


def verify_manifest(path):
    for p, h in read(path)['files'].items():
        if sha(p) != h:
            raise ValueError('Changed frozen input/code: ' + p)


def plan(out):
    if (out / 'plan.json').exists():
        verify_manifest(out / 'plan.json')
        return
    files = [Path(__file__), Path(__file__).with_name('run_split_taxonomy_suite.py'),
             Path(__file__).with_name('run_node_context_edges.py'),
             Path(__file__).with_name('build_evidence_edge_review_suite.py'),
             ROOT / 'EvidenceNet/evidence_graph/run_split_taxonomy_relation_typing.py',
             ROOT / 'EvidenceNet/evidence_graph/llm_client.py', SOURCE / 'manifest.json']
    write(out / 'plan.json', dict(files={str(p.resolve()): sha(p) for p in files},
          source=str(SOURCE), candidate_budget=48, reference_labels_used_for_selection=False))


def confirmed_article(node):
    # PAGE_LOCAL_ONLY is a search bucket, not a confirmed magazine article.
    return node.get('original_article_id') if node.get('assignment_status') == 'KNOWN_PAPER_DOCUMENT_PROFILE' else None


def source_position(node):
    """Preserve page/slide/image identity; do not manufacture PDF pages for images."""
    override = PAGE_OVERRIDES.get((node['document'], node['page']))
    if override is not None:
        return dict(kind='pdf_page', number=override, source_label=node['page'])
    label = str(node['page'])
    if label.isdigit():
        return dict(kind='pdf_page', number=int(label), source_label=node['page'])
    match = re.fullmatch(r'(page|slide|image)_(\d+)', label)
    if not match:
        raise ValueError('Unknown source position: ' + label)
    return dict(kind={'page': 'pdf_page', 'slide': 'slide', 'image': 'image'}[match[1]],
                number=int(match[2]), source_label=node['page'])


def scope(a, b):
    if a['document'] != b['document']:
        return 'cross_document'
    aa, bb = confirmed_article(a), confirmed_article(b)
    if aa and bb:
        return 'intra_article' if aa == bb else 'same_pdf_cross_article'
    return 'same_pdf_article_unresolved'


def stratum(pair, nodes):
    a, b = nodes[pair['source']], nodes[pair['target']]
    members = []
    for n in (a, b):
        allowed = {(e['kind'], e['member_id']) for e in n['eligible_members'] if e['eligible']}
        members.extend(m for m in n['members'] if (m['kind'], m['id']) in allowed)
    modality = 'visual' if any(m['kind'] == 'visual' for m in members) else (
        'table' if any(m.get('type') == 'table' for m in members) else 'text')
    material = 'magazine' if any('courier' in n['document'].lower() or 'magazine' in n['document'].lower()
                               for n in (a, b)) else 'other'
    return (scope(a, b), material, modality)


def select(candidates, nodes, limit=48):
    buckets = defaultdict(list)
    for p in sorted(candidates, key=lambda p: (-p['retrieval_score'], p['source'], p['target'])):
        buckets[stratum(p, nodes)].append(p)
    selected = []; degrees = Counter()
    # Balanced trial across observed scopes/modalities, with fixed node degree cap.
    while len(selected) < limit:
        added = False
        for key in sorted(buckets):
            bucket = buckets[key]
            while bucket:
                p = bucket.pop(0)
                if degrees[p['source']] >= 4 or degrees[p['target']] >= 4:
                    continue
                selected.append(dict(p, pilot_stratum=list(key)))
                degrees[p['source']] += 1; degrees[p['target']] += 1
                added = True
                break
            if len(selected) == limit:
                break
        if not added:
            break
    return selected


def prepare(out):
    verify_manifest(out / 'plan.json')
    if (out / 'manifest.json').exists():
        verify_manifest(out / 'manifest.json')
        return
    candidates = rows(SOURCE / 'hierarchical_candidates.jsonl')
    ns = {n['id']: n for n in rows(SOURCE / 'corpus_nodes.jsonl')}
    policies = read(SOURCE / 'corpus_policies.json')
    inputs, invalid = {}, []
    for nid, n in ns.items():
        n['eligible_members'] = policies[nid]['members']
        n['source_position'] = source_position(n)
        n['original_pdf_page'] = n['source_position']['number'] if n['source_position']['kind'] == 'pdf_page' else None
        base = ROOT / 'EvidenceNet/output' / (
            'paper_relevance_urban_traffic_20261013/graph' if n['source_collection'] == 'traffic'
            else 'article_bridge_expanded_v5_20261012')
        for m in n['members']:
            if m.get('crop'):
                m['original_crop_path'] = str((base / m['crop']).resolve())
        try:
            inputs[nid] = node_input(n)
            inputs[nid]['source_position'] = n['source_position']
        except (KeyError, ValueError) as exc:
            invalid.append(dict(node_id=nid, error=str(exc)))
    usable = [p for p in candidates if p['source'] in inputs and p['target'] in inputs]
    selected = select(usable, ns)
    if not selected:
        raise ValueError('No usable natural candidates; do not report an empty graph as success')
    tasks = []
    for p in selected:
        ends = [p['source'], p['target']]
        task_id = 'NAT_' + hashlib.sha256(json.dumps(sorted(ends)).encode()).hexdigest()[:16]
        if int(hashlib.sha256(task_id.encode()).hexdigest(), 16) % 2:
            ends.reverse()
        task = dict(task_id=task_id, evidence_a=inputs[ends[0]], evidence_b=inputs[ends[1]])
        prompt = pair_prompt(task) + '''
Also return "semantic_grounding": null for REJECT_UNCERTAIN, otherwise an object:
{"source":{"member_id":"source endpoint member","quote":"short exact quote"},
 "target":{"member_id":"target endpoint member","quote":"short exact quote"},
 "reason":"Explain the specific relation and its direction; preserve limitations."}.
Quotes must each contain 8-180 characters copied from that member's supplied original_text or
qwen_visual_description. Do not quote the other endpoint. A generated description remains a model
representation, not an independently verified image fact. Shared topic is insufficient.
'''
        tasks.append(dict(task=task, prompt=prompt, candidate=p,
                          scope=scope(ns[p['source']], ns[p['target']])))
    chosen_ids = {p[k] for p in selected for k in ('source', 'target')}
    jsonl(out / 'nodes.jsonl', [ns[n] for n in sorted(chosen_ids)])
    jsonl(out / 'inputs.jsonl', tasks)
    jsonl(out / 'excluded_nodes.jsonl', invalid)
    write(out / 'protocol.json', dict(model=str(MODEL), cpu=True, pairs=len(tasks),
        natural_candidates=len(candidates), candidates_missing_descriptions_or_metadata=len(candidates)-len(usable),
        system=SYSTEM, semantic_types=['SUPPORTS', 'EXPLAINS_OR_ELABORATES', 'MODIFIES', 'CONTRASTS_WITH'],
        references='Independent explicit reference, original-text cue required', max_new_tokens=900, attempts=2,
        input='Eligible original text/captions/parsed tables plus existing Qwen visual descriptions; no images sent.',
        selection='Score-sorted within scope/material/modality strata, round-robin 48, degree cap 4; no labels.',
        scope='Bounded natural-candidate pilot, not all retrieved pairs. Article identities remain unresolved where not confirmed.',
        statuses='All graph edges are model proposals pending original-source review. Description anchors marked generated.',
        stratum_counts=dict(Counter('|'.join(t['candidate']['pilot_stratum']) for t in tasks))))
    files = [out / f for f in ('inputs.jsonl', 'nodes.jsonl', 'excluded_nodes.jsonl', 'protocol.json', 'plan.json')]
    files += [SOURCE / f for f in ('hierarchical_candidates.jsonl', 'corpus_nodes.jsonl', 'corpus_policies.json')]
    files += [Path(m['original_crop_path']) for nid in chosen_ids for m in ns[nid]['members'] if m.get('original_crop_path')]
    write(out / 'manifest.json', dict(files={str(p.resolve()): sha(p) for p in files}))
    print(json.dumps(dict(prepared=len(tasks), natural_candidates=len(candidates))), flush=True)


def anchor(member, quote):
    field = 'original_text' if 'original_text' in member else 'qwen_visual_description'
    text = member[field]
    if not isinstance(quote, str) or not 8 <= len(quote) <= 180:
        raise ValueError('Quote length must be 8-180 characters')
    start = text.find(quote); end = start + len(quote)
    if start < 0:
        # Permit whitespace-only differences, but bind back to an exact owned original span.
        chars, positions = [], []
        for i, ch in enumerate(text):
            if ch.isspace():
                if chars and chars[-1] != ' ':
                    chars.append(' '); positions.append(i)
            else:
                chars.append(ch); positions.append(i)
        q = re.sub(r'\s+', ' ', quote).strip()
        start_normalized = ''.join(chars).find(q)
        if start_normalized < 0:
            raise ValueError('Quote not owned by supplied member')
        start = positions[start_normalized]; end = positions[start_normalized + len(q) - 1] + 1
    return dict(member_id=member['member_id'], char_start=start, char_end=end, quote=text[start:end],
                member_sha256=hashlib.sha256(text.encode()).hexdigest(),
                kind='ORIGINAL_TEXT' if field == 'original_text' else 'QWEN_VISUAL_DESCRIPTION',
                source_verified=False)


def validate(value, task):
    normalized, valid = validate_result(value, task)
    if not valid:
        raise ValueError('Invalid semantic/reference schema or cue ownership')
    semantic = normalized['semantic']
    if semantic['relation'] == 'REJECT_UNCERTAIN':
        return dict(**normalized, semantic_grounding=None)
    grounding = value.get('semantic_grounding')
    if not isinstance(grounding, dict) or not isinstance(grounding.get('reason'), str) or not grounding['reason'].strip():
        raise ValueError('Semantic grounding and reason required')
    bound = dict(reason=grounding['reason'])
    for side in ('source', 'target'):
        nid = semantic[side + '_node_id']
        owner = next(n for n in (task['evidence_a'], task['evidence_b']) if n['node_id'] == nid)
        supplied = grounding[side]
        member = next((m for m in owner['members'] if m['member_id'] == supplied['member_id']), None)
        if member is None:
            raise ValueError('Anchor member belongs to other endpoint or is excluded')
        bound[side] = dict(node_id=nid, **anchor(member, supplied['quote']))
    return dict(**normalized, semantic_grounding=bound)


def report(out):
    tasks = rows(out / 'inputs.jsonl')
    nodes = {n['id']: n for n in rows(out / 'nodes.jsonl')}
    preds = rows(out / 'predictions.jsonl') if (out / 'predictions.jsonl').exists() else []
    lookup = {t['task']['task_id']: t for t in tasks}
    edges, statuses = [], Counter()
    for p in preds:
        if not p['valid']:
            statuses['INVALID'] += 1
            continue
        sem, ref = p['result']['semantic'], p['result']['references']
        statuses[sem['relation']] += 1
        for kind, decision in [('semantic', sem), ('reference', ref)]:
            if (kind == 'semantic' and sem['relation'] == 'REJECT_UNCERTAIN') or (kind == 'reference' and not ref['exists']):
                continue
            edges.append(dict(id=p['task_id'] + '::' + kind, pair_id=p['task_id'],
                source=decision['source_node_id'], target=decision['target_node_id'],
                relation=sem['relation'] if kind == 'semantic' else 'REFERENCES',
                symmetric=kind == 'semantic' and sem['relation'] == 'CONTRASTS_WITH',
                scope=lookup[p['task_id']]['scope'], decision=decision,
                grounding=p['result']['semantic_grounding'] if kind == 'semantic' else dict(cue=ref['cue']),
                review_status='MODEL_PROPOSAL_SOURCE_REVIEW_REQUIRED'))
    articles = defaultdict(list)
    for e in edges:
        a, b = confirmed_article(nodes[e['source']]), confirmed_article(nodes[e['target']])
        if not a or not b or a == b:
            continue
        articles[tuple(sorted((a, b)))].append(e['id'])
    jsonl(out / 'evidence_edges.jsonl', edges)
    jsonl(out / 'article_navigation_edges.jsonl', [dict(source=a, target=b, supporting_edge_ids=ids,
          status='NAVIGATION_FROM_MODEL_PROPOSALS_NOT_VERIFIED_ARTICLE_RELATION') for (a, b), ids in articles.items()])
    summary = dict(processed=len(preds), total=len(tasks), complete=len(preds) == len(tasks),
                   statuses=dict(statuses), evidence_edges=len(edges),
                   article_navigation_pairs=len(articles), source_review_complete=False)
    write(out / 'summary.json', summary)
    (out / 'REPORT.md').write_text('# Natural-candidate edge pilot\n\n```json\n' + json.dumps(summary, indent=2) +
        '\n```\n\nEdges are model proposals. Generated-description anchors are explicitly marked; '
        'article navigation aggregates only confirmed article IDs. Reading order is a separate existing graph.\n')
    return summary


def run(out):
    prepare(out)
    verify_manifest(out / 'manifest.json')
    import torch
    torch.set_num_threads(32)
    tasks = rows(out / 'inputs.jsonl')
    preds = rows(out / 'predictions.jsonl') if (out / 'predictions.jsonl').exists() else []
    if [p['task_id'] for p in preds] != [t['task']['task_id'] for t in tasks[:len(preds)]]:
        raise ValueError('Checkpoint mismatch')
    model = create_llm(dict(provider='transformers', model=str(MODEL), dtype='bfloat16',
                           device_map='cpu', require_cuda=False, enable_thinking=False))
    for t in tasks[len(preds):]:
        attempts = []; bound = None
        for _ in range(2):
            raw = None
            try:
                response = model.generate_raw_with_images(SYSTEM, t['prompt'], [], max_new_tokens=900)
                raw = response.raw
                bound = validate(extract_json(raw), t['task'])
                attempts.append(dict(raw=raw, valid=True))
                break
            except Exception as exc:
                attempts.append(dict(raw=raw, error=str(exc), valid=False))
        preds.append(dict(task_id=t['task']['task_id'], valid=bound is not None, result=bound, attempts=attempts))
        jsonl(out / 'predictions.jsonl', preds)
        print(json.dumps(report(out)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'prepare', 'run', 'report'])
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.command](args.output)
