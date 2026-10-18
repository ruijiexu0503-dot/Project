#!/usr/bin/env python3
"""Staged alias resolution, independent evidence binding, and article-first routing.

Original v1 artifacts are immutable inputs. Weak node edges are derived from
independently verified bindings; they never assert entailment or numerical equality.
"""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import json
import random
import re
import shutil

from run_article_bridge_pilot import DEFAULT as SOURCE, checked, cached_call, CONTENT_ROLES
from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, tokens
from run_typed_node_edges import catalog, allowed_members
from run_article_context_pilot import node_vectors, VECTORS
from run_fact_grounded_edges import digest

DEFAULT = ROOT / 'EvidenceNet/output/article_bridge_binding_v2_20261012'
ASPECTS = {'detection_significance', 'parameter_estimation', 'gravity_test', 'instrument_calibration',
           'project_goals', 'project_components', 'project_partners', 'application_results', 'other'}
BINDING_STATES = {'SUPPORTED', 'BACKGROUND', 'MENTION_ONLY', 'UNRESOLVED', 'NOT_ABOUT_SUBJECT'}


def alias_base(name):
    name = ' '.join(name.casefold().split())
    name = re.sub(r'^the\s+', '', name)
    return re.sub(r'\s+project$', '', name)


def edit_one(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i+1:] == a for i in range(len(b)))


def alias_candidates(groups):
    result = []
    for a, b in combinations(groups, 2):
        if a['kind'] != b['kind']:
            continue
        aa, bb = alias_base(a['name']), alias_base(b['name'])
        same_article = a['article_id'] == b['article_id']
        # Fuzzy spelling is only proposed inside a confirmed article. Even exact
        # cross-article names require contextual identity verification.
        if aa == bb or (same_article and a['kind'] == 'PROJECT' and min(len(aa), len(bb)) >= 6 and edit_one(aa, bb)):
            result.append({'alias_pair_id': 'ALIAS_' + digest([a['group_id'], b['group_id']])[:12],
                           'source_group': a['group_id'], 'target_group': b['group_id'],
                           'proposal_reason': 'normalized_name' if aa == bb else 'within_article_spelling_candidate'})
    return result


def canonicalize(groups, decisions):
    """Complete-link merge: uncertain/missing/different cross-pairs block merging."""
    states = {tuple(sorted((d['source_group'], d['target_group']))): d['status'] for d in decisions}
    clusters = [{g['group_id']} for g in groups]
    for key, status in sorted(states.items()):
        if status != 'SAME':
            continue
        a = next(c for c in clusters if key[0] in c)
        b = next(c for c in clusters if key[1] in c)
        if a is b:
            continue
        if all(states.get(tuple(sorted((x, y)))) == 'SAME' for x in a for y in b):
            a.update(b); clusters.remove(b)
    by_id = {g['group_id']: g for g in groups}
    subjects, mapping = [], {}
    for cluster in sorted(clusters, key=lambda c: sorted(c)):
        ids = sorted(cluster)
        sid = 'SUBJECT_' + digest(ids)[:12]
        names = sorted({by_id[g]['name'] for g in ids}, key=lambda n: (len(n), n))
        subjects.append({'subject_id': sid, 'kind': by_id[ids[0]]['kind'], 'display_name': names[0],
                         'source_spellings': names, 'group_ids': ids,
                         'alias_pair_ids': [d['alias_pair_id'] for d in decisions if d['status'] == 'SAME'
                                            and d['source_group'] in cluster and d['target_group'] in cluster]})
        mapping.update({g: sid for g in cluster})
    return subjects, mapping


