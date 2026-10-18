#!/usr/bin/env python3
"""Replay 76411 retrieval and the preceding source-grounded verifier on current data."""
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import inspect
import itertools
import json
from pathlib import Path
import textwrap

import numpy as np

import run_hierarchical_edge_retrieval as hier
import run_traffic_relevance_graph as prior
from run_traffic_relevance_cpu import cpu_embed
from run_split_taxonomy_suite import SUITE, MODEL, create_llm
from run_typed_node_edges import catalog
from run_node_context_edges import ROOT, read, rows, write, jsonl, sha

OUT = ROOT / 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015'
SOURCES = {
    'traffic': ROOT / 'EvidenceNet/output/paper_relevance_urban_traffic_20261013/graph',
    'expanded': ROOT / 'EvidenceNet/output/article_bridge_expanded_v5_20261012',
}
FOUR = ROOT / 'EvidenceNet/output/split_taxonomy_current_suite_qwen_descriptions_v2_20261015'
SUPPORTED = {'METHOD_CORRESPONDENCE', 'DATASET_CORRESPONDENCE', 'MEASUREMENT_COMPARISON'}


def check(out):
    for p, h in read(out / 'manifest.json')['files'].items():
        if sha(p) != h:
            raise ValueError('Changed source/code: ' + p)


def previous_prompt_prefix():
    # Reuse the literal prompt of the preceding verifier, with no policy edits.
    tree = ast.parse(textwrap.dedent(inspect.getsource(prior.verify)))
    values = [n.value.left.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'prompt' for t in n.targets)
              and isinstance(n.value, ast.BinOp) and isinstance(n.value.left, ast.Constant)]
    if len(values) != 1:
        raise ValueError('Cannot uniquely identify frozen previous prompt')
    return values[0]


