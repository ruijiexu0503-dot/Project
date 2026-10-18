#!/usr/bin/env python3
"""Source-addressed article routing and a matched node-context pilot."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import shutil

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, check, tokens, scope
from run_typed_node_edges import allowed_members, entities, catalog, request_targets
from run_fact_grounded_edges import call_json, digest

SOURCE = ROOT/'EvidenceNet/output/fact_grounded_edges_v1_20261012'
TYPED = ROOT/'EvidenceNet/output/typed_node_edges_v1_20261012'
VECTORS = ROOT/'EvidenceNet/output/node_context_edges_v2_20261011'
RELATIONS = {'SAME_EVENT', 'SAME_PROJECT', 'CAPTION_FOR', 'DEFINITION_TO_INSTANCE', 'ORGANIZATION_CONTEXT'}
SPEC = '''Choose only a source-supported relationship between the TWO target evidence nodes.
SAME_EVENT: both nodes contain concrete content about the same specific occurrence; shared organization/instrument is insufficient.
SAME_PROJECT: both nodes contain concrete content about the same named project; project participation may appear in qualifiers, not just the grammatical subject.
CAPTION_FOR: target text is an actual caption of the original visual at the other target; caption to visual.
DEFINITION_TO_INSTANCE: one target contains an actual definition or a substantive category explanation, and the other explicitly demonstrates/applies that category. A bare heading or related-work topic list is insufficient.
ORGANIZATION_CONTEXT: the only link is a shared institution/instrument; return INDEX_ONLY, not ACCEPT.
For other possible relationships return UNCERTAIN with relation_type NONE and explain that the relationship falls outside this pilot. If no specific supported bridge exists, REJECT.
Portrait style, animal appearance, broad subject/task similarity and co-membership in an article cannot prove these relationships.
Optional article context can resolve a referent or explain scope, but cannot supply a missing assertion at either target. A bare CMS logo/name is not a concrete event claim.
Do not borrow the other target's content. Unknown identity or insufficient support means UNCERTAIN.
For ACCEPT state the specific local content at each target and the concrete bridge. Select only target evidence IDs as primary anchors. Context IDs never substitute for target anchors.'''


def source_snippets(node, policy, out):
    _, lookup = catalog(node, policy, 'CTX', out)
    return [{'node_id': node['id'], 'document': node['document'], 'page': node['page'],
             **anchor} for anchor in lookup.values() if anchor['kind'] == 'TEXT']


def profiles(nodes, policies, out):
    groups = defaultdict(list)
    for node in nodes.values():
        if node.get('article_id') and policies[node['id']]['eligible']:
            groups[node['article_id']].append(node)
    result = []
    for aid, members in sorted(groups.items()):
        ordered = sorted(members, key=lambda n: (n['page'], n.get('min_order') or 0, n['id']))
        titles = sorted({n['article_title'] for n in ordered if n.get('article_title')})
        snippets = [s for n in ordered for s in source_snippets(n, policies[n['id']], out)]
        result.append({'article_id': aid, 'document': ordered[0]['document'],
                       'node_ids': [n['id'] for n in ordered], 'titles': titles,
                       'title_provenance': 'inherited segmentation metadata; not a source quotation',
                       'assignment_statuses': sorted({n.get('assignment_status', '') for n in ordered}),
                       'sampled_pages': sorted({n['page'] for n in ordered}),
                       'coverage': 'only available sampled pages, not a complete article',
                       'source_snippets': snippets})
    return result


def pair_context(pair, nodes, article_profiles):
    excluded = {pair['source'], pair['target']}
    result = {}
    for label, key in [('A', 'source'), ('B', 'target')]:
        node = nodes[pair[key]]; article = article_profiles.get(node.get('article_id'))
        if article is None:
            result[label] = {'article_id': None, 'status': 'ARTICLE_UNRESOLVED', 'snippets': []}
            continue
        query = set(tokens(' '.join(m.get('text', '') for m in node['members'] if m['kind'] == 'atom')))
        candidates = [s for s in article['source_snippets'] if s['node_id'] not in excluded]
        def rank(s):
            other = nodes[s['node_id']]
            heading = any(m['id'] == s['member_id'] and m.get('role') in {'title', 'heading', 'headline', 'sec_title'} for m in other['members'])
            overlap = len(query & set(tokens(s['quote']))) / max(len(query), 1)
            local = other['page'] == node['page']
            distance = abs((other.get('min_order') or 0) - (node.get('min_order') or 0)) if local else 10000
            return (-int(heading), -overlap, -int(local), distance, s['node_id'], s['char_start'])
        chosen = []; seen = set()
        for snippet in sorted(candidates, key=rank):
            if snippet['node_id'] in seen: continue
            seen.add(snippet['node_id']); chosen.append(snippet)
            if len(chosen) == 4: break
        result[label] = {'article_id': article['article_id'], 'titles': article['titles'],
                         'title_provenance': article['title_provenance'], 'status': 'SAMPLED_ARTICLE_CONTEXT',
                         'assignment_statuses': article['assignment_statuses'],
                         'snippets': [{**s, 'id': f'CTX:{label}:{i:03d}'} for i, s in enumerate(chosen)]}
    return result


def node_vectors(nodes, policies, views, matrix):
    import numpy as np
    if len(views) != len(matrix): raise ValueError('view_vector_coverage')
    by_node = defaultdict(list)
    allowed = {nid: {(m['member_id'], m['kind']) for m in policy['members'] if m['eligible']}
               for nid, policy in policies.items()}
    for i, view in enumerate(views):
        nid = view['node_id']
        if view['kind'] not in {'source_text', 'generated_description'}: raise ValueError('unknown_view_kind')
        kind = 'visual' if view['kind'] == 'generated_description' else 'atom'
        if nid in nodes and (view['member_id'], kind) in allowed[nid]:
            # Check cached retrieval source against immutable node text/crop.
            member = next(m for m in nodes[nid]['members'] if m['id'] == view['member_id'] and m['kind'] == kind)
            if kind == 'atom' and member['text'][view['char_start']:view['char_end']] != view['text']:
                raise ValueError('view_source_mismatch:'+view['view_id'])
            if kind == 'visual' and member.get('crop') != view.get('crop'):
                raise ValueError('visual_view_crop_mismatch:'+view['view_id'])
            by_node[nid].append(matrix[i])
    ids = sorted(by_node)
    pooled = np.asarray([np.mean(by_node[nid], axis=0) for nid in ids])
    pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
    return ids, pooled


def route_candidates(nodes, policies, articles, views, matrix, budget=12):
    import numpy as np
    ids, vectors = node_vectors(nodes, policies, views, matrix)
    index = {nid: i for i, nid in enumerate(ids)}; similarity = vectors @ vectors.T
    aids = [a['article_id'] for a in articles if any(n in index for n in a['node_ids'])]
    by_article = {a['article_id']: a for a in articles}
    av = np.asarray([np.mean([vectors[index[n]] for n in by_article[aid]['node_ids'] if n in index], axis=0) for aid in aids]) if aids else np.zeros((0, vectors.shape[1]))
    av /= np.maximum(np.linalg.norm(av, axis=1, keepdims=True), 1e-12)
    scores = av @ av.T; article_neighbors = {}; article_candidates = []
    entity_sets = {aid: {e['key'] for nid in by_article[aid]['node_ids'] for e in entities(nodes[nid], policies[nid])} for aid in aids}
    for i, aid in enumerate(aids):
        neighbors = set()
        for same_document, limit in [(False, 3), (True, 2)]:
            candidates = [j for j, other in enumerate(aids) if j != i and
                          (by_article[other]['document'] == by_article[aid]['document']) == same_document]
            dense = sorted(candidates, key=lambda j: (-float(scores[i, j]), aids[j]))[:limit]
            entity = sorted([j for j in candidates if entity_sets[aid] & entity_sets[aids[j]]],
                            key=lambda j: (-len(entity_sets[aid] & entity_sets[aids[j]]), -float(scores[i, j]), aids[j]))[:2]
            for j in sorted(set(dense + entity)):
                neighbors.add(aids[j]);article_candidates.append({'source_article': aid, 'target_article': aids[j],
                    'cosine': float(scores[i, j]), 'routes': (['article_dense'] if j in dense else []) + (['article_entity_index'] if j in entity else []),
                    'shared_entity_keys': sorted(entity_sets[aid] & entity_sets[aids[j]]),
                    'status': 'CANDIDATE_ONLY'})
        article_neighbors[aid] = neighbors
    selections = []; pair_pool = {}
    for i, nid in enumerate(ids):
        # Scope quota guarantees both intra-document and cross-document routes.
        direct = []; combined = []
        for same_document in [False, True]:
            ranked = [ids[j] for j in np.argsort(-similarity[i], kind='stable') if j != i and
                      (nodes[ids[j]]['document'] == nodes[nid]['document']) == same_document]
            quota = budget // 2
            direct.extend(ranked[:quota])
            allowed_articles = article_neighbors.get(nodes[nid].get('article_id'), set())
            hierarchical = [other for other in ranked if nodes[other].get('article_id') in allowed_articles]
            chosen = ranked[:quota // 2]
            for other in hierarchical:
                if other not in chosen: chosen.append(other)
                if len(chosen) >= quota: break
            for other in ranked:
                if len(chosen) >= quota: break
                if other not in chosen: chosen.append(other)
            combined.extend(chosen)
        selections.append({'source': nid, 'direct_targets': direct, 'combined_targets': combined})
        for arm, selected in [('direct', direct), ('combined', combined)]:
            for target in selected:
                key = tuple(sorted((nid, target)))
                record = pair_pool.setdefault(key, {'source': key[0], 'target': key[1], 'scope': scope(nodes[key[0]], nodes[key[1]]),
                      'routes': [], 'score': float(similarity[i, index[target]])})
                if arm not in record['routes']: record['routes'].append(arm)
    return article_candidates, selections, list(pair_pool.values()), len(ids)


def prepare(out, source):
    import numpy as np
    if out.exists(): raise ValueError('Use a fresh experiment directory')
    check(source)
    for name, h in read(source/'verification_manifest.json')['artifact_sha256'].items():
        if sha(source/name) != h: raise ValueError('changed_previous_artifact:'+name)
    out.mkdir(parents=True)
    for name in ['units.jsonl', 'eligibility.json', 'reading_edges.jsonl']:
        shutil.copy2(source/name, out/name)
    # All existing provenance-relative crops remain addressable without copying.
    (out/'assets').symlink_to((source/'assets').resolve(), target_is_directory=True)
    nodes = {n['id']: n for n in rows(out/'units.jsonl')}; policies = read(out/'eligibility.json')
    articles = profiles(nodes, policies, out); jsonl(out/'article_profiles.jsonl', articles)
    views = rows(VECTORS/'views.jsonl');matrix = np.load(VECTORS/'view_vectors.npy')
    article_pairs, selections, candidates, count = route_candidates(nodes, policies, articles, views, matrix)
    jsonl(out/'article_candidates.jsonl', article_pairs);jsonl(out/'routing_selections.jsonl', selections)
    jsonl(out/'route_candidates.jsonl', candidates)
    old_queue = rows(source/'verification_queue.jsonl');old_map = {p['pair_id']: p for p in old_queue}
    required = ['TYPED_00270','TYPED_00558','TYPED_03527','TYPED_05161','TYPED_05813','TYPED_06144',
                'TYPED_00808','TYPED_01886','TYPED_04439','TYPED_04478','TYPED_05222','TYPED_05226',
                'TYPED_05269','TYPED_05306','TYPED_05320','TYPED_06363','TYPED_07990','TYPED_04532',
                'TYPED_08362','TYPED_08365','TYPED_03252','TYPED_07872','TYPED_04966','TYPED_08676']
    selected = {}; rng = random.Random(20261012)
    def add(pair, cohort):
        key = tuple(sorted((pair['source'], pair['target'])))
        if key not in selected: selected[key] = {**pair, 'pilot_cohort': cohort}
    for pid in required: add(old_map[pid], 'known_case_regression')
    remaining = [p for p in old_queue if tuple(sorted((p['source'], p['target']))) not in selected]
    rng.shuffle(remaining)
    for pair in sorted(remaining, key=lambda p: (not bool(nodes[p['source']].get('article_id') and nodes[p['target']].get('article_id')), p['scope'])):
        if len(selected) >= 48: break
        add(pair, 'frozen_development_sample')
    previously_judged = {tuple(sorted((p['source'], p['target']))) for p in rows(TYPED/'verification_queue.jsonl')}
    fresh = [p for p in candidates if tuple(sorted((p['source'], p['target']))) not in previously_judged]
    buckets = defaultdict(list)
    for pair in fresh: buckets[pair['scope']].append(pair)
    for bucket in buckets.values(): rng.shuffle(bucket)
    for family, quota in [('cross_document', 10), ('intra_article', 2), ('cross_article', 2), ('same_document_article_unresolved', 2)]:
        for pair in buckets[family][:quota]:
            add({**pair, 'pair_id': f'ARTICLE_NEW_{len(selected):03d}', 'relation_type': 'UNBOUND'}, 'previously_unjudged_sample')
    queue = list(selected.values());jsonl(out/'verification_queue.jsonl', queue)
    article_index = {a['article_id']: a for a in articles}
    contexts = {p['pair_id']: pair_context(p, nodes, article_index) for p in queue}
    write(out/'pair_contexts.json', contexts)
    direct_keys = {tuple(sorted((r['source'], t))) for r in selections for t in r['direct_targets']}
    combined_keys = {tuple(sorted((r['source'], t))) for r in selections for t in r['combined_targets']}
    coverage = []
    for pair in old_queue:
        key = tuple(sorted((pair['source'], pair['target'])))
        coverage.append({'pair_id': pair['pair_id'], 'scope': pair['scope'],
                         'direct_candidate': key in direct_keys, 'combined_candidate': key in combined_keys,
                         'both_articles_known': all(nodes[pair[k]].get('article_id') for k in ['source','target']),
                         'review_label': 'not assigned; old model decisions are not ground truth'})
    jsonl(out/'routing_regression.jsonl', coverage)
    summary = {'original_nodes': len(nodes), 'eligible_nodes': sum(p['eligible'] for p in policies.values()),
        'article_units': len(articles), 'article_unresolved_nodes': sum(not n.get('article_id') for n in nodes.values()),
        'routed_nodes': count, 'article_candidate_proposals': len(article_pairs),
        'direct_unique_pairs': len(direct_keys), 'combined_unique_pairs': len(combined_keys),
        'outgoing_budget_per_node': 12, 'queue': len(queue), 'queue_cohorts': dict(Counter(p['pilot_cohort'] for p in queue)),
        'queue_scopes': dict(Counter(p['scope'] for p in queue)),
        'context_available_pairs': sum(any(c[k]['snippets'] for k in ['A','B']) for c in contexts.values()),
        'known_queue_candidate_presence': {'direct': sum(c['direct_candidate'] for c in coverage), 'combined': sum(c['combined_candidate'] for c in coverage)},
        'candidate_presence_is_not_positive_recall': True, 'production_modified': False, 'retrieval_quality_evaluated': False}
    write(out/'routing_summary.json', summary)
    files = ['units.jsonl','eligibility.json','reading_edges.jsonl','article_profiles.jsonl','article_candidates.jsonl',
             'routing_selections.jsonl','route_candidates.jsonl','verification_queue.jsonl','pair_contexts.json']
    code = ['run_article_context_pilot.py','run_fact_grounded_edges.py','run_typed_node_edges.py',
            'run_node_context_edges.py','run_own_corpus_edges.py','verify_node_context_v3.py',
            'node_context_policy.py','node_context_coreference.py']
    (out/'code_snapshot').mkdir()
    for name in code: shutil.copy2(Path(__file__).parent/name, out/'code_snapshot'/name)
    manifest = read(source/'manifest.json')
    manifest.update(experiment='article_context_pilot_v1', source_experiment=str(source.resolve()),
        snapshot_files={name: sha(out/name) for name in files},
        code_sha256={name: sha(out/'code_snapshot'/name) for name in code},
        model=str(ROOT/'external/models/Qwen3.5-35B-A3B'),
        embedding_cache={str(VECTORS/name): sha(VECTORS/name) for name in ['views.jsonl','view_vectors.npy']},
        design='matched node pairs, limited relation spec, target originals; article context is the only arm difference',
        development_sample=True, independent_human_evaluation=False)
    write(out/'manifest.json', manifest);print(json.dumps(summary), flush=True)


def validate(value, lookups, context):
    if not isinstance(value, dict) or value.get('status') not in {'ACCEPT','REJECT','UNCERTAIN','INDEX_ONLY'}:
        raise ValueError('status_invalid')
    if not isinstance(value.get('reason'), str) or not value['reason'].strip(): raise ValueError('reason_required')
    context_ids = value.get('context_ids', [])
    allowed = {s['id'] for c in context.values() for s in c['snippets']}
    if not isinstance(context_ids, list) or any(not isinstance(i, str) or i not in allowed for i in context_ids):
        raise ValueError('context_id_not_supplied')
    if value['status'] not in {'ACCEPT','INDEX_ONLY'}: return {'anchors': {}, 'context_ids': context_ids}
    kind = value.get('relation_type')
    if kind not in RELATIONS: raise ValueError('relation_type_invalid')
    if (kind == 'ORGANIZATION_CONTEXT') != (value['status'] == 'INDEX_ONLY'): raise ValueError('organization_index_only')
    direction = value.get('direction')
    if kind in {'SAME_EVENT','SAME_PROJECT','ORGANIZATION_CONTEXT'} and direction != 'SYMMETRIC': raise ValueError('symmetric_required')
    if kind in {'CAPTION_FOR','DEFINITION_TO_INSTANCE'} and direction not in {'A_TO_B','B_TO_A'}: raise ValueError('directed_required')
    bound = {}
    for label in ['A','B']:
        suffix = label.lower(); refs = value.get('anchors_'+suffix)
        if not isinstance(refs, list) or not refs or len(refs) > 4 or any(not isinstance(i, str) or i not in lookups[label] for i in refs):
            raise ValueError('anchors_must_be_local_id_array')
        if len(set(refs)) != len(refs): raise ValueError('duplicate_anchor')
        if not isinstance(value.get('local_content_'+suffix), str) or len(value['local_content_'+suffix].strip()) < 8:
            raise ValueError('local_content_required')
        if any(lookups[label][i]['kind'] == 'VISUAL' for i in refs):
            if not isinstance(value.get('observation_'+suffix), str) or len(value['observation_'+suffix].strip()) < 8:
                raise ValueError('visual_observation_required')
        bound[label] = [{**lookups[label][i], 'id': i} for i in refs]
    if kind == 'CAPTION_FOR':
        src, dst = ('A','B') if direction == 'A_TO_B' else ('B','A')
        if not any(a['kind'] == 'TEXT' for a in bound[src]) or not any(a['kind'] == 'VISUAL' for a in bound[dst]):
            raise ValueError('caption_text_to_visual_required')
    return {'anchors': bound, 'context_ids': context_ids}


def judge(model, pair, nodes, policy, out, context):
    targets, lookups, images = request_targets(pair, nodes, policy, out)
    schema = {'status':'ACCEPT|REJECT|UNCERTAIN|INDEX_ONLY', 'relation_type':'one allowed type, or NONE',
        'direction':'A_TO_B|B_TO_A|SYMMETRIC; NONE for no edge', 'reason':'specific local content and bridge',
        'anchors_a':['one or more actual A target IDs; empty for no edge'],
        'anchors_b':['one or more actual B target IDs; empty for no edge'],
        'local_content_a':'content actually present at target A', 'local_content_b':'content actually present at target B',
        'observation_a':'visible original details if visual used', 'observation_b':'visible original details if visual used',
        'context_ids':['only supplied CTX IDs used; empty if none']}
    inputs = {'targets': targets, 'article_context': context}
    prompt = SPEC+'\nReturn JSON with this schema: '+json.dumps(schema)+'\n'+json.dumps(inputs, ensure_ascii=False)
    record = call_json(model, prompt, images, lambda v: validate(v, lookups, context), 1100)
    return {**record, 'pair': pair, 'context': context,
            'input_sha256': digest({'inputs': inputs, 'lookups': lookups, 'spec': SPEC}),
            'status': record['value']['status'] if record['valid'] else 'FORMAT_PENDING'}


def report(out):
    queue = rows(out/'verification_queue.jsonl'); comparison = []
    for pair in queue:
        row = {'pair': pair}
        for arm in ['without_context','with_context']:
            path = out/arm/f'{pair["pair_id"]}.json'
            row[arm] = read(path) if path.exists() else {'status':'NOT_RUN','valid':False}
        comparison.append(row)
    jsonl(out/'paired_comparison.jsonl', comparison)
    accepted = []; index_only = []
    for r in comparison:
        decision = r['with_context']
        if decision.get('valid') and decision['status'] in {'ACCEPT','INDEX_ONLY'}:
            record = {'id': r['pair']['pair_id'], 'source': r['pair']['source'], 'target': r['pair']['target'],
                'scope': r['pair']['scope'], 'type': decision['value']['relation_type'],
                'direction': decision['value']['direction'], 'reason': decision['value']['reason'],
                'anchors': decision['bound']['anchors'], 'context_ids': decision['bound']['context_ids'],
                'status': 'MODEL_ACCEPTED_REQUIRES_SOURCE_REVIEW'}
            (accepted if decision['status'] == 'ACCEPT' else index_only).append(record)
    jsonl(out/'semantic_edges.jsonl', accepted);jsonl(out/'index_relations.jsonl', index_only)
    nodes = {n['id']: n for n in rows(out/'units.jsonl')}; aggregates = defaultdict(list)
    for edge in accepted:
        a, b = nodes[edge['source']].get('article_id'), nodes[edge['target']].get('article_id')
        if a and b and a != b: aggregates[tuple(sorted((a,b)))].append(edge['id'])
    jsonl(out/'article_edges.jsonl', [{'source': a, 'target': b, 'supporting_edge_ids': ids,
            'status': 'AGGREGATED_MODEL_ACCEPTED_REQUIRES_SOURCE_REVIEW'} for (a,b), ids in sorted(aggregates.items())])
    summary = {'queue': len(queue), 'routing': read(out/'routing_summary.json'),
        'statuses': {arm: dict(Counter(r[arm]['status'] for r in comparison)) for arm in ['without_context','with_context']},
        'transitions': dict(Counter(r['without_context']['status']+' -> '+r['with_context']['status'] for r in comparison)),
        'both_valid': sum(r['without_context']['valid'] and r['with_context']['valid'] for r in comparison),
        'complete': all(r[arm]['status'] != 'NOT_RUN' for r in comparison for arm in ['without_context','with_context']),
        'semantic_edges': len(accepted), 'article_edges': len(aggregates),
        'retrieval_quality_evaluated': False, 'independent_human_evaluation': False, 'production_modified': False}
    write(out/'summary.json', summary);print(json.dumps(summary), flush=True)


def run(out):
    from run_own_corpus_edges import llm
    check(out); manifest = read(out/'manifest.json')
    for name, h in manifest['code_sha256'].items():
        if sha(Path(__file__).parent/name) != h: raise ValueError('experiment_code_changed:'+name)
    nodes = {n['id']: n for n in rows(out/'units.jsonl')}; policy = read(out/'eligibility.json')
    contexts = read(out/'pair_contexts.json'); queue = rows(out/'verification_queue.jsonl');model = llm()
    for i, pair in enumerate(queue):
        # Alternate order; both arms use deterministic decoding and the same spec.
        arms = ['without_context','with_context'] if i % 2 == 0 else ['with_context','without_context']
        for arm in arms:
            path = out/arm/f'{pair["pair_id"]}.json'
            if path.exists(): continue
            context = contexts[pair['pair_id']] if arm == 'with_context' else {}
            decision = judge(model, pair, nodes, policy, out, context);write(path, decision)
            print(json.dumps({'pair': i+1, 'total': len(queue), 'arm': arm, 'status': decision['status']}), flush=True)
    write(out/'verification_manifest.json', {'complete': True,
        'artifact_sha256': {str(p.relative_to(out)): sha(p) for arm in ['without_context','with_context'] for p in sorted((out/arm).glob('*.json'))}})
    report(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare','run','report'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=SOURCE)
    args = parser.parse_args()
    if args.stage == 'prepare': prepare(args.output, args.source)
    else: globals()[args.stage](args.output)
