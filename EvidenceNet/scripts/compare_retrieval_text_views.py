"""Controlled text retrieval views; immutable nodes and unchanged non-text views."""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import re
import time

import numpy as np
import run_hierarchical_edge_retrieval as h
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha, tokens

SOURCE = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
OUT = ROOT / 'EvidenceNet/output/retrieval_text_views_v1_20261016'
ARMS = ('whole', 'window', 'sentence')


def sentence_spans(text):
    """Exact original offsets, avoiding decimal/initial/abbreviation boundaries."""
    starts = [0]
    for match in re.finditer(r'[.!?][\"”’]?(?=\s+[A-Z\"“])', text):
        prefix = text[:match.end()].rstrip('"”’')
        if re.search(r'\b(?:[A-Z]|Fig|Figs|Eq|Eqs|Dr|Mr|Ms|Prof|al|vs|e\.g|i\.e)\.$', prefix):
            continue
        starts.append(match.end())
    starts.append(len(text))
    result = []
    for lo, hi in zip(starts, starts[1:]):
        while lo < hi and text[lo].isspace(): lo += 1
        while hi > lo and text[hi-1].isspace(): hi -= 1
        if hi > lo: result.append((lo, hi))
    return result


def text_views(nodes, policies, arm):
    base = h.make_views(nodes, policies)
    if arm == 'window': return base
    represented = {v['node_id'] for v in base}
    # Tables and visual descriptions are byte-identical to window-arm representations.
    special = {(n['id'], m['id']) for n in nodes.values() for m in n['members']
               if m['kind'] == 'visual' or '<table' in m.get('text', '').lower()}
    result = [deepcopy(v) for v in base if (v['node_id'], v['member_id']) in special]
    for n in sorted(nodes.values(), key=lambda n: n['id']):
        if n['id'] not in represented: continue
        allowed = {(m['member_id'], m['kind']) for m in policies[n['id']]['members'] if m['eligible']}
        members = [m for m in n['members'] if (m['id'], m['kind']) in allowed
                   and (n['id'], m['id']) not in special and m.get('text', '').strip()]
        if arm == 'whole':
            if not members: continue
            # A retrieval-only concatenation, with every original member span recorded.
            text = '\n'.join(m['text'] for m in members)
            if len(tokens(h.clean(text))) < 4: continue
            result.append(dict(node_id=n['id'], article_id=n['article_id'], member_id=None,
                member_kind='atom', kind='whole_text_node', char_start=None, char_end=None,
                quote=None, retrieval_text=h.clean(text), identifiers=h.identifiers(text),
                source_status='ORIGINAL_TEXT', source_spans=[dict(member_id=m['id'],
                    char_start=0, char_end=len(m['text']), quote=m['text']) for m in members]))
        else:
            for m in members:
                spans = sentence_spans(m['text'])
                seen = set()
                for i, (lo, hi) in enumerate(spans):
                    focus = (lo, hi)
                    plain = h.clean(m['text'][lo:hi])
                    # Generic, label-blind antecedent context; no hand-picked method names.
                    needs_context = bool(re.match(r'(?i)^(?:it|its|they|their|this|these|those|such|however|therefore|in contrast)\b', plain)) or len(plain.split()) < 12
                    if i and needs_context and len(m['text'][spans[i-1][0]:hi].split()) <= 160:
                        lo = spans[i-1][0]
                    if (lo, hi) in seen or len(tokens(h.clean(m['text'][lo:hi]))) < 4: continue
                    seen.add((lo, hi))
                    result.append(dict(node_id=n['id'], article_id=n['article_id'], member_id=m['id'],
                        member_kind=m['kind'], kind='sentence_context', char_start=lo, char_end=hi,
                        quote=m['text'][lo:hi], retrieval_text=h.clean(m['text'][lo:hi]),
                        identifiers=h.identifiers(m['text'][lo:hi]), source_status='ORIGINAL_TEXT',
                        focus_char_start=focus[0], focus_char_end=focus[1]))
    result.sort(key=lambda v: (v['node_id'], str(v['member_id']), v['char_start'] or 0, v['kind']))
    for i, v in enumerate(result): v['view_id'] = f'VIEW_{i:06d}'
    return result


