import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_article_context_pilot import pair_context, validate, route_candidates, node_vectors


def node(nid, document='doc', article='article'):
    return {'id': nid, 'document': document, 'page': 'page_0001', 'article_id': article,
            'min_order': None, 'members': [{'id': 'm', 'kind': 'atom', 'text': 'A specific project result.'}]}


def test_context_never_contains_either_target_even_in_same_article():
    ns = {nid: node(nid) for nid in ['a', 'b', 'c']}
    article = {'article_id': 'article', 'titles': ['A title'], 'title_provenance': 'metadata',
               'assignment_statuses': ['PAGE_LOCAL_ONLY'], 'source_snippets': [
                   {'node_id': nid, 'member_id': 'm', 'page': 'page_0001',
                    'quote': 'A specific project result.', 'char_start': 0} for nid in ns]}
    contexts = pair_context({'source': 'a', 'target': 'b'}, ns, {'article': article})
    assert {s['node_id'] for c in contexts.values() for s in c['snippets']} == {'c'}
    ns['a']['article_id'] = None
    assert pair_context({'source': 'a', 'target': 'b'}, ns, {'article': article})['A']['snippets'] == []


def response(kind='SAME_PROJECT'):
    return {'status': 'ACCEPT', 'relation_type': kind, 'direction': 'SYMMETRIC', 'reason': 'Specific shared project.',
            'anchors_a': ['A:T000'], 'anchors_b': ['B:T000'], 'context_ids': [],
            'local_content_a': 'Local project participation.', 'local_content_b': 'Local project results.'}


def lookups():
    return {'A': {'A:T000': {'kind': 'TEXT', 'quote': 'Project participation.'}},
            'B': {'B:T000': {'kind': 'TEXT', 'quote': 'Project results.'}}}


def test_context_cannot_replace_an_endpoint_anchor():
    value = response();value['anchors_a'] = ['CTX:A:000']
    context = {'A': {'snippets': [{'id': 'CTX:A:000'}]}}
    with pytest.raises(ValueError, match='anchors_must_be_local_id_array'):
        validate(value, lookups(), context)
    value = response();value['context_ids'] = ['CTX:A:000']
    with pytest.raises(ValueError, match='context_id_not_supplied'):
        validate(value, lookups(), {})


def test_multiple_local_anchors_are_bound_and_cross_endpoint_ids_rejected():
    ls = lookups();ls['A']['A:T001'] = {'kind': 'TEXT', 'quote': 'Further local detail.'}
    value = response();value['anchors_a'].append('A:T001')
    assert len(validate(value, ls, {})['anchors']['A']) == 2
    value['anchors_a'].append('B:T000')
    with pytest.raises(ValueError, match='anchors_must_be_local_id_array'):
        validate(value, ls, {})


def test_caption_direction_checks_original_visual_endpoint():
    value = response('CAPTION_FOR');value['direction'] = 'A_TO_B'
    with pytest.raises(ValueError, match='caption_text_to_visual_required'):
        validate(value, lookups(), {})
    ls = lookups();ls['B']['B:V001'] = {'kind': 'VISUAL', 'crop': 'source.jpg'}
    value['anchors_b'] = ['B:V001'];value['observation_b'] = 'Original shows a control room.'
    assert validate(value, ls, {})['anchors']['B'][0]['crop'] == 'source.jpg'


def test_unresolved_article_still_has_both_routing_arms():
    ns = {nid: node(nid, document=('doc' if i < 8 else 'other'), article=None) for i, nid in enumerate('abcdefghijklmnop')}
    policies = {nid: {'eligible': True, 'members': [{'member_id': 'm', 'kind': 'atom', 'eligible': True}]} for nid in ns}
    views = [{'view_id': nid, 'node_id': nid, 'member_id': 'm', 'kind': 'source_text',
              'text': 'A specific project result.', 'char_start': 0, 'char_end': 26} for nid in ns]
    matrix = np.eye(len(ns), dtype=np.float32)
    _, selections, _, count = route_candidates(ns, policies, [], views, matrix)
    assert count == 16
    assert all(r['direct_targets'] == r['combined_targets'] and len(r['direct_targets']) == 12 for r in selections)


def test_retrieval_description_is_visual_and_cached_text_is_checked():
    n = node('a'); n['members'].append({'id': 'v', 'kind': 'visual', 'crop': 'original.jpg'})
    pol = {'a': {'members': [{'member_id': 'v', 'kind': 'visual', 'eligible': True}]}}
    views = [{'node_id': 'a', 'member_id': 'v', 'kind': 'generated_description', 'crop': 'original.jpg'}]
    ids, _ = node_vectors({'a': n}, pol, views, np.ones((1, 2)))
    assert ids == ['a']
    views[0]['crop'] = 'other.jpg'; views[0]['view_id'] = 'test'
    with pytest.raises(ValueError, match='visual_view_crop_mismatch'):
        node_vectors({'a': n}, pol, views, np.ones((1, 2)))