def prepare(out):
    from build_evidence_edge_review_suite import validate
    validate(SUITE)
    if (out / 'manifest.json').exists():
        check(out)
        return
    nodes, policies, original_sources = {}, {}, []
    fallback = []
    for collection, folder in SOURCES.items():
        source_policy = read(folder / 'eligibility.json')
        original_sources += [folder / 'units.jsonl', folder / 'eligibility.json']
        for n in rows(folder / 'units.jsonl'):
            nid = n['id']
            if nid in nodes:
                raise ValueError('Ambiguous duplicate node ID in combined corpus: ' + nid)
            n = json.loads(json.dumps(n)); n['source_collection'] = collection
            n['original_article_id'] = n.get('article_id')
            if not n.get('article_id'):
                # A page-local search bucket is not an inferred article or semantic edge.
                n['article_id'] = n['document'] + '::UNRESOLVED_PAGE_BUCKET::' + str(n['page'])
                fallback.append(nid)
            nodes[nid] = n; policies[nid] = source_policy[nid]
    # Full source corpus, never just the suite's selected candidate endpoints.
    jsonl(out / 'corpus_nodes.jsonl', nodes.values())
    write(out / 'corpus_policies.json', policies)
    jsonl(out / 'views.jsonl', hier.make_views(nodes, policies))
    cases = rows(SUITE / 'cases.jsonl')
    jsonl(out / 'evaluation/cases.jsonl', cases)
    jsonl(out / 'evaluation/four_tag_reference.jsonl', rows(FOUR / 'evaluation/reference.jsonl'))
    suite_nodes = {(n['source_collection'], n['id']): n for n in rows(SUITE / 'nodes.jsonl')}
    tasks = []
    for case in cases:
        if case['relation'] not in SUPPORTED:
            continue
        endpoints = [suite_nodes[case[k]['source_collection'], case[k]['node_id']] for k in ('A', 'B')]
        if int(hashlib.sha256(case['case_id'].encode()).hexdigest(), 16) % 2:
            endpoints.reverse()
        evidence, lookups, images = {}, {}, []
        for side, n in zip(('A', 'B'), endpoints):
            policy = dict(members=n['eligible_members'])
            public, lookup = catalog(n, policy, side, SUITE)
            for entry in public:
                if entry['kind'] == 'VISUAL':
                    images.append(str((SUITE / entry.pop('crop')).resolve()))
                    entry['image_index'] = len(images)
            evidence[side] = public; lookups[side] = lookup
        tasks.append(dict(task_id=case['case_id'],
                          endpoint_ids=[n['id'] for n in endpoints],
                          prompt=previous_prompt_prefix() + json.dumps(evidence, ensure_ascii=False),
                          images=images, lookups=lookups))
    assert len(tasks) == 45
    jsonl(out / 'verifier/inputs.jsonl', tasks)
    write(out / 'protocol.json', dict(
        nodes=len(nodes), documents=len({n['document'] for n in nodes.values()}),
        routing_buckets=len({n['article_id'] for n in nodes.values()}), unresolved_page_bucket_nodes=len(fallback),
        unresolved_node_ids=fallback, retrieval='Exact 76411 algorithm/default budgets on the full union corpus; whole-node dense baseline rebuilt on same corpus.',
        original_76411='Original six-paper candidates also rescored on supported cases only; unavailable endpoints are NOT counted as misses.',
        verification='45 fixed pairs, unchanged 75115 prompt/catalog/validator and 1800-token budget; original raw visual crops and parsed tables.',
        unsupported_cases=[c['case_id'] for c in cases if c['relation'] not in SUPPORTED],
        comparison='Native relation scores reported separately. Binary scheme comparison only where original requested-relation and provisional functional labels agree.',
        caveat='Overall system comparison, not a prompt-only ablation: taxonomy, schema, grounding and token budget differ. Development set, not independent expert gold.',
        labels_in_model_inputs=False, labels_used_in_retrieval=False))
    code = [Path(__file__), Path(hier.__file__), Path(prior.__file__),
            Path(__file__).with_name('run_traffic_relevance_cpu.py'),
            Path(__file__).with_name('run_typed_node_edges.py'),
            Path(__file__).with_name('run_fact_grounded_edges.py'),
            Path(__file__).with_name('run_node_context_edges.py'),
            Path(__file__).with_name('run_split_taxonomy_suite.py'),
            ROOT / 'EvidenceNet/evidence_graph/llm_client.py']
    files = [out / name for name in ('corpus_nodes.jsonl', 'corpus_policies.json', 'views.jsonl',
             'evaluation/cases.jsonl', 'evaluation/four_tag_reference.jsonl', 'verifier/inputs.jsonl', 'protocol.json')]
    files += original_sources + code + [SUITE / 'manifest.json', SUITE / 'nodes.jsonl', SUITE / 'cases.jsonl']
    files += [Path(p) for t in tasks for p in t['images']]
    write(out / 'manifest.json', {'files': {str(p.resolve()): sha(p) for p in files}})
    print(json.dumps(dict(nodes=len(nodes), views=len(rows(out / 'views.jsonl')), verifier_pairs=len(tasks))), flush=True)


def whole_node_candidates(nodes, vectors):
    ids = list(nodes)
    scores = vectors @ vectors.T
    grouped = defaultdict(list)
    for i, nid in enumerate(ids):
        grouped[nodes[nid]['document']].append(i)
    selected = {}
    for da, db in itertools.combinations_with_replacement(sorted(grouped), 2):
        same = da == db
        indices = itertools.combinations(grouped[da], 2) if same else itertools.product(grouped[da], grouped[db])
        candidates = sorted(((float(scores[i, j]), i, j) for i, j in indices), reverse=True)
        degree = Counter(); count = 0
        for score, i, j in candidates:
            if degree[i] >= (2 if same else 3) or degree[j] >= (2 if same else 3):
                continue
            a, b = sorted((ids[i], ids[j]))
            selected[a, b] = dict(source=a, target=b, similarity=score)
            degree[i] += 1; degree[j] += 1; count += 1
            if count >= (12 if same else 24):
                break
    return list(selected.values()), scores


def coverage(cases, candidates, supported_nodes=None):
    keys = {frozenset((p['source'], p['target'])) for p in candidates}
    evaluated, counts = [], Counter()
    for case in cases:
        ends = {case['A']['node_id'], case['B']['node_id']}
        if supported_nodes is not None and not ends <= supported_nodes:
            counts['unavailable_cases'] += 1
            continue
        hit = frozenset(ends) in keys
        counts[case['label'] + '_total'] += 1
        counts[case['label'] + '_retrieved'] += int(hit)
        evaluated.append(dict(task_id=case['case_id'], suite_case_id=case['suite_case_id'],
                              requested_relation=case['relation'], label=case['label'], retrieved=hit))
    counts['candidate_pairs'] = len(candidates)
    counts['candidate_nodes'] = len({p[k] for p in candidates for k in ('source', 'target')})
    return dict(counts), evaluated