def prepare(out):
    if (out / 'manifest.json').exists(): check(out); return
    nodes = {n['id']: n for n in rows(SOURCE / 'corpus_nodes.jsonl')}
    policies = read(SOURCE / 'corpus_policies.json')
    stats = {}
    for arm in ARMS:
        views = text_views(nodes, policies, arm)
        jsonl(out / arm / 'views.jsonl', views)
        stats[arm] = dict(views=len(views), nodes=len({v['node_id'] for v in views}))
    write(out / 'protocol.json', dict(nodes=len(nodes), arms=ARMS, views=stats,
        encoder=str(h.ENCODER), dtype='float32', device='cpu', embedding_max_tokens=512,
        sentence_rule='All eligible text, punctuation sentences; one preceding sentence for anaphora or <12 words, combined <=160 whitespace words. No labels or named-method filters.',
        fixed='Original evidence nodes, eligible members, model, 512-token truncation, non-text/table views, RRF and route parameters. Labels only read after candidates frozen.',
        budget='Native default hierarchy plus identical top-K prefix K=min(1301, native count of each arm). Also global RRF top1301 diagnostic with no article route.',
        caveats='View counts differ by representation. Whole text may truncate; token lengths reported. Fixed article identities include unresolved page buckets. No semantic verifier, no query retrieval quality, development cases only.'))
    files = [SOURCE / x for x in ['corpus_nodes.jsonl','corpus_policies.json','views.jsonl','view_vectors.npy','evaluation/cases.jsonl']]
    files += [Path(__file__), Path(h.__file__), Path(h.__file__).with_name('run_traffic_relevance_cpu.py')]
    files += [out / a / 'views.jsonl' for a in ARMS] + [out / 'protocol.json']
    files += list(h.ENCODER.glob('*.json')) + [h.ENCODER / 'model.safetensors', h.ENCODER / 'merges.txt', h.ENCODER / 'vocab.json']
    write(out / 'manifest.json', {'files': {str(p): sha(p) for p in files}})
    print(stats, flush=True)


def check(out):
    for p, digest in read(out / 'manifest.json')['files'].items():
        if sha(p) != digest: raise ValueError('changed frozen input: ' + p)