def prepare(out):
    if out.exists():
        raise ValueError('fresh_output_required')
    checked(SOURCE)
    for name, fingerprint in read(SOURCE / 'audit/artifact_sha256.json').items():
        if sha(SOURCE / name) != fingerprint:
            raise ValueError('changed_v1_result:' + name)
    out.mkdir(parents=True)
    (out / 'assets').symlink_to((SOURCE / 'assets').resolve(), target_is_directory=True)
    names = ['units.jsonl', 'eligibility.json', 'articles.jsonl', 'unit_article_map.json', 'reading_edges.jsonl',
             'protected_intra_article_candidates.jsonl', 'asset_sha256.json', 'subject_mentions.jsonl',
             'context_bindings.jsonl', 'routing_selections.jsonl', 'node_edge_decisions.jsonl', 'verification_queue.jsonl',
             'previously_judged_pairs.json']
    for name in names:
        shutil.copy2(SOURCE / name, out / ('v1_' + name if name in {'subject_mentions.jsonl', 'context_bindings.jsonl',
            'routing_selections.jsonl', 'node_edge_decisions.jsonl', 'verification_queue.jsonl'} else name))
    groups = {}
    for mention in rows(out / 'v1_subject_mentions.jsonl'):
        key = (mention['article_id'], mention['subject_id'])
        g = groups.setdefault(key, {'group_id': 'G_' + digest(key)[:12], 'article_id': key[0],
                                  'literal_subject_id': key[1], 'kind': mention['kind'],
                                  'name': mention['source_mention'], 'mentions': []})
        g['mentions'].append(mention)
    groups = list(groups.values())
    jsonl(out / 'identity_groups.jsonl', groups)
    candidates = alias_candidates(groups)
    jsonl(out / 'alias_candidates.jsonl', candidates)
    # Prior model results and source audits are development inputs, never test truth.
    development = rows(out / 'v1_verification_queue.jsonl')
    seen = {tuple(sorted((p['source'], p['target']))) for p in development}
    for p in rows(SOURCE / 'audit/subject_only_candidate_review.jsonl'):
        key = tuple(sorted((p['source'], p['target'])))
        if key not in seen:
            development.append({'pair_id': 'AUDITED_' + digest(key)[:12], 'source': key[0], 'target': key[1]})
            seen.add(key)
    jsonl(out / 'development_pairs.jsonl', [{**p, 'cohort': 'previously_reviewed_development'} for p in development])
    shutil.copy2(SOURCE / 'audit/source_review.jsonl', out / 'previous_source_review.jsonl')
    # Probe negative bindings independently. These IDs come from frozen cases,
    # not from inspecting the next run's outputs.
    v1_pairs = {p['pair_id']: p for p in development}
    probes = [{'node_id': v1_pairs[pid]['source'], 'subject_kind': kind, 'subject_name': name,
               'case_id': pid, 'purpose': 'negative_binding_probe'} for pid, kind, name in [
              ('TYPED_05820', 'EVENT', 'GW150914'), ('TYPED_05882', 'EVENT', 'GW150914'),
              ('TYPED_00270', 'PROJECT', 'UMBRELLA')]]
    write(out / 'binding_probe_spec.json', probes)
    # Replay the status-policy issue without reclassifying model outputs as truth.
    conflicts = []
    for d in rows(out / 'v1_node_edge_decisions.jsonl'):
        if d['status'] == 'FORMAT_PENDING':
            response = read(SOURCE / 'calls' / ('verify_' + d['pair']['pair_id'] + '.json'))['response']
            conflicts.append({'pair_id': d['pair']['pair_id'], 'binding_coverage': 'MISSING',
                              'original_pipeline_status': d['status'], 'semantic_decision': response['value'].get('status'),
                              'json_parse_valid': True, 'original_status_policy_valid': False,
                              'source_evaluation': 'NOT_RECLASSIFIED_AS_CORRECT_NEGATIVE', 'errors': d['errors']})
    jsonl(out / 'status_protocol_replay.jsonl', conflicts)
    manifest = read(SOURCE / 'manifest.json')
    manifest.update(experiment='article_bridge_binding_v2', source_experiment=str(SOURCE),
        snapshot_files={p.name: sha(p) for p in out.iterdir() if p.is_file()},
        stages=['source_backed_alias_resolution', 'independent_node_subject_binding', 'article_first_routing'],
        budgets={'global_slots': 4, 'article_slots': 4, 'max_articles': 2, 'per_article': 2, 'fresh_pairs': 16},
        evaluation={'prior_cases': 'development only; no independent expert labels',
          'missing_binding': 'coverage status, never a semantic rejection',
          'edge_type': 'weak RELATED_VIA_SUBJECT only',
          'gates': ['no accepted source/identity errors on audit', 'preserve local candidates',
                    'report additions AND lost candidates', 'independent query evaluation required for retrieval claims']},
        limitations=['Reuse v1 mention discovery to isolate changes; does not repair all missing mentions',
                     'Dense/Jaccard ranking inherited unchanged for controlled comparison',
                     'No new independent subject clusters in this run'])
    manifest['code_sha256'][str(Path(__file__).resolve())] = sha(__file__)
    write(out / 'manifest.json', manifest)
    (out / 'code').mkdir()
    for path in manifest['code_sha256']:
        shutil.copy2(path, out / 'code' / Path(path).name)
    print(json.dumps({'groups': len(groups), 'alias_proposals': len(candidates), 'development_pairs': len(development),
                      'status_conflicts_replayed': len(conflicts)}), flush=True)


