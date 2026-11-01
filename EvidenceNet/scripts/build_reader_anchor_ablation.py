#!/usr/bin/env python3
"""Offline text-only fixed-candidate reader packets. No gold or answer input.

Uses full original members (including full HTML tables), never clipped anchors.
This is a localization development experiment, not an answer-quality evaluation.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import math
from pathlib import Path
import re

import numpy as np
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[2]
DIAG = ROOT / 'migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics'
TRACE = ROOT / 'migration/vldocir_trace_inputs_20261023'
SOURCE = ROOT / 'migration/vldocir-edge-20261022/results'
MODEL = ROOT / 'external/models/Qwen3.5-35B-A3B'
OUT = ROOT / 'EvidenceNet/output/reader_anchor_ablation_20261029'
BUDGETS = (512, 1024, 2048, 4096)
STOP = set('the a an of to in and or is are was were for with by what how which does did'.split())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def terms(text):
    return set(re.findall(r'\w+', html.unescape(re.sub('<[^>]*>', ' ', text)).lower())) - STOP


def count(tokenizer, text):
    return len(tokenizer.encode(text, add_special_tokens=False).ids)


def render(packets):
    # Document labels preserve identity without sending UUIDs to the reader.
    docs = {}
    blocks = []
    for i, p in enumerate(packets, 1):
        doc = docs.setdefault(p['page'][0], len(docs) + 1)
        blocks.append(f"[E{i}] Document D{doc}, page {p['page'][1]}\n{p['text']}")
    return '\n\n'.join(blocks)


def pack(ranked, budget, tokenizer):
    chosen, dropped, seen = [], [], set()
    for p in ranked:
        # Keep equal wording from DIFFERENT documents: they are different evidence.
        key = (tuple(p['page']), p['member_sha256'])
        if key in seen:
            dropped.append({'packet_id': p['packet_id'], 'reason': 'same_page_exact_duplicate'})
            continue
        if count(tokenizer, render(chosen + [p])) > budget:
            dropped.append({'packet_id': p['packet_id'], 'reason': 'complete_member_over_remaining_budget'})
            continue
        chosen.append(p)
        seen.add(key)
    return chosen, dropped


def verify_anchor(span, members):
    m = members[(span['node_id'], span['member_id'])]
    text = m['text']
    lo, hi = span['char_start'], span['char_end']
    if sha(text) != span['member_sha256'] or not 0 <= lo <= hi <= len(text) or text[lo:hi] != span['text']:
        raise ValueError('anchor source mismatch: ' + span['span_id'])
    return m


def build(out, model):
    if out.exists():
        raise ValueError('Use a fresh output directory; do not overwrite a frozen run')
    files = [DIAG / n for n in ('queries.jsonl', 'query_candidates.jsonl', 'search_paths.jsonl', 'edge_records.jsonl')]
    files += [TRACE / n for n in ('queries.jsonl', 'units.jsonl', 'windows.jsonl')]
    files += [SOURCE / 'nodes.jsonl', SOURCE / 'search/query_window_scores.npy', model / 'tokenizer.json', Path(__file__)]
    tokenizer = Tokenizer.from_file(str(model / 'tokenizer.json'))
    tokenizer.no_truncation(); tokenizer.no_padding()
    queries = rows(DIAG / 'queries.jsonl')
    assert [q['question_id'] for q in queries] == [q['question_id'] for q in rows(TRACE / 'queries.jsonl')]
    candidates = {r['question_id']: [tuple(map(str, p)) for p in r['pages']] for r in rows(DIAG / 'query_candidates.jsonl') if r['arm'] == 'D_relation'}
    assert set(candidates) == {q['question_id'] for q in queries}
    assert all(len(p) == len(set(p)) == 20 for p in candidates.values())
    paths = {r['question_id']: r for r in rows(DIAG / 'search_paths.jsonl') if r['arm'] == 'D_relation'}
    nodes = rows(SOURCE / 'nodes.jsonl')
    members, packets, exclusions = {}, [], []
    for node in nodes:
        allowed = {m['member_id'] for m in node.get('eligible_members', []) if m.get('eligible')}
        for m in node['members']:
            members[node['id'], m['id']] = m
            if m['id'] not in allowed or not m.get('text', '').strip() or m.get('kind') == 'visual':
                exclusions.append({'node_id': node['id'], 'member_id': m['id'], 'reason': 'ineligible_empty_or_generated_visual'})
                continue
            packets.append({'packet_id': sha(node['id'] + ':' + m['id']), 'node_id': node['id'], 'member_id': m['id'],
                'page': [str(node['document']), str(node['page'])], 'text': m['text'], 'member_sha256': sha(m['text']),
                'char_start': 0, 'char_end': len(m['text']), 'boxes': m.get('boxes', []),
                'source_image_path': node.get('source_image_path'), 'node_type': node.get('node_type'),
                'source_kind': 'ORIGINAL_PARSER_MEMBER', 'context_policy': 'full_member_no_clipping',
                'context_sufficiency': 'unreviewed', 'visual_input_included': False})
    edges = {e['edge_id']: e for e in rows(DIAG / 'edge_records.jsonl')}
    for edge in edges.values():
        for ep in edge['endpoints'].values():
            for span in ep['spans']:
                verify_anchor(span, members)
    units = rows(TRACE / 'units.jsonl'); windows = rows(TRACE / 'windows.jsonl')
    scores = np.load(SOURCE / 'search/query_window_scores.npy', allow_pickle=False)
    assert scores.shape == (len(queries), len(windows))
    df = Counter(t for p in packets for t in terms(p['text']))
    idf = {t: math.log(1 + len(packets) / (1 + n)) for t, n in df.items()}
    pt = {p['packet_id']: terms(p['text']) for p in packets}
    records, annotations = [], {}
    for qi, q in enumerate(queries):
        qid = q['question_id']; pages = set(candidates[qid]); qt = terms(q['question'])
        dense = defaultdict(lambda: -1.)
        for wi, w in enumerate(windows):
            nid = units[w['unit_input_line'] - 1]['unit_id']
            dense[nid] = max(dense[nid], float(scores[qi, wi]))
        available = [p for p in packets if tuple(p['page']) in pages]
        lex = {p['packet_id']: sum(idf[t] for t in qt & pt[p['packet_id']]) / math.sqrt(max(1, len(pt[p['packet_id']]))) for p in available}
        lr = {p['packet_id']: i + 1 for i, p in enumerate(sorted(available, key=lambda p: (-lex[p['packet_id']], p['packet_id'])))}
        dr = {p['packet_id']: i + 1 for i, p in enumerate(sorted(available, key=lambda p: (-dense[p['node_id']], p['packet_id'])))}
        links = defaultdict(list); anchor_audit = []
        for route in paths[qid]['paths']:
            for side, ep in edges[route['edge_id']]['endpoints'].items():
                if (str(ep['document_id']), str(ep['page_number'])) not in pages:
                    continue
                for span in ep['spans']:
                    anchor = {'edge_id': route['edge_id'], 'edge_rank': route['edge_rank'], 'edge_score': route['edge_score'],
                              'side': side, 'span': span, 'entry': 'global_edge_index_not_seed_traversal'}
                    anchor_audit.append(anchor)
                    if span['source_kind'] == 'ORIGINAL_TEXT':
                        links[(span['node_id'], span['member_id'])].append(anchor)
        common = []
        for p in available:
            linked = links[(p['node_id'], p['member_id'])]
            base = 1 / (60 + lr[p['packet_id']]) + 1 / (60 + dr[p['packet_id']])
            bonus = 1 / (60 + min(a['edge_rank'] for a in linked)) if linked else 0
            common.append({**p, 'base_score': base, 'edge_bonus': bonus, 'anchor_ids': [a['span']['span_id'] for a in linked]})
        for arm in ('B_node', 'C_node_edge'):
            ranked = sorted(common, key=lambda p: (-(p['base_score'] + (p['edge_bonus'] if arm == 'C_node_edge' else 0)), p['packet_id']))
            for budget in BUDGETS:
                chosen, dropped = pack(ranked, budget, tokenizer)
                context = render(chosen)
                prompt = 'Answer using only the evidence. Cite [E#]. State if evidence is insufficient.\nQuestion: ' + q['question'] + '\nEvidence:\n' + context
                covered = {a for p in chosen for a in p['anchor_ids']}
                audit = [{**a, 'included': a['span']['span_id'] in covered} for a in anchor_audit]
                records.append({'question_id': qid, 'question': q['question'], 'arm': arm, 'budget': budget,
                    'candidate_pages': candidates[qid], 'evidence_text': context, 'prompt_text': prompt,
                    'evidence_tokens': count(tokenizer, context), 'plain_prompt_tokens': count(tokenizer, prompt),
                    'chat_template_tokens': None, 'visual_tokens': 0, 'answer_llm_run': False,
                    'prompt_sha256': sha(prompt), 'packets': chosen, 'dropped': dropped, 'anchors': audit})
                for p in chosen:
                    key = sha(qid + p['packet_id'])
                    annotations[key] = {'review_id': key, 'question': q['question'], 'page': p['page'], 'text': p['text'],
                        'source_node_id': p['node_id'], 'source_member_id': p['member_id'], 'label': 'UNREVIEWED',
                        'allowed_labels': ['DIRECT', 'NECESSARY_CONTEXT', 'IRRELEVANT', 'UNCERTAIN'], 'notes': ''}
    out.mkdir(parents=True)
    def dump(name, value):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    (out / 'packets.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    # No arm or ranking shown in review records. Shuffle by stable opaque hash.
    (out / 'blinded_review.jsonl').write_text(''.join(json.dumps(annotations[k], ensure_ascii=False) + '\n' for k in sorted(annotations)))
    dump('excluded_members.json', exclusions)
    stats = []
    for budget in BUDGETS:
        for arm in ('B_node', 'C_node_edge'):
            rr = [r for r in records if r['budget'] == budget and r['arm'] == arm]
            stats.append({'budget': budget, 'arm': arm, 'queries': len(rr), 'mean_evidence_tokens': sum(r['evidence_tokens'] for r in rr) / len(rr),
                'anchors_included': sum(a['included'] for r in rr for a in r['anchors']), 'anchors_total': sum(len(r['anchors']) for r in rr),
                'answer_quality': None, 'noise_rate': None})
    dump('summary.json', stats)
    dump('manifest.json', {'files': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'scope': '24 development queries, fixed D20 candidates, text-only, no answer inference',
        'selection': 'lexical+dense RRF60; C adds one edge-rank RRF60 term; full original members only',
        'token_accounting': 'Qwen3.5 tokenizer exact evidence/plain prompt text; chat template and visual processing NOT measured',
        'limitations': ['Not a four-arm end-to-end comparison', 'No semantic quality or noise labels yet',
                       'Full member may lack cross-member context', 'Existing D candidate set is graph-conditioned in BOTH arms',
                       'Anchor inclusion is mechanical, not a relevance metric', 'Generated visual descriptions excluded, no images']} )
    sections = ['<!doctype html><meta charset="utf-8"><title>Reader anchor ablation</title><style>body{font:16px system-ui;margin:24px}article{display:grid;grid-template-columns:1fr 1fr;gap:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border:1px solid #aaa;padding:12px}summary{cursor:pointer;padding:12px}</style>',
        '<h1>有边 / 无边：实际证据输入</h1><p>固定同一批20个候选页、相同token上限；仅原文文本。尚未运行回答LLM，未评定正确率/噪声率。锚点覆盖增加不等于质量提升。展开查看实际输入。</p>']
    for q in queries:
        for budget in BUDGETS:
            rr = [r for r in records if r['question_id'] == q['question_id'] and r['budget'] == budget]
            sections.append('<details><summary>' + html.escape(q['question']) + f' — {budget} tokens</summary><article>')
            for r in rr:
                sections.append('<section><h2>' + r['arm'] + f"</h2><p>{r['evidence_tokens']} evidence tokens; {sum(a['included'] for a in r['anchors'])}/{len(r['anchors'])} anchors</p><pre>" + html.escape(r['evidence_text']) + '</pre></section>')
            sections.append('</article></details>')
    (out / 'index.html').write_text('\n'.join(sections))
    print(json.dumps({'output': str(out), 'records': len(records), 'review_items': len(annotations), 'summary': stats}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--model', type=Path, default=MODEL)
    args = parser.parse_args()
    build(args.out, args.model)