def run(out):
    check(out)
    import torch
    from transformers import AutoTokenizer
    torch.set_num_threads(32)
    started = time.monotonic()
    nodes = {n['id']: n for n in rows(SOURCE / 'corpus_nodes.jsonl')}
    views = {a: rows(out / a / 'views.jsonl') for a in ARMS}
    oldviews = rows(SOURCE / 'views.jsonl')
    oldvectors = np.load(SOURCE / 'view_vectors.npy')
    assert len(oldviews) == len(oldvectors)
    cache = {v['retrieval_text']: oldvectors[i] for i, v in enumerate(oldviews)}
    texts = sorted({v['retrieval_text'] for vs in views.values() for v in vs} - cache.keys())
    tokenizer = AutoTokenizer.from_pretrained(h.ENCODER, local_files_only=True)
    for arm in ARMS:
        lengths = [len(tokenizer(v['retrieval_text'])['input_ids']) for v in views[arm]]
        write(out / arm / 'token_lengths.json', dict(total=len(lengths), truncated=sum(n>512 for n in lengths),
              maximum=max(lengths), per_view=dict(zip([v['view_id'] for v in views[arm]], lengths))))
    # New embeddings are checkpointed so report/retrieval retries do not re-encode.
    if (out / 'new_vectors.npy').exists():
        assert read(out / 'new_texts.json') == texts
        encoded = np.load(out / 'new_vectors.npy')
    else:
        write(out / 'new_texts.json', texts)
        encoded = np.asarray(h.cpu_embed(texts, h.ENCODER), dtype=np.float32)
        np.save(out / 'new_vectors.npy', encoded)
    assert len(encoded) == len(texts)
    cache.update(zip(texts, encoded))
    native = {}
    for arm in ARMS:
        print('retrieving', arm, len(views[arm]), flush=True)
        vectors = np.asarray([cache[v['retrieval_text']] for v in views[arm]], dtype=np.float32)
        np.save(out / arm / 'vectors.npy', vectors)
        pool = h.retrieve(views[arm], vectors)
        articles, selected = h.route_and_select(nodes, pool)
        jsonl(out / arm / 'initial_pool.jsonl', pool.values())
        jsonl(out / arm / 'article_candidates.jsonl', articles)
        jsonl(out / arm / 'native_candidates.jsonl', selected)
        native[arm] = selected
    budget = min(1301, *(len(native[a]) for a in ARMS))
    # Only now open references, after all retrieval outputs have been produced.
    cases = rows(SOURCE / 'evaluation/cases.jsonl')
    from compare_previous_edge_schemes import coverage
    summaries, detail = {}, {}
    for arm in ARMS:
        pool = rows(out / arm / 'initial_pool.jsonl')
        matched = native[arm][:budget]
        global_ranked = sorted(pool, key=lambda p: (-p['retrieval_score'],p['source'],p['target']))[:1301]
        jsonl(out / arm / 'matched_candidates.jsonl', matched)
        summaries[arm], detail[arm] = {}, {}
        for name, pairs in [('initial',pool),('native',native[arm]),('matched',matched),('global_rrf_1301',global_ranked)]:
            summaries[arm][name], detail[arm][name] = coverage(cases, pairs)
        diagnostics = []
        ordered = sorted(pool, key=lambda p: (-p['retrieval_score'],p['source'],p['target']))
        rank = {frozenset((p['source'],p['target'])): i+1 for i,p in enumerate(ordered)}
        lookup = {frozenset((p['source'],p['target'])): p for p in pool}
        for c in cases:
            key = frozenset((c['A']['node_id'],c['B']['node_id']))
            diagnostics.append(dict(case_id=c['suite_case_id'], rank=rank.get(key), candidate=lookup.get(key)))
        jsonl(out / arm / 'case_diagnostics.jsonl', diagnostics)
        # Pair cosine and node-max ranks even when top-30 view retrieval missed a pair.
        vs = views[arm]
        vec = np.load(out / arm / 'vectors.npy')
        ids = sorted({v['node_id'] for v in vs})
        index = {nid: i for i, nid in enumerate(ids)}
        groups = np.asarray([index[v['node_id']] for v in vs])
        bynode = {nid: np.flatnonzero(groups == i) for nid, i in index.items()}
        probe_cache = {}
        def probe(nid):
            if nid not in probe_cache:
                vi = bynode[nid]
                scores = vec[vi] @ vec.T
                maxima = np.full(len(ids), -np.inf, dtype=np.float32)
                np.maximum.at(maxima, groups, scores.max(axis=0))
                maxima[index[nid]] = -np.inf
                probe_cache[nid] = (vi, scores, maxima)
            return probe_cache[nid]
        probes = []
        for c in cases:
            if c['label'] != 'POSITIVE': continue
            a, b = c['A']['node_id'], c['B']['node_id']
            if a not in bynode or b not in bynode:
                probes.append(dict(case_id=c['suite_case_id'], missing_views=True)); continue
            ai, scores, maxima = probe(a)
            bj = bynode[b]
            local = scores[:, bj]
            i, j = np.unravel_index(local.argmax(), local.shape)
            score = float(local[i,j])
            _, _, back = probe(b)
            probes.append(dict(case_id=c['suite_case_id'], cosine=score,
                rank_from_a=1+int((maxima > score).sum()), rank_from_b=1+int((back > score).sum()),
                rank_semantics='Exact node-max cosine rank, excludes own node; ties share competition rank. Not RRF rank.',
                best_a=vs[int(ai[i])], best_b=vs[int(bj[j])]))
        jsonl(out / arm / 'cosine_probes.jsonl', probes)
    write(out / 'summary.json', dict(complete=True, matched_budget=budget, results=summaries,
        elapsed_seconds=time.monotonic()-started, new_embeddings=len(texts), reused_embedding_texts=len(cache)-len(texts)))
    write(out / 'case_coverage.json', detail)
    lines = ['# Text retrieval view comparison', '', 'Candidate coverage only; no new semantic graph or query evaluation.', '',
             '| Arm | Views | Initial positives /26 | Native pairs | Native positives | Matched positives |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for a in ARMS:
        s=summaries[a]
        lines.append(f"| {a} | {len(views[a])} | {s['initial']['POSITIVE_retrieved']} | {len(native[a])} | {s['native']['POSITIVE_retrieved']} | {s['matched']['POSITIVE_retrieved']} |")
    lines += ['',f'Identical matched budget: {budget}. Native hierarchy uses the unchanged routing/bucket/degree rules.',
              'Whole-text truncation and per-case best source views are saved separately. View-count changes affect competition; this is not a pure cosine-only ablation.']
    (out / 'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(read(out / 'summary.json'), flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','run'])
    parser.add_argument('--output',type=Path,default=OUT);args=parser.parse_args()
    (prepare if args.command=='prepare' else run)(args.output)