def retrieval(out):
    check(out)
    import torch
    torch.set_num_threads(32)
    nodes = {n['id']: n for n in rows(out / 'corpus_nodes.jsonl')}
    policies = read(out / 'corpus_policies.json')
    views = rows(out / 'views.jsonl')
    vectors = np.asarray(cpu_embed([v['retrieval_text'] for v in views], hier.ENCODER), dtype=np.float32)
    np.save(out / 'view_vectors.npy', vectors)
    pool = hier.retrieve(views, vectors)
    articles, selected = hier.route_and_select(nodes, pool)
    jsonl(out / 'article_candidates.jsonl', articles)
    jsonl(out / 'hierarchical_candidates.jsonl', selected)
    jsonl(out / 'initial_pool.jsonl', pool.values())
    # Match the old whole-node embedding input policy, including all members of eligible nodes.
    eligible_nodes = {nid: n for nid, n in sorted(nodes.items()) if policies[nid]['eligible']}
    dense = np.asarray(cpu_embed(['\n'.join(m.get('text', '') for m in n['members'])
                                 for n in eligible_nodes.values()], hier.ENCODER), dtype=np.float32)
    np.save(out / 'whole_node_vectors.npy', dense)
    baseline, similarity = whole_node_candidates(eligible_nodes, dense)
    jsonl(out / 'whole_node_candidates.jsonl', baseline)
    # Global cosine at the same final pair count is an extra budget control, not the old policy.
    ii, jj = np.triu_indices(len(eligible_nodes), 1)
    order = np.argsort(-similarity[ii, jj], kind='stable')[:len(selected)]
    ids = list(eligible_nodes)
    equal_budget = [dict(source=ids[int(ii[k])], target=ids[int(jj[k])], similarity=float(similarity[ii[k], jj[k]])) for k in order]
    jsonl(out / 'global_cosine_equal_budget.jsonl', equal_budget)
    cases = rows(out / 'evaluation/cases.jsonl')
    summary, details = {}, {}
    for name, candidates in [('hierarchical_76411_replay', selected), ('whole_node_previous_policy', baseline),
                              ('global_cosine_equal_budget_control', equal_budget), ('initial_pool_upper_bound_not_final', list(pool.values()))]:
        summary[name], details[name] = coverage(cases, candidates)
    old_source = ROOT / 'EvidenceNet/output/hierarchical_edge_retrieval_v1_20261014'
    old_nodes = {n['id'] for n in rows(SOURCES['traffic'] / 'units.jsonl')}
    for name, path in [('original_76411_six_papers', old_source / 'node_candidates.jsonl'),
                       ('original_dense_six_papers', SOURCES['traffic'] / 'semantic_candidates.jsonl')]:
        summary[name], details[name] = coverage(cases, rows(path), old_nodes)
    write(out / 'retrieval_summary.json', dict(complete=True, results=summary,
         interpretation='Candidate inclusion only, not semantic precision. Policies have different budgets; equal-budget control is separate. Unresolved page buckets are search allocation, not confirmed article segmentation.'))
    write(out / 'retrieval_cases.json', details)
    print(json.dumps(summary), flush=True)
    report(out)


def verifier(out):
    check(out)
    import torch
    torch.set_num_threads(32)
    tasks = rows(out / 'verifier/inputs.jsonl')
    existing = rows(out / 'verifier/predictions.jsonl') if (out / 'verifier/predictions.jsonl').exists() else []
    if [p['task_id'] for p in existing] != [t['task_id'] for t in tasks[:len(existing)]]:
        raise ValueError('Checkpoint mismatch')
    model = create_llm(dict(provider='transformers', model=str(MODEL), dtype='bfloat16',
                           device_map='cpu', require_cuda=False, enable_thinking=False))
    for t in tasks[len(existing):]:
        try:
            response = prior.call_json(model, t['prompt'], t['images'], lambda v: prior.validate(v, t['lookups']), 1800)
        except Exception as exc:
            response = dict(valid=False, bound=None, errors=[str(exc)], attempts=[])
        existing.append(dict(task_id=t['task_id'], response=response))
        jsonl(out / 'verifier/predictions.jsonl', existing)
        report(out)
        print(json.dumps(dict(processed=len(existing), total=len(tasks), valid=response['valid'],
                              status=(response.get('bound') or {}).get('status'))), flush=True)