def resolve_aliases(model, out):
    groups = rows(out / 'identity_groups.jsonl'); by_id = {g['group_id']: g for g in groups}
    decisions = []
    for candidate in rows(out / 'alias_candidates.jsonl'):
        evidence = []
        for key in ['source_group', 'target_group']:
            g = by_id[candidate[key]]; anchors = []
            for mention in g['mentions']:
                if mention['content_anchor'] not in anchors:
                    anchors.append(mention['content_anchor'])
            evidence.append({'group_id': g['group_id'], 'kind': g['kind'], 'name': g['name'],
                             'article_id': g['article_id'], 'source_anchors': anchors[:4]})
        prompt = '''Determine whether these two literal mentions identify the SAME specific event or project.
Use only the original source anchors and context. Equal strings are not enough when contexts conflict.
A project, its platform/component, its institution and a related project remain distinct identities.
A leading 'the' or trailing 'project' can be a surface-form variation when context supports identity.
An OCR spelling variant can be SAME only with strong contextual evidence; otherwise UNCERTAIN.
Return {"status":"SAME|DIFFERENT|UNCERTAIN","reason":"source-based identity explanation"}.
''' + json.dumps(evidence, ensure_ascii=False)
        def validate(v):
            if not isinstance(v, dict):
                raise ValueError('alias_object_required')
            if v.get('status') not in {'SAME', 'DIFFERENT', 'UNCERTAIN'} or not isinstance(v.get('reason'), str) or not v['reason'].strip():
                raise ValueError('alias_schema')
            return v
        response = cached_call(model, out, candidate['alias_pair_id'], prompt, [], validate, 900)
        decisions.append({**candidate, 'status': response['bound']['status'] if response['valid'] else 'FORMAT_PENDING',
                          'decision': response['bound'], 'errors': response['errors'], 'evidence': evidence})
        jsonl(out / 'alias_decisions.jsonl', decisions)
    subjects, mapping = canonicalize(groups, decisions)
    jsonl(out / 'canonical_subjects.jsonl', subjects); write(out / 'group_subject_map.json', mapping)
    return subjects, mapping


def binding_queue(out, group_map):
    groups = rows(out / 'identity_groups.jsonl')
    mention_group = {m['binding_id']: g['group_id'] for g in groups for m in g['mentions']}
    pool = {}
    def add(nid, sid, purpose='content_index'):
        return pool.setdefault((nid, sid), {'binding_id': 'NB_' + digest([nid, sid])[:12], 'node_id': nid,
                    'subject_id': sid, 'direct_mentions': [], 'context_proposals': [], 'purposes': [purpose]})
    for g in groups:
        for m in g['mentions']:
            add(m['node_id'], group_map[g['group_id']])['direct_mentions'].append(m)
    for b in rows(out / 'v1_context_bindings.jsonl'):
        if b['status'] == 'SUPPORTED':
            sid = group_map[mention_group[b['context_binding_id']]]
            target = add(b['node_id'], sid)
            # Preserve multiple different sources, deduplicate exact references.
            proposal = {k: b[k] for k in ['context_binding_id', 'context_anchor', 'reference']}
            if not any(p['reference'] == proposal['reference'] for p in target['context_proposals']):
                target['context_proposals'].append(proposal)
    subjects = rows(out / 'canonical_subjects.jsonl')
    for probe in read(out / 'binding_probe_spec.json'):
        matching = [s for s in subjects if s['kind'] == probe['subject_kind'] and
                    any(alias_base(name) == alias_base(probe['subject_name']) for name in s['source_spellings'])]
        for subject in matching:
            q = add(probe['node_id'], subject['subject_id'], probe['purpose'])
            if probe['purpose'] not in q['purposes']:
                q['purposes'].append(probe['purpose'])
    queue = list(pool.values()); jsonl(out / 'binding_queue.jsonl', queue)
    return queue


