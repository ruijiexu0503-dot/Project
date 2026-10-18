#!/usr/bin/env python3
"""Source-backed subject navigation; immutable evidence nodes remain endpoints.

First pilot deliberately handles literal event/project mentions and unique explicit
figure/table references. It does not infer paragraph identity from article membership.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import time

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, check, tokens
from run_typed_node_edges import catalog, request_targets, allowed_members
from run_article_context_pilot import node_vectors, VECTORS
from run_fact_grounded_edges import call_json, digest
from node_context_policy import structured_pairs

SOURCE = ROOT / 'EvidenceNet/output/article_context_pilot_v1_20261012'
DEFAULT = ROOT / 'EvidenceNet/output/article_bridge_pilot_v1_20261012'
KINDS = {'EVENT', 'PROJECT'}
ROLES = {'reports_detection', 'estimates_parameters', 'tests_prediction', 'describes_project',
         'describes_component', 'reports_application', 'reports_results', 'mention_only', 'background'}
CONTENT_ROLES = ROLES - {'mention_only', 'background'}


def subject_key(kind, name):
    # No cross-name alias merging in this pilot: precision before alias recall.
    return kind + ':' + re.sub(r'\s+', ' ', name).strip().casefold()


def literal_span(text, mention):
    """Whitespace normalization only; return original offsets, never fabricated quote."""
    words = mention.split()
    if not words:
        raise ValueError('empty_mention')
    match = re.search(r'\s+'.join(re.escape(w) for w in words), text, re.I)
    if not match:
        raise ValueError('mention_not_in_original')
    return match.start(), match.end()


def validate_mentions(value, lookup):
    if not isinstance(value, dict) or not isinstance(value.get('mentions'), list):
        raise ValueError('mentions_list_required')
    good, bad = [], []
    for item in value['mentions']:
        try:
            if item.get('kind') not in KINDS or item.get('role') not in ROLES:
                raise ValueError('kind_or_role')
            anchor = lookup[item['evidence_id']]
            if anchor['kind'] != 'TEXT':
                raise ValueError('literal_text_required')
            lo, hi = literal_span(anchor['quote'], item['source_mention'])
            if not isinstance(item.get('aspect'), str) or not item['aspect'].strip():
                raise ValueError('aspect_required')
            # Canonical identity is exactly the source spelling after whitespace/case
            # normalization; model aliases cannot silently merge unrelated objects.
            source_name = anchor['quote'][lo:hi]
            good.append({'subject_id': subject_key(item['kind'], source_name),
                         'kind': item['kind'], 'source_mention': source_name,
                         'role': item['role'], 'aspect': item['aspect'],
                         'node_id': anchor['node_id'], 'article_id': anchor['article_id'],
                         'anchor': {**anchor, 'char_start': anchor['char_start'] + lo,
                                    'char_end': anchor['char_start'] + hi, 'quote': source_name},
                         'content_anchor': anchor})
        except (KeyError, ValueError, TypeError) as exc:
            bad.append({'record': item, 'error': str(exc)})
    return {'mentions': good, 'record_errors': bad}


def unique_explicit_references(nodes, policies):
    """Source marker resolution scoped to confirmed article identity.

    Unlike the older marker regex, a sentence-ending period is allowed; decimal
    section numbers (Fig. 1.2) are still not confused with Fig. 1.
    """
    registry = defaultdict(list)
    pattern = r'\b(fig(?:ure)?s?\.?|table)\s*([0-9]+|[IVX]+)(?!\d|\.\d)'
    for node in nodes.values():
        for member in allowed_members(node, policies[node['id']]):
            if member['kind'] != 'atom':
                continue
            cap = re.match(r'^\s*(FIG(?:URE)?\.?|TABLE)\s*([0-9]+|[IVX]+)\b', member['text'], re.I)
            if cap:
                kind = 'figure' if cap[1].lower().startswith('fig') else 'table'
                registry[(node.get('article_id'), kind, cap[2].upper())].append((node, member))
    references, issues = [], []
    for node in nodes.values():
        for member in allowed_members(node, policies[node['id']]):
            if member['kind'] != 'atom':
                continue
            text = member['text']
            for match in re.finditer(pattern, text, re.I):
                if not text[:match.start()].strip():
                    continue  # caption declaration, not a reference
                if re.search(r'\b(?:their|his|her)\b', text[max(0, match.start()-25):match.start()], re.I):
                    continue
                kind = 'figure' if match[1].lower().startswith('fig') else 'table'
                hits = [(n, m) for n, m in registry[(node.get('article_id'), kind, match[2].upper())]
                        if n['id'] != node['id'] and n['document'] == node['document'] and node.get('article_id')]
                if len({n['id'] for n, m in hits}) == 1:
                    target, tm = hits[0]
                    references.append({'source': node['id'], 'target': target['id'], 'source_member': member['id'],
                        'source_start': match.start(), 'source_end': match.end(), 'source_quote': match[0],
                        'target_member': tm['id'], 'target_quote': tm['text'], 'kind': kind, 'number': match[2].upper(),
                        'verification': 'unique marker within confirmed article identity'})
                else:
                    issues.append({'node_id': node['id'], 'kind': kind, 'number': match[2].upper(),
                                   'reason': 'ambiguous_target' if hits else 'target_not_available'})
    return references, issues


def select_articles(nodes):
    papers = ['gw150914_detection', 'gw150914_properties', 'gw150914_gr_test',
              'arxiv_1510_04615', 'gNtSaU-1511.05999v3', 'arxiv_1511_05955', 'detr']
    result = []
    for doc in papers:
        members = [n for n in nodes.values() if n['document'] == doc]
        if not members or any(n.get('assignment_status') != 'KNOWN_PAPER_DOCUMENT_PROFILE' for n in members):
            raise ValueError('paper_boundary_unconfirmed:' + doc)
        result.append({'article_id': 'BRIDGE:' + doc, 'document': doc,
                       'boundary_status': 'KNOWN_PAPER_DOCUMENT_PROFILE',
                       'boundary_basis': 'inherited confirmed paper identity; sampled pages only',
                       'node_ids': sorted(n['id'] for n in members)})
    fragments = [
        ('DLRmagazine_176_EN', 'page_0012', list(range(1, 23)), 'AHEAD',
         'one humanitarian-aid article continuation, including project sidebar; author bio is metadata'),
        ('CERNCourier2025JanFeb-digitaledition', 'page_0017', list(range(2, 10)) + [14, 15], 'UMBRELLA',
         'top stroke-treatment article only; lower RF article excluded'),
        ('CERNCourier2022NovDec-digitaledition', 'page_0006', list(range(12, 18)) + [34], 'OpenScience',
         'bottom-left Open Science article only; Nobel, astronomy and Microcosm excluded'),
        ('ML1_11_Reinforcement_Learning_1', 'page_0003', list(range(1, 9)), 'supervised_slide',
         'single slide fragment, not a complete research article')]
    for doc, page, numbers, label, basis in fragments:
        ids = [f'{doc}_{page}_HY_{i:03d}' for i in numbers]
        if any(n not in nodes for n in ids):
            raise ValueError('missing_fragment_node:' + label)
        result.append({'article_id': f'BRIDGE:{doc}:{label}', 'document': doc,
                       'boundary_status': 'VISUALLY_REVIEWED_PAGE_FRAGMENT',
                       'boundary_basis': basis, 'node_ids': ids,
                       'page_image': 'assets/pages/' + next((SOURCE / 'assets/pages').glob(f'*_{doc}_{page}.jpg')).name})
    for article in result:
        article['sampled_pages'] = sorted({nodes[n]['page'] for n in article['node_ids']})
        article['coverage'] = 'available sampled pages/fragment, not guaranteed complete article'
    return result


def prepare(out):
    if out.exists():
        raise ValueError('fresh_output_required')
    check(SOURCE)
    original = {n['id']: n for n in rows(SOURCE / 'units.jsonl')}
    articles = select_articles(original)
    out.mkdir(parents=True)
    (out / 'assets').symlink_to((SOURCE / 'assets').resolve(), target_is_directory=True)
    mapping = {nid: a['article_id'] for a in articles for nid in a['node_ids']}
    nodes = {nid: original[nid] for nid in mapping}
    policies = {nid: deepcopy(read(SOURCE / 'eligibility.json')[nid]) for nid in nodes}
    for nid in nodes:
        # Explicitly reviewed author/byline nodes, retained as original nodes but
        # not usable as subject evidence. Do not interpret affiliations as projects.
        if nid in {'DLRmagazine_176_EN_page_0012_HY_014',
                   'CERNCourier2025JanFeb-digitaledition_page_0017_HY_009'}:
            policies[nid]['eligible'] = False
            for member in policies[nid]['members']:
                member.update(eligible=False, reason='reviewed_author_metadata')
    jsonl(out / 'units.jsonl', nodes.values())
    write(out / 'eligibility.json', policies)
    jsonl(out / 'articles.jsonl', articles)
    write(out / 'unit_article_map.json', mapping)
    reading = [e for e in rows(SOURCE / 'reading_edges.jsonl') if e['source'] in nodes and e['target'] in nodes]
    jsonl(out / 'reading_edges.jsonl', reading)
    routed_nodes = {nid: {**n, 'article_id': mapping[nid]} for nid, n in nodes.items()}
    structural, old_issues = structured_pairs(routed_nodes, policies, reading)
    references, issues = unique_explicit_references(routed_nodes, policies)
    issues.extend(i for i in old_issues if i.get('kind') == 'equation')
    protected = {}
    for pair in structural:
        if mapping[pair['source']] != mapping[pair['target']]:
            continue
        equation_refs = [r for r in pair['references'] if r['kind'] == 'equation']
        pair = {**pair, 'routes': [r for r in pair['routes'] if r != 'resolved_source_reference' or equation_refs],
                'references': equation_refs}
        if pair['routes']:
            protected[tuple(sorted((pair['source'], pair['target'])))] = pair
    for ref in references:
        key = tuple(sorted((ref['source'], ref['target'])))
        pair = protected.setdefault(key, {'source': key[0], 'target': key[1], 'routes': [], 'references': []})
        if 'resolved_source_reference' not in pair['routes']:
            pair['routes'].append('resolved_source_reference')
        pair['references'].append(ref)
    structural = list(protected.values())
    jsonl(out / 'protected_intra_article_candidates.jsonl', structural)
    jsonl(out / 'reference_issues.jsonl', issues)
    old_queue = rows(ROOT / 'EvidenceNet/output/typed_node_edges_v1_20261012/verification_queue.jsonl')
    available = [p for p in old_queue if p['source'] in nodes and p['target'] in nodes]
    preferred = {'TYPED_08073', 'TYPED_08362', 'TYPED_08365', 'TYPED_05820', 'TYPED_05882',
                 'TYPED_04439', 'TYPED_04478', 'TYPED_01886', 'TYPED_05306', 'TYPED_00270',
                 'TYPED_07887', 'TYPED_05813', 'TYPED_06144', 'TYPED_08446'}
    required = [p for p in available if p['pair_id'] in preferred]
    rng = random.Random(20261012)
    rest = [p for p in available if p['pair_id'] not in preferred]
    rng.shuffle(rest)
    selected = (required + rest)[:28]
    if len(selected) < 20:
        raise ValueError('insufficient_development_pairs')
    jsonl(out / 'development_pairs.jsonl', [{**p, 'scope': 'intra_article' if mapping[p['source']] == mapping[p['target']] else 'cross_article',
            'cohort': 'frozen_development', 'label_status': 'source audit pending; prior decisions are not truth'} for p in selected])
    write(out / 'previously_judged_pairs.json', [sorted((p['source'], p['target'])) for p in old_queue])
    names = ['units.jsonl', 'eligibility.json', 'articles.jsonl', 'unit_article_map.json', 'reading_edges.jsonl',
             'protected_intra_article_candidates.jsonl', 'reference_issues.jsonl', 'development_pairs.jsonl', 'previously_judged_pairs.json']
    code = [Path(__file__), *[Path(__file__).with_name(n + '.py') for n in
            ['run_node_context_edges', 'run_typed_node_edges', 'run_article_context_pilot',
             'run_fact_grounded_edges', 'run_own_corpus_edges', 'node_context_policy', 'verify_node_context_v3',
             'node_context_coreference']]]
    code.append(ROOT / 'EvidenceNet/evidence_graph/llm_client.py')
    asset_hashes = {}
    for nid, node in nodes.items():
        for member in allowed_members(node, policies[nid]):
            if member.get('crop'):
                asset_hashes[member['crop']] = sha(out / member['crop'])
    for article in articles:
        if article.get('page_image'):
            asset_hashes[article['page_image']] = sha(out / article['page_image'])
    write(out / 'asset_sha256.json', asset_hashes)
    names.append('asset_sha256.json')
    manifest = {'experiment': 'article_bridge_pilot_v1', 'source': str(SOURCE),
                'original_node_files': read(SOURCE / 'manifest.json')['original_node_files'],
                'snapshot_files': {n: sha(out / n) for n in names},
                'code_sha256': {str(p): sha(p) for p in code},
                'vector_cache_sha256': {str(VECTORS / n): sha(VECTORS / n) for n in ['views.jsonl', 'view_vectors.npy']},
                'model': str(ROOT / 'external/models/Qwen3.5-35B-A3B'),
                'model_config_sha256': sha(ROOT / 'external/models/Qwen3.5-35B-A3B/config.json'),
                'sampling': {'do_sample': False, 'enable_thinking': False},
                'cross_article_budget_per_node': 8, 'subject_quota': 4, 'fresh_pair_budget': 16,
                'adoption_gate': {'independent_source_audit_required': True, 'protected_routes_lost': 0,
                     'accepted_source_or_identity_errors_allowed': 0,
                     'known_valid_cross_article_recall_must_improve': True,
                     'retrieval_gain_claim': 'requires separate frozen-query evaluation; not tested here'},
                'limitations': ['event/project only; no cross-name aliases', 'explicit figure/table context only',
                                'fresh cases excluded from previous verification queue, not expert blind labels'],
                'development_sample': True}
    write(out / 'manifest.json', manifest)
    (out / 'code').mkdir(exist_ok=True)
    for p in code:
        shutil.copy2(p, out / 'code' / p.name)
    print(json.dumps({'articles': len(articles), 'nodes': len(nodes), 'development_pairs': len(selected),
                      'protected_candidates': len(structural), 'reading_edges': len(reading)}), flush=True)


def checked(out):
    check(out)
    manifest = read(out / 'manifest.json')
    for path, h in {**manifest['code_sha256'], **manifest['vector_cache_sha256']}.items():
        if sha(path) != h:
            raise ValueError('changed_runtime_input:' + path)
    for path, fingerprint in read(out / 'asset_sha256.json').items():
        if sha(out / path) != fingerprint:
            raise ValueError('changed_source_asset:' + path)
    if sha(Path(manifest['model']) / 'config.json') != manifest['model_config_sha256']:
        raise ValueError('changed_model_config')


def cached_call(model, out, name, prompt, images, validate, budget=1700):
    path = out / 'calls' / (name + '.json')
    fingerprint = digest({'prompt': prompt, 'images': [sha(p) for p in images],
                          'generation': read(out / 'manifest.json')['sampling'], 'budget': budget})
    if path.exists():
        record = read(path)
        if record['input_sha256'] != fingerprint:
            raise ValueError('stale_call:' + name)
        return record['response']
    started = time.monotonic()
    response = call_json(model, prompt, images, validate, budget)
    write(path, {'input_sha256': fingerprint, 'response': response, 'elapsed_seconds': time.monotonic() - started})
    print(name, 'READY' if response['valid'] else 'FORMAT_PENDING', flush=True)
    return response


def index_subjects(model, out, nodes, policies, mapping):
    mentions, failures = [], []
    for article in rows(out / 'articles.jsonl'):
        ids = [nid for nid in article['node_ids'] if policies[nid]['eligible']]
        for start in range(0, len(ids), 5):
            public, lookup = [], {}
            for i, nid in enumerate(ids[start:start + 5]):
                evidence, anchors = catalog(nodes[nid], policies[nid], f'N{i}', out)
                public.append({'node_id': nid, 'evidence': [e for e in evidence if e['kind'] == 'TEXT']})
                lookup.update({key: {**a, 'node_id': nid, 'article_id': article['article_id']}
                               for key, a in anchors.items()})
            prompt = '''Independently index specific named EVENTS and PROJECTS in these original node texts.
An EVENT is a specific occurrence (e.g. GW150914), not LIGO, a generic measurement or SNR threshold.
A PROJECT is an identifiable named initiative, not CERN, a task category or an institution.
Return literal source mentions only; no aliases or inferred identities. Preserve distinct subjects.
Classify the content role separately at each node: reports_detection, estimates_parameters,
tests_prediction, describes_project, describes_component, reports_application, mention_only, background.
Generic detection/noise/method text remains background even when an event is cited in related work.
Never assign an event to other nodes just because they share an article. Unknown referents stay unresolved.
Author lists, affiliations, running headers, footer/page numbers and bare names are not content roles.
Return at most 12 records, deduplicating subject per node; empty list is valid.
Schema: {"mentions":[{"kind":"EVENT|PROJECT","source_mention":"literal name",
"evidence_id":"actual N0:T000 ID","role":"one allowed role","aspect":"what THIS node says about it, including qualifiers"}]}.
''' + json.dumps(public, ensure_ascii=False)
            response = cached_call(model, out, 'index_' + digest(article['article_id'])[:10] + f'_{start:03d}',
                                   prompt, [], lambda v: validate_mentions(v, lookup), 2200)
            if response['valid']:
                mentions.extend(response['bound']['mentions'])
                failures.extend(response['bound']['record_errors'])
            else:
                failures.append({'article_id': article['article_id'], 'nodes': ids[start:start + 5],
                                 'error': 'FORMAT_PENDING', 'errors': response['errors']})
    for i, m in enumerate(mentions):
        m['binding_id'] = f'M{i:04d}'
        m['binding_kind'] = 'DIRECT_LITERAL'
    jsonl(out / 'subject_mentions.jsonl', mentions)
    jsonl(out / 'index_errors.jsonl', failures)
    subjects = defaultdict(list)
    for m in mentions:
        subjects[m['subject_id']].append(m)
    jsonl(out / 'subjects.jsonl', [{'subject_id': sid, 'kind': ms[0]['kind'],
            'source_spellings': sorted({m['source_mention'] for m in ms}),
            'article_ids': sorted({m['article_id'] for m in ms}),
            'binding_ids': [m['binding_id'] for m in ms]} for sid, ms in sorted(subjects.items())])
    return mentions


def figure_bindings(model, out, nodes, policies, mapping, mentions):
    direct = defaultdict(list)
    for mention in mentions:
        if mention['role'] in CONTENT_ROLES:
            direct[mention['node_id']].append(mention)
    bindings = []
    for pair in rows(out / 'protected_intra_article_candidates.jsonl'):
        for ref in pair.get('references', []):
            if ref['kind'] not in {'figure', 'table'}:
                continue
            for source in direct[ref['source']]:
                target = nodes[ref['target']]
                public, lookup = catalog(target, policies[target['id']], 'TARGET', out)
                images = []
                for entry in public:
                    if entry['kind'] == 'VISUAL':
                        images.append(str(out / entry.pop('crop')))
                        entry['image_index'] = len(images)
                def validate(value):
                    if value.get('status') not in {'SUPPORTED', 'UNSUPPORTED', 'UNCERTAIN'}:
                        raise ValueError('binding_status')
                    if not isinstance(value.get('aspect'), str) or not isinstance(value.get('reason'), str):
                        raise ValueError('binding_explanation')
                    ids = value.get('target_evidence_ids')
                    if not isinstance(ids, list) or any(x not in lookup for x in ids):
                        raise ValueError('target_anchor_ids')
                    if value['status'] == 'SUPPORTED' and (not ids or not value['aspect'].strip()):
                        raise ValueError('binding_local_support')
                    return {**value, 'target_anchors': [lookup[x] for x in ids]}
                prompt = '''Check this explicit within-article figure/table reference against the original target.
The source must explicitly identify the subject AND refer to this target's number in a relevant assertion.
A mention of an unrelated comparison or generic background cannot assign the subject to the target.
The target must contain substantive content about that subject after resolving the reference.
Keep what the TARGET itself says separate from source-only values/qualifiers; do not copy source masses into a plot.
Return {"status":"SUPPORTED|UNSUPPORTED|UNCERTAIN","target_evidence_ids":["TARGET:T000"],
"aspect":"target's actual content","reason":"why this explicit reference resolves identity"}.
''' + json.dumps({'subject': source, 'reference': ref, 'target': public}, ensure_ascii=False)
                name = 'bind_' + digest([ref, source['binding_id']])[:16]
                response = cached_call(model, out, name, prompt, images, validate, 1200)
                record = {'binding_id': 'B' + digest([ref, source['binding_id']])[:12],
                          'subject_id': source['subject_id'], 'node_id': target['id'],
                          'article_id': mapping[target['id']], 'binding_kind': 'EXPLICIT_SOURCE_REFERENCE',
                          'context_binding_id': source['binding_id'], 'context_anchor': source['content_anchor'],
                          'reference': ref, 'response': response}
                if response['valid'] and response['bound']['status'] == 'SUPPORTED':
                    record.update(role='reports_results', aspect=response['bound']['aspect'],
                                  target_anchors=response['bound']['target_anchors'], status='SUPPORTED')
                else:
                    record['status'] = response['bound']['status'] if response['valid'] else 'FORMAT_PENDING'
                bindings.append(record)
    jsonl(out / 'context_bindings.jsonl', bindings)
    return [b for b in bindings if b['status'] == 'SUPPORTED']


def route(nodes, mapping, eligible, base_rank, bindings, budget=8, quota=4):
    by_node = defaultdict(dict)
    for binding in bindings:
        if binding.get('role') in CONTENT_ROLES:
            by_node[binding['node_id']][binding['subject_id']] = binding
    selections, pairs = [], {}
    for nid in sorted(eligible):
        ranked = [other for other in base_rank[nid] if other != nid and mapping[other] != mapping[nid]]
        guided = [other for other in ranked if by_node[nid].keys() & by_node[other].keys()]
        # Reserve half for global fallback; shared-subject slots are finite and padded.
        combined = list(dict.fromkeys(guided[:quota] + ranked[:budget - quota]))
        for other in ranked:
            if len(combined) >= min(budget, len(ranked)):
                break
            if other not in combined:
                combined.append(other)
        selection = {'source': nid, 'global_targets': ranked[:budget], 'subject_targets': combined[:budget]}
        selections.append(selection)
        for arm in ['global', 'subject']:
            for target in selection[arm + '_targets']:
                a, b = sorted((nid, target))
                p = pairs.setdefault((a, b), {'source': a, 'target': b, 'arms': [],
                     'shared_subject_ids': sorted(by_node[a].keys() & by_node[b].keys())})
                if arm not in p['arms']:
                    p['arms'].append(arm)
    return selections, list(pairs.values()), by_node


def propose(out, nodes, policies, mapping, bindings):
    import numpy as np
    ids, vectors = node_vectors(nodes, policies, rows(VECTORS / 'views.jsonl'), np.load(VECTORS / 'view_vectors.npy'))
    index = {nid: i for i, nid in enumerate(ids)}
    similarities = vectors @ vectors.T
    eligible = sorted(nid for nid in nodes if policies[nid]['eligible'])
    terms = {nid: set(tokens(' '.join(m.get('text', '') for m in allowed_members(nodes[nid], policies[nid])))) for nid in eligible}
    rankings = {}
    for nid in eligible:
        def score(other):
            lexical = len(terms[nid] & terms[other]) / max(len(terms[nid] | terms[other]), 1)
            if nid in index and other in index:
                return float(similarities[index[nid], index[other]])
            return lexical
        # Dense then lexical fallback; all eligible nodes remain addressable.
        rankings[nid] = sorted(eligible, key=lambda other: (-score(other), other))
    selections, pairs, by_node = route(nodes, mapping, eligible, rankings, bindings)
    jsonl(out / 'routing_selections.jsonl', selections)
    jsonl(out / 'node_candidates.jsonl', [{**p, 'pair_id': 'BRIDGE_' + digest([p['source'], p['target']])[:12],
              'status': 'CANDIDATE_ONLY'} for p in pairs])
    nav = defaultdict(lambda: {'binding_ids': [], 'node_ids': set()})
    for b in bindings:
        if b.get('role') in CONTENT_ROLES:
            v = nav[(b['subject_id'], b['article_id'])]
            v['binding_ids'].append(b['binding_id']); v['node_ids'].add(b['node_id'])
    article_edges = []
    for sid in sorted({s for s, _ in nav}):
        articles = sorted(a for s, a in nav if s == sid)
        for i, a in enumerate(articles):
            for b in articles[i + 1:]:
                article_edges.append({'source_article': a, 'target_article': b, 'subject_id': sid,
                    'type': 'SHARED_' + sid.split(':')[0], 'status': 'LITERAL_ANCHORED_MODEL_NAVIGATION_AUDIT_PENDING',
                    'source_binding_ids': nav[(sid, a)]['binding_ids'], 'target_binding_ids': nav[(sid, b)]['binding_ids']})
    jsonl(out / 'article_navigation_edges.jsonl', article_edges)
    jsonl(out / 'subject_node_index.jsonl', [{'subject_id': sid, 'article_id': aid, 'node_ids': sorted(v['node_ids']),
                                            'binding_ids': v['binding_ids']} for (sid, aid), v in sorted(nav.items())])
    prior = {tuple(p) for p in read(out / 'previously_judged_pairs.json')}
    fresh = [p for p in rows(out / 'node_candidates.jsonl') if (p['source'], p['target']) not in prior]
    random.Random(20261012).shuffle(fresh)
    # Matched exclusive-arm samples plus common candidates, fixed before verification.
    buckets = [[p for p in fresh if p['arms'] == [arm]] for arm in ['global', 'subject']]
    chosen = buckets[0][:5] + buckets[1][:5]
    chosen_keys = {(p['source'], p['target']) for p in chosen}
    chosen += [p for p in fresh if (p['source'], p['target']) not in chosen_keys][:16 - len(chosen)]
    queue = rows(out / 'development_pairs.jsonl') + [{**p, 'cohort': 'fresh_untouched'} for p in chosen]
    jsonl(out / 'verification_queue.jsonl', queue)
    write(out / 'proposal_manifest.json', {'queue_sha256': sha(out / 'verification_queue.jsonl'),
         'selections_sha256': sha(out / 'routing_selections.jsonl'), 'binding_sha256': digest(bindings),
         'eligible_nodes': len(eligible), 'vector_nodes': len(ids), 'lexical_fallback_nodes': sorted(set(eligible) - set(ids)),
         'candidate_count': len(pairs), 'navigation_edges': len(article_edges)})
    return by_node


def validate_decision(v, anchors, shared):
    if v.get('status') not in {'ACCEPT', 'REJECT', 'UNCERTAIN'}:
        raise ValueError('decision_status')
    if not shared and v['status'] != 'UNCERTAIN':
        raise ValueError('missing_binding_is_unresolved')
    for field in ['reason', 'source_aspect', 'target_aspect', 'subject_id']:
        if not isinstance(v.get(field), str):
            raise ValueError('decision_field:' + field)
    for field, label in [('source_evidence_ids', 'A:'), ('target_evidence_ids', 'B:')]:
        values = v.get(field)
        if not isinstance(values, list) or any(x not in anchors or not x.startswith(label) for x in values):
            raise ValueError('endpoint_anchor:' + field)
        if v['status'] == 'ACCEPT' and not values:
            raise ValueError('accept_needs_local_anchor')
    if v['status'] == 'ACCEPT' and (not v['source_aspect'].strip() or not v['target_aspect'].strip()):
        raise ValueError('accept_needs_two_aspects')
    if v['status'] == 'ACCEPT' and v['subject_id'] not in shared:
        raise ValueError('unbound_subject')
    return {**v, 'source_anchors': [anchors[x] for x in v['source_evidence_ids']],
            'target_anchors': [anchors[x] for x in v['target_evidence_ids']]}

def verify(model, out, nodes, policies, by_node):
    proposal = read(out / 'proposal_manifest.json')
    if sha(out / 'verification_queue.jsonl') != proposal['queue_sha256']:
        raise ValueError('queue_changed')
    decisions = []
    for pair in rows(out / 'verification_queue.jsonl'):
        public, endpoint_anchors, images = request_targets(pair, nodes, policies, out)
        anchors = {key: anchor for lookup in endpoint_anchors.values() for key, anchor in lookup.items()}
        a, b = pair['source'], pair['target']
        shared = sorted(by_node[a].keys() & by_node[b].keys())
        binding_pairs = [{'subject_id': sid, 'source': by_node[a][sid], 'target': by_node[b][sid]} for sid in shared]
        prompt = '''Verify these two immutable evidence nodes using the same rule for every retrieval arm.
RELATED_VIA_SUBJECT means each target contains substantive content about the SAME specific EVENT/PROJECT.
Shared institutions, instruments, broad topics, method text or mention-only citations are insufficient.
The shared subject may be resolved by the supplied explicit source reference, but local content must still exist.
Inspect original images when present. Target anchors and context anchors must remain distinct.
Do not assert SUPPORTS, EXPLAINS, CAPTION_FOR, numerical equality, causation or entailment.
Keep source/target aspects including incompatible reference frames and conditions separate.
If candidate binding is incorrect or a local assertion is borrowed from context, REJECT or UNCERTAIN.
No shared binding means UNCERTAIN (index coverage unresolved), not a correct negative.
Return {"status":"ACCEPT|REJECT|UNCERTAIN","subject_id":"one supplied shared subject or empty",
"source_evidence_ids":["A:T000"],"target_evidence_ids":["B:T000"],
"source_aspect":"local content","target_aspect":"local content","reason":"source-backed explanation"}.
''' + json.dumps({'target_evidence': public, 'shared_bindings': binding_pairs}, ensure_ascii=False)
        response = cached_call(model, out, 'verify_' + pair['pair_id'], prompt, images, lambda v: validate_decision(v, anchors, shared), 1400)
        decisions.append({'pair': pair, 'status': response['bound']['status'] if response['valid'] else 'FORMAT_PENDING',
                          'decision': response['bound'], 'errors': response['errors'], 'shared_binding_pairs': binding_pairs})
        jsonl(out / 'node_edge_decisions.jsonl', decisions)
    return decisions


def report(out):
    checked(out)
    decisions = rows(out / 'node_edge_decisions.jsonl') if (out / 'node_edge_decisions.jsonl').exists() else []
    mapping = read(out / 'unit_article_map.json')
    selections = rows(out / 'routing_selections.jsonl') if (out / 'routing_selections.jsonl').exists() else []
    keys = {arm: {tuple(sorted((r['source'], t))) for r in selections for t in r[arm + '_targets']} for arm in ['global', 'subject']}
    coverage = []
    for p in rows(out / 'development_pairs.jsonl'):
        k = tuple(sorted((p['source'], p['target'])))
        coverage.append({'pair_id': p['pair_id'], 'scope': p['scope'], **{arm: k in keys[arm] for arm in keys},
                         'label_status': 'requires independent source review'})
    jsonl(out / 'routing_development_coverage.jsonl', coverage)
    edges, aggregation = [], defaultdict(list)
    for d in decisions:
        if d['status'] != 'ACCEPT':
            continue
        p, v = d['pair'], d['decision']
        edge = {'id': p['pair_id'], 'source': p['source'], 'target': p['target'], 'type': 'RELATED_VIA_SUBJECT',
                'subject_id': v['subject_id'], 'source_aspect': v['source_aspect'], 'target_aspect': v['target_aspect'],
                'source_anchors': v['source_anchors'], 'target_anchors': v['target_anchors'],
                'bindings': [x for x in d['shared_binding_pairs'] if x['subject_id'] == v['subject_id']],
                'status': 'MODEL_ACCEPTED_SOURCE_AUDIT_PENDING'}
        edges.append(edge)
        aa, bb = sorted((mapping[p['source']], mapping[p['target']]))
        if aa != bb:
            aggregation[(aa, bb, v['subject_id'])].append(p['pair_id'])
    jsonl(out / 'semantic_edges.jsonl', edges)
    jsonl(out / 'article_evidence_edges.jsonl', [{'source_article': a, 'target_article': b,
          'subject_id': s, 'node_edge_ids': ids, 'status': 'MODEL_ACCEPTED_SOURCE_AUDIT_PENDING'}
          for (a, b, s), ids in sorted(aggregation.items())])
    calls = [read(p) for p in sorted((out / 'calls').glob('*.json'))] if (out / 'calls').exists() else []
    summary = {'phase': 'RESULTS_PENDING_SOURCE_AUDIT' if decisions else 'AWAITING_MODEL_RUN',
               'model_requests': sum(len(c['response']['attempts']) for c in calls),
               'model_call_seconds': sum(c.get('elapsed_seconds', 0) for c in calls),
               'decisions': len(decisions), 'statuses': dict(Counter(d['status'] for d in decisions)),
               'cohorts': {c: dict(Counter(d['status'] for d in decisions if d['pair']['cohort'] == c))
                           for c in sorted({d['pair']['cohort'] for d in decisions})},
               'accepted_edges': len(edges), 'retrieval_gain': 'NOT_EVALUATED',
               'index_record_errors': len(rows(out / 'index_errors.jsonl')) if (out / 'index_errors.jsonl').exists() else None,
               'context_binding_statuses': dict(Counter(b['status'] for b in rows(out / 'context_bindings.jsonl'))) if (out / 'context_bindings.jsonl').exists() else {},
               'adoption': 'NOT_APPROVED; source audit and independent evaluation pending',
               'protected_candidates': len(rows(out / 'protected_intra_article_candidates.jsonl')),
               'development_cross_article_candidate_coverage': {arm: sum(p[arm] for p in coverage if p['scope'] == 'cross_article') for arm in keys} if selections else None}
    write(out / 'summary.json', summary)
    nodes = rows(out / 'units.jsonl')
    payload = json.dumps({'articles': rows(out / 'articles.jsonl'), 'nodes': nodes,
                         'navigation': rows(out / 'article_navigation_edges.jsonl') if (out / 'article_navigation_edges.jsonl').exists() else [],
                         'mentions': rows(out / 'subject_mentions.jsonl') if (out / 'subject_mentions.jsonl').exists() else [],
                         'bindings': rows(out / 'context_bindings.jsonl') if (out / 'context_bindings.jsonl').exists() else [],
                         'decisions': decisions}, ensure_ascii=False).replace('</', '<\\/')
    template = '''<!doctype html><meta charset="utf-8"><title>Article subject bridge pilot</title>
<style>body{font:16px system-ui;margin:2rem;background:#f5f7fa}details{margin:1rem;padding:1rem;background:white}pre{white-space:pre-wrap}img{max-width:700px;max-height:500px}button,select{padding:.5rem}</style>
<h1>文章关联 → evidence node → 原文／原图</h1><p>模型输出待来源审查；文章导航不等于证据边。点击下列节点查看原始成员。上下文绑定独立显示。</p>
<select id="articles"></select><div id="content"></div><h2>文章导航理由</h2><div id="nav"></div><h2>核验结果（含拒绝／不确定）</h2><div id="decisions"></div>
<script id="data" type="application/json">PAYLOAD</script><script>
const d=JSON.parse(document.getElementById('data').textContent),select=document.getElementById('articles');
function text(tag,value,parent){let e=document.createElement(tag);e.textContent=value;parent.appendChild(e);return e}
function detail(value,parent){let e=text('details','',parent);text('summary',value,e);return e}
function node(id,parent){let n=d.nodes.find(x=>x.id===id);let e=detail(id,parent);if(!n)return;
for(let m of n.members){text('pre',`${m.kind} ${m.id} (${m.role||''})\\n${m.text||''}`,e);if(m.crop){let im=document.createElement('img');im.src=m.crop;im.loading='lazy';e.appendChild(im)}}
text('pre',JSON.stringify({direct:d.mentions.filter(x=>x.node_id===id),context:d.bindings.filter(x=>x.node_id===id)},null,2),e)}
for(let a of d.articles){let o=text('option',a.article_id,select);o.value=a.article_id}
function show(){let c=document.getElementById('content');c.replaceChildren();let a=d.articles.find(x=>x.article_id===select.value);text('p',a.boundary_basis+' — '+a.coverage,c);for(let id of a.node_ids)node(id,c)}select.onchange=show;if(d.articles.length)show();
for(let v of d.navigation){let e=detail(v.source_article+' ↔ '+v.target_article+' via '+v.subject_id,document.getElementById('nav'));text('pre',JSON.stringify(v,null,2),e);for(let id of [...v.source_binding_ids,...v.target_binding_ids]){let b=d.mentions.concat(d.bindings).find(x=>x.binding_id===id);if(b)node(b.node_id,e)}}
for(let v of d.decisions){let e=detail(v.pair.pair_id+' '+v.status,document.getElementById('decisions'));text('pre',JSON.stringify(v,null,2),e);node(v.pair.source,e);node(v.pair.target,e)}
</script>'''
    (out / 'viewer.html').write_text(template.replace('PAYLOAD', payload))
    (out / 'REPORT.md').write_text('# Article bridge pilot\n\n' + json.dumps(summary, indent=2) +
        '\n\nThe two arms use identical originals and a common verifier over their sampled union. Counts are development diagnostics, not retrieval metrics. '
        'Zero shared bindings is unresolved coverage, not proof of no relationship. Navigation uses source-backed EVENT/PROJECT identity; '
        'only explicit unique figure/table references resolve unnamed targets in this first version. Protected local candidates and reading edges consume no cross-article slots. '
        'Inspect index_errors, reference_issues, context_bindings and both accepted/rejected decisions before assessing benefit.\n')
    print(json.dumps(summary), flush=True)


def run(out):
    checked(out)
    from run_own_corpus_edges import llm
    model = llm()
    nodes = {n['id']: n for n in rows(out / 'units.jsonl')}
    policies = read(out / 'eligibility.json'); mapping = read(out / 'unit_article_map.json')
    mentions = index_subjects(model, out, nodes, policies, mapping)
    context = figure_bindings(model, out, nodes, policies, mapping, mentions)
    by_node = propose(out, nodes, policies, mapping, mentions + context)
    verify(model, out, nodes, policies, by_node)
    report(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'run', 'report'])
    parser.add_argument('--output', type=Path, default=DEFAULT)
    args = parser.parse_args()
    {'prepare': prepare, 'run': run, 'report': report}[args.stage](args.output.resolve())