def binary_metrics(decisions, references):
    c = Counter()
    for key, truth in references.items():
        if key not in decisions:
            c['missing'] += 1; continue
        pred = decisions[key]
        if pred is None:
            c['invalid_or_uncertain'] += 1; continue
        c['tp' if truth and pred else 'fn' if truth else 'fp' if pred else 'tn'] += 1
    tp, fp, fn, tn = [c[k] for k in ('tp', 'fp', 'fn', 'tn')]
    return dict(c, total=len(references), precision_valid_only=tp / (tp + fp) if tp + fp else None,
                recall_valid_only=tp / (tp + fn) if tp + fn else None,
                correct=len([k for k, v in references.items() if decisions.get(k) is v]))


def report(out):
    cases = rows(out / 'evaluation/cases.jsonl')
    refs = {r['task_id']: r for r in rows(out / 'evaluation/four_tag_reference.jsonl')}
    old_rows = rows(out / 'verifier/predictions.jsonl') if (out / 'verifier/predictions.jsonl').exists() else []
    old = {r['task_id']: None if not r['response']['valid'] or r['response']['bound']['status'] == 'UNCERTAIN'
           else r['response']['bound']['status'] == 'ACCEPT' for r in old_rows}
    new_rows = rows(FOUR / 'predictions.jsonl') if (FOUR / 'predictions.jsonl').exists() else []
    new = {r['task_id']: None if not r['valid'] else r['semantic']['relation'] != 'REJECT_UNCERTAIN' for r in new_rows}
    native = {c['case_id']: c['label'] == 'POSITIVE' for c in cases
              if c['relation'] in SUPPORTED and c['label'] in ('POSITIVE', 'NEGATIVE')}
    common = {c['case_id']: native[c['case_id']] for c in cases if c['case_id'] in native
              and refs[c['case_id']]['semantic_status'] != 'UNRESOLVED'
              and native[c['case_id']] == (refs[c['case_id']]['allowed_semantic_readings'][0]['relation'] != 'REJECT_UNCERTAIN')}
    joint = {key: truth for key, truth in common.items() if key in old and key in new}
    result = dict(previous_processed=len(old_rows), previous_total=45,
                  four_tag_processed=len(new_rows), four_tag_total=58,
                  previous_native_reference=binary_metrics(old, native),
                  agreeing_reference_cases=len(common),
                  common_scope_previous=binary_metrics(old, common),
                  common_scope_four_tag=binary_metrics(new, common),
                  jointly_processed_cases=len(joint),
                  jointly_processed_previous=binary_metrics(old, joint),
                  jointly_processed_four_tag=binary_metrics(new, joint),
                  previous_statuses=dict(Counter(r['response']['bound']['status'] if r['response']['valid']
                      else 'INVALID' for r in old_rows)),
                  caveat='Compare existence on agreeing-reference cases only; taxonomies and input representations differ. Accepted prose still requires source review.')
    write(out / 'verification_comparison.json', result)
    lines = ['# Previous edge schemes vs current suite', '',
             'This report separates retrieval from fixed-pair verification. Candidate inclusion is not an accepted edge.', '',
             '## Verification', '', '```json', json.dumps(result, indent=2), '```', '']
    if (out / 'retrieval_summary.json').exists():
        lines += ['## Retrieval', '', '```json', json.dumps(read(out / 'retrieval_summary.json'), indent=2), '```', '']
    lines += ['No overall winner is asserted from unequal scopes, incomplete runs, or acceptance rates. '
              'Current references are provisional development annotations, not expert blind-test gold.']
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'retrieval', 'verifier', 'report'])
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.output)
    else:
        check(args.output)
        globals()[args.command](args.output)