def context_catalog(item, nodes, mapping):
    contexts = {}
    for proposal in item['context_proposals']:
        ref = proposal['reference']; source = ref['source']; target = item['node_id']
        if ref['target'] != target or mapping[source] != mapping[target]:
            raise ValueError('context_crosses_article_or_target')
        member = next(m for m in nodes[source]['members'] if m['kind'] == 'atom' and m['id'] == ref['source_member'])
        if member['text'][ref['source_start']:ref['source_end']] != ref['source_quote']:
            raise ValueError('context_reference_changed')
        anchor = proposal['context_anchor']
        if anchor['node_id'] != source:
            raise ValueError('context_anchor_owner')
        key = 'CTX:' + digest([source, anchor, ref])[:12]
        contexts[key] = {'context_id': key, 'source_node': source, 'target_node': target,
                         'source_article': mapping[source], 'target_article': mapping[target],
                         'anchor': anchor, 'reference': ref}
    return contexts


def validate_binding(v, lookup, contexts):
    if not isinstance(v, dict):
        raise ValueError('binding_object_required')
    if v.get('status') not in BINDING_STATES:
        raise ValueError('binding_status')
    if not isinstance(v.get('reason'), str):
        raise ValueError('binding_reason')
    local = v.get('local_evidence_ids'); used_context = v.get('context_ids')
    if not isinstance(local, list) or any(x not in lookup for x in local):
        raise ValueError('local_anchor_ownership')
    if not isinstance(used_context, list) or any(x not in contexts for x in used_context):
        raise ValueError('context_ownership')
    if v['status'] == 'SUPPORTED':
        if not local or v.get('aspect_type') not in ASPECTS:
            raise ValueError('supported_binding_requires_content')
        if any(lookup[x]['kind'] == 'VISUAL' for x in local) and (not isinstance(v.get('visual_observation'), str) or not v['visual_observation'].strip()):
            raise ValueError('visual_observation_required')
    return {**v, 'local_anchors': [lookup[x] for x in local],
            'context_sources': [contexts[x] for x in used_context]}


def verify_bindings(model, out, nodes, policies, mapping, subjects, queue):
    subject_map = {s['subject_id']: s for s in subjects}; results = []
    for item in queue:
        public, lookup = catalog(nodes[item['node_id']], policies[item['node_id']], 'LOCAL', out)
        lookup = {key: {**a, 'node_id': item['node_id'], 'article_id': mapping[item['node_id']]} for key, a in lookup.items()}
        images = []
        for entry in public:
            if entry['kind'] == 'VISUAL':
                images.append(str(out / entry.pop('crop'))); entry['image_index'] = len(images)
        contexts = context_catalog(item, nodes, mapping)
        subject = subject_map[item['subject_id']]
        prompt = '''Independently verify ONE evidence node's content about ONE proposed specific event/project.
No candidate partner node or desired edge is provided. Inspect all original local text and images.
SUPPORTED: this node has substantive content about this exact event/project. Different aspects are valid:
detection significance, parameter estimation, GR tests, calibration at that event, or project goals/components/partners.
BACKGROUND: generic methods, thresholds or design noise, even if the article discusses the event.
MENTION_ONLY: bare name/citation without substantive content. NOT_ABOUT_SUBJECT: source identifies a different subject.
UNRESOLVED: identity or local content cannot be established from the provided originals.
The proposed subject is a hypothesis, not evidence. Article co-membership alone never proves a binding.
Context can resolve only the supplied explicit within-article figure/table reference; never import context-only
measurements into local evidence. Keep source/detector frame, search-class conditions and uncertainties distinct.
Aliases have been checked separately; the original mention need not equal the canonical spelling.
Select LOCAL anchors for local content, and CTX IDs separately only if required for identity resolution.
Return {"status":"SUPPORTED|BACKGROUND|MENTION_ONLY|UNRESOLVED|NOT_ABOUT_SUBJECT",
"aspect_type":"detection_significance|parameter_estimation|gravity_test|instrument_calibration|project_goals|project_components|project_partners|application_results|other",
"local_evidence_ids":["LOCAL:T000"],"context_ids":[],"visual_observation":"visible content or empty",
"reason":"explain local binding without inventing facts or cross-article citations"}.
''' + json.dumps({'subject': subject, 'local_evidence': public, 'context': list(contexts.values())}, ensure_ascii=False)
        response = cached_call(model, out, item['binding_id'], prompt, images,
                               lambda v: validate_binding(v, lookup, contexts), 1300)
        results.append({'binding_id': item['binding_id'], 'node_id': item['node_id'], 'article_id': mapping[item['node_id']],
                        'subject_id': item['subject_id'], 'purposes': item['purposes'],
                        'status': response['bound']['status'] if response['valid'] else 'FORMAT_PENDING',
                        'decision': response['bound'], 'errors': response['errors'],
                        # Keep all eligible originals alongside selected anchors so
                        # abbreviated model observations cannot erase local qualifiers.
                        'original_local_catalog': list(lookup.values()),
                        'available_context_sources': list(contexts.values()),
                        'source_mention_ids': [m['binding_id'] for m in item['direct_mentions']]})
        jsonl(out / 'node_subject_bindings.jsonl', results)
    return results


def graph_binding(binding):
    # Diagnostic probes must not inject new subject assignments into the graph.
    return binding['status'] == 'SUPPORTED' and 'content_index' in binding.get('purposes', ['content_index'])


def navigation(bindings):
    index = defaultdict(lambda: defaultdict(list))
    for b in bindings:
        if graph_binding(b):
            index[b['subject_id']][b['article_id']].append(b['binding_id'])
    edges = []
    for sid, articles in sorted(index.items()):
        for a, b in combinations(sorted(articles), 2):
            edges.append({'source_article': a, 'target_article': b, 'subject_id': sid,
                          'source_binding_ids': articles[a], 'target_binding_ids': articles[b],
                          'status': 'MODEL_VERIFIED_BINDINGS_SOURCE_AUDIT_PENDING'})
    return edges


def full_rankings(nodes, policies):
    import numpy as np
    ids, vectors = node_vectors(nodes, policies, rows(VECTORS / 'views.jsonl'), np.load(VECTORS / 'view_vectors.npy'))
    ix = {nid: i for i, nid in enumerate(ids)}; sim = vectors @ vectors.T
    eligible = sorted(nid for nid in nodes if policies[nid]['eligible'])
    terms = {nid: set(tokens(' '.join(m.get('text', '') for m in allowed_members(nodes[nid], policies[nid])))) for nid in eligible}
    def score(a, b):
        return float(sim[ix[a], ix[b]]) if a in ix and b in ix else len(terms[a] & terms[b]) / max(len(terms[a] | terms[b]), 1)
    return {a: sorted(eligible, key=lambda b: (-score(a, b), b)) for a in eligible}


def select_routes(rankings, mapping, bindings, article_edges, article_first):
    supported = defaultdict(dict)
    for b in bindings:
        if graph_binding(b):
            if b['subject_id'] in supported[b['node_id']]:
                raise ValueError('duplicate_node_subject_binding')
            supported[b['node_id']][b['subject_id']] = b
    neighbors = defaultdict(set)
    for edge in article_edges:
        for a, b in [(edge['source_article'], edge['target_article']), (edge['target_article'], edge['source_article'])]:
            neighbors[(a, edge['subject_id'])].add(b)
    selections = []
    for nid, ranking in sorted(rankings.items()):
        ranked = [other for other in ranking if other != nid and mapping[other] != mapping[nid]]
        choices = [other for other in ranked if supported[nid].keys() & supported[other].keys()]
        if article_first:
            per_article = defaultdict(list)
            for other in choices:
                shared = supported[nid].keys() & supported[other].keys()
                if any(mapping[other] in neighbors[(mapping[nid], sid)] for sid in shared):
                    per_article[mapping[other]].append(other)
            position = {n: i for i, n in enumerate(ranked)}
            articles = sorted(per_article, key=lambda a: (position[per_article[a][0]], a))[:2]
            guided = []; allocation = []
            for aid in articles:
                pool = per_article[aid]; first = pool[0]; selected = [first]
                first_aspects = {v['decision']['aspect_type'] for v in supported[first].values()}
                others = sorted(pool[1:], key=lambda n: (
                    not any(v['decision']['aspect_type'] not in first_aspects for v in supported[n].values()), position[n]))
                if others:
                    selected.append(others[0])
                guided.extend(selected); allocation.append({'article_id': aid, 'targets': selected})
        else:
            guided = choices[:4]; allocation = []
        selected = list(dict.fromkeys(ranked[:4] + guided))
        for other in ranked:
            if len(selected) >= min(8, len(ranked)):
                break
            if other not in selected:
                selected.append(other)
        selections.append({'source': nid, 'targets': selected[:8], 'article_allocations': allocation})
    return selections


def derive_pair(pair, bindings):
    a = {b['subject_id']: b for b in bindings if b['node_id'] == pair['source'] and graph_binding(b)}
    b = {v['subject_id']: v for v in bindings if v['node_id'] == pair['target'] and graph_binding(v)}
    shared = sorted(a.keys() & b.keys())
    paths = [{'subject_id': sid, 'source_binding_id': a[sid]['binding_id'], 'target_binding_id': b[sid]['binding_id'],
              'source_aspect': a[sid]['decision']['aspect_type'], 'target_aspect': b[sid]['decision']['aspect_type'],
              'source_local_anchors': a[sid]['decision']['local_anchors'],
              'target_local_anchors': b[sid]['decision']['local_anchors'],
              'source_context': a[sid]['decision']['context_sources'],
              'target_context': b[sid]['decision']['context_sources']} for sid in shared]
    pending = any(v['node_id'] in {pair['source'], pair['target']} and v['status'] == 'FORMAT_PENDING' for v in bindings)
    return {**pair, 'status': 'DERIVED_RELATED_VIA_SUBJECT' if paths else 'BINDING_PENDING' if pending else 'NO_SHARED_VERIFIED_SUBJECT',
            'type': 'RELATED_VIA_SUBJECT' if paths else None, 'paths': paths,
            'semantics': 'weak common-subject association; no entailment, equality or cross-article citation asserted',
            'source_audit': 'PENDING; derivation is not independent ground truth'}


def propose(out, nodes, policies, mapping, subjects, group_map, bindings):
    rankings = full_rankings(nodes, policies)
    old = rows(out / 'v1_routing_selections.jsonl')
    global_routes = [{'source': r['source'], 'targets': r['global_targets']} for r in old]
    # Ensure comparison uses the exact same original dense/lexical ranking.
    for r in global_routes:
        expected = [t for t in rankings[r['source']] if t != r['source'] and mapping[t] != mapping[r['source']]][:8]
        if r['targets'] != expected:
            raise ValueError('global_baseline_changed')
    alias_bindings = []
    for g in rows(out / 'identity_groups.jsonl'):
        for m in g['mentions']:
            if m['role'] in CONTENT_ROLES:
                alias_bindings.append({'node_id': m['node_id'], 'article_id': m['article_id'], 'subject_id': group_map[g['group_id']],
                    'binding_id': m['binding_id'], 'status': 'SUPPORTED', 'decision': {'aspect_type': 'other'}})
    # Alias-only is an explicitly unverified diagnostic arm, not final accepted graph.
    alias_index = {(b['node_id'], b['subject_id']): b for b in alias_bindings}
    mention_groups = {m['binding_id']: g['group_id'] for g in rows(out / 'identity_groups.jsonl') for m in g['mentions']}
    for b in rows(out / 'v1_context_bindings.jsonl'):
        if b['status'] == 'SUPPORTED':
            sid = group_map[mention_groups[b['context_binding_id']]]
            alias_index.setdefault((b['node_id'], sid), {'node_id': b['node_id'], 'article_id': b['article_id'],
                'subject_id': sid, 'binding_id': b['binding_id'], 'status': 'SUPPORTED', 'decision': {'aspect_type': 'other'}})
    alias_bindings = list(alias_index.values())
    article_edges = navigation(bindings)
    # Navigation is constructed first and explicitly consumed by article-first route.
    jsonl(out / 'article_navigation_edges.jsonl', article_edges)
    arms = {'global': global_routes,
            'v1_literal': [{'source': r['source'], 'targets': r['subject_targets']} for r in old],
            'alias_only': select_routes(rankings, mapping, alias_bindings, navigation(alias_bindings), False),
            'verified_subject': select_routes(rankings, mapping, bindings, article_edges, False),
            'article_first': select_routes(rankings, mapping, bindings, article_edges, True)}
    keys = {}; pool = {}
    for arm, selections in arms.items():
        jsonl(out / ('routes_' + arm + '.jsonl'), selections)
        keys[arm] = {tuple(sorted((r['source'], t))) for r in selections for t in r['targets']}
        for a, b in sorted(keys[arm]):
            pair = pool.setdefault((a, b), {'pair_id': 'V2_' + digest([a, b])[:12], 'source': a, 'target': b, 'arms': []})
            pair['arms'].append(arm)
    jsonl(out / 'node_candidates.jsonl', pool.values())
    jsonl(out / 'semantic_edges.jsonl', [edge for pair in pool.values()
          if 'article_first' in pair['arms'] for edge in [derive_pair(pair, bindings)] if edge['paths']])
    development = rows(out / 'development_pairs.jsonl')
    jsonl(out / 'development_alias_only.jsonl', [{'pair_id': p['pair_id'], 'shared_subjects': sorted(
          {b['subject_id'] for b in alias_bindings if b['node_id'] == p['source']} &
          {b['subject_id'] for b in alias_bindings if b['node_id'] == p['target']})} for p in development])
    jsonl(out / 'development_decisions.jsonl', [{**derive_pair(p, bindings),
          'candidate_coverage': {arm: tuple(sorted((p['source'], p['target']))) in pairs for arm, pairs in keys.items()}}
          for p in development])
    seen = {tuple(p) for p in read(out / 'previously_judged_pairs.json')}
    seen.update(tuple(sorted((p['source'], p['target']))) for p in development)
    fresh = [p for key, p in pool.items() if key not in seen and any(a in p['arms'] for a in ['global', 'article_first'])]
    random.Random(20261012).shuffle(fresh)
    chosen = []
    for group in ['global_only', 'article_only', 'common']:
        subset = [p for p in fresh if ('global' in p['arms'], 'article_first' in p['arms']) ==
                  {'global_only': (True, False), 'article_only': (False, True), 'common': (True, True)}[group]]
        chosen.extend(subset[:6 if group != 'common' else 4])
    chosen_ids = {p['pair_id'] for p in chosen}
    chosen.extend(p for p in fresh if p['pair_id'] not in chosen_ids)
    jsonl(out / 'fresh_review_queue.jsonl', [derive_pair({**p, 'cohort': 'new_source_review_required'}, bindings) for p in chosen[:16]])
    jsonl(out / 'candidate_deltas.jsonl', [{**p, 'change': 'added' if key in keys['article_first'] else 'removed'}
          for key, p in sorted(pool.items()) if key in keys['article_first'] ^ keys['global']])
    write(out / 'routing_summary.json', {'candidate_counts': {arm: len(v) for arm, v in keys.items()},
         'added_vs_global': len(keys['article_first'] - keys['global']), 'removed_vs_global': len(keys['global'] - keys['article_first']),
         'navigation_edges': len(article_edges), 'candidate_budget': 8,
         'all_directed_budgets_equal': all(len(r['targets']) == 8 for selections in arms.values() for r in selections),
         'evaluation': 'candidate coverage and derived weak edges only; source audit and query evaluation required'})


def report(out):
    checked(out)
    def optional(name):
        return rows(out / name) if (out / name).exists() else []
    bindings = optional('node_subject_bindings.jsonl'); decisions = optional('development_decisions.jsonl')
    calls = [read(p) for p in (out / 'calls').glob('*.json')] if (out / 'calls').exists() else []
    summary = {'phase': 'DERIVED_GRAPH_AWAITING_SOURCE_AUDIT' if decisions else 'PARTIAL_OR_NOT_STARTED',
       'alias_statuses': dict(Counter(d['status'] for d in optional('alias_decisions.jsonl'))),
       'canonical_subjects': len(optional('canonical_subjects.jsonl')),
       'binding_statuses': dict(Counter(b['status'] for b in bindings)),
       'development_statuses': dict(Counter(d['status'] for d in decisions)),
       'derived_candidate_edges': len(optional('semantic_edges.jsonl')),
       'negative_probes': [{'node_id': b['node_id'], 'status': b['status']} for b in bindings if 'negative_binding_probe' in b['purposes']],
       'model_requests': sum(len(c['response']['attempts']) for c in calls),
       'model_seconds': sum(c.get('elapsed_seconds', 0) for c in calls),
       'reading_edges': len(rows(out / 'reading_edges.jsonl')),
       'protected_candidates': len(rows(out / 'protected_intra_article_candidates.jsonl')),
       'retrieval_gain': 'NOT_EVALUATED', 'adoption': 'SOURCE_AUDIT_AND_INDEPENDENT_EVALUATION_REQUIRED'}
    if (out / 'routing_summary.json').exists():
        summary['routing'] = read(out / 'routing_summary.json')
    write(out / 'summary.json', summary)
    payload = json.dumps({'nodes': rows(out / 'units.jsonl'), 'subjects': optional('canonical_subjects.jsonl'),
        'aliases': optional('alias_decisions.jsonl'), 'bindings': bindings,
        'navigation': optional('article_navigation_edges.jsonl'), 'development': decisions,
        'fresh': optional('fresh_review_queue.jsonl'), 'edges': optional('semantic_edges.jsonl')}, ensure_ascii=False).replace('</', '<\\/')
    template = '''<!doctype html><meta charset="utf-8"><title>Article bridge v2</title>
<style>body{font:16px system-ui;margin:2rem;background:#f4f6f8}details{background:white;margin:1rem;padding:1rem}pre{white-space:pre-wrap}img{max-width:700px;max-height:500px}</style>
<h1>身份 → 独立 node 绑定 → 文章导航 → 弱关联</h1><p>模型绑定和派生边待来源审查；未评测检索提升。</p><main id="root"></main>
<script type="application/json" id="data">PAYLOAD</script><script>
const d=JSON.parse(document.getElementById('data').textContent),root=document.getElementById('root');
function text(tag,s,p){const e=document.createElement(tag);e.textContent=s;p.appendChild(e);return e}
function detail(s,p){const e=text('details','',p);text('summary',s,e);return e}
function node(id,p){const n=d.nodes.find(n=>n.id===id);const box=detail(id,p);if(!n)return;for(const m of n.members){text('pre',`${m.kind} ${m.id}\\n${m.text||''}`,box);if(m.crop){const im=document.createElement('img');im.src=m.crop;im.loading='lazy';box.appendChild(im)}}}
for(const section of ['subjects','aliases','bindings','navigation','development','fresh','edges']){const group=detail(section+' ('+d[section].length+')',root);for(const row of d[section]){const box=detail(row.binding_id||row.pair_id||row.subject_id||row.alias_pair_id,group);text('pre',JSON.stringify(row,null,2),box);if(row.node_id)node(row.node_id,box);if(row.source)node(row.source,box);if(row.target)node(row.target,box);for(const path of row.paths||[]){for(const id of [path.source_binding_id,path.target_binding_id]){const b=d.bindings.find(x=>x.binding_id===id);if(b)text('pre',JSON.stringify(b,null,2),box)}}}}
</script>'''
    (out / 'viewer.html').write_text(template.replace('PAYLOAD', payload))
    (out / 'REPORT.md').write_text('# Article bridge binding v2\n\n```json\n' + json.dumps(summary, indent=2) + '\n```\n\nDerived edge counts are not precision or retrieval gains. Review aliases, negative probes, both added and removed candidates, development cases and fresh queue against originals.\n')
    write(out / 'result_sha256.json', {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name not in {'result_sha256.json','jobs.json'}})
    print(json.dumps(summary), flush=True)


def run(out):
    checked(out)
    from run_own_corpus_edges import llm
    model = llm()
    nodes = {n['id']: n for n in rows(out / 'units.jsonl')}; policies = read(out / 'eligibility.json')
    mapping = read(out / 'unit_article_map.json')
    subjects, group_map = resolve_aliases(model, out)
    queue = binding_queue(out, group_map)
    bindings = verify_bindings(model, out, nodes, policies, mapping, subjects, queue)
    propose(out, nodes, policies, mapping, subjects, group_map, bindings)
    report(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'run', 'report'])
    parser.add_argument('--output', type=Path, default=DEFAULT)
    args = parser.parse_args()
    {'prepare': prepare, 'run': run, 'report': report}[args.stage](args.output.resolve())
