import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_article_bridge_pilot import literal_span, subject_key, validate_mentions, validate_decision, route


def anchor(text='GW150914 source-frame masses', node='a', article='one'):
    return {'kind': 'TEXT', 'quote': text, 'char_start': 17, 'char_end': 17 + len(text),
            'node_id': node, 'article_id': article, 'member_id': 'm', 'member_sha256': 'hash'}


def test_normalized_mention_preserves_original_offsets_and_spelling():
    text = 'The AHEAD\n project is described here.'
    lo, hi = literal_span(text, 'AHEAD project')
    assert text[lo:hi] == 'AHEAD\n project'
    assert subject_key('PROJECT', text[lo:hi]) == 'PROJECT:ahead project'
    with pytest.raises(ValueError, match='mention_not_in_original'):
        literal_span('Generic LIGO detection threshold', 'GW150914')


def test_bad_record_does_not_discard_other_source_supported_mentions():
    good = {'kind': 'EVENT', 'source_mention': 'GW150914', 'evidence_id': 'N:T000',
            'role': 'estimates_parameters', 'aspect': 'source-frame masses'}
    wrong = {**good, 'source_mention': 'GW170817'}
    result = validate_mentions({'mentions': [wrong, good]}, {'N:T000': anchor()})
    assert len(result['record_errors']) == 1
    assert result['mentions'][0]['anchor']['quote'] == 'GW150914'
    assert result['mentions'][0]['anchor']['char_start'] == 17


def decision():
    return {'status': 'ACCEPT', 'subject_id': 'EVENT:gw150914', 'reason': 'Same identified event.',
            'source_evidence_ids': ['A:T000'], 'target_evidence_ids': ['B:T000'],
            'source_aspect': 'detection', 'target_aspect': 'source-frame masses'}


def test_context_cannot_replace_either_endpoint_and_missing_index_is_unresolved():
    anchors = {'A:T000': anchor(), 'B:T000': anchor(node='b', article='two')}
    v = decision()
    bound = validate_decision(v, anchors, ['EVENT:gw150914'])
    assert bound['target_anchors'][0]['node_id'] == 'b'
    v['target_evidence_ids'] = ['A:T000']
    with pytest.raises(ValueError, match='endpoint_anchor'):
        validate_decision(v, anchors, ['EVENT:gw150914'])
    v = decision(); v['status'] = 'REJECT'
    with pytest.raises(ValueError, match='missing_binding_is_unresolved'):
        validate_decision(v, anchors, [])


def test_budget_preserves_global_fallback_and_excludes_same_article():
    ids = ['a', 'local'] + [f'b{i}' for i in range(12)]
    mapping = {nid: nid for nid in ids}; mapping['local'] = 'a'
    ranks = {nid: [other for other in ids if other != nid] for nid in ids}
    bindings = [{'node_id': nid, 'subject_id': 'EVENT:gw150914', 'role': 'reports_detection'}
                for nid in ['a'] + [f'b{i}' for i in range(6, 12)]]
    selections, pairs, _ = route({}, mapping, ids, ranks, bindings)
    selected = next(r for r in selections if r['source'] == 'a')
    assert len(selected['global_targets']) == len(selected['subject_targets']) == 8
    assert {'b0', 'b1', 'b2', 'b3'} <= set(selected['subject_targets'])
    assert 'b8' in selected['subject_targets']
    assert 'local' not in selected['subject_targets']
    assert not any(p['source'] == 'a' and p['target'] == 'local' for p in pairs)


def test_background_never_promotes_article_membership_to_event_node_binding():
    mapping = {'a': 'one', 'generic': 'two', 'event': 'three'}
    ranks = {'a': ['generic', 'event'], 'generic': ['a', 'event'], 'event': ['a', 'generic']}
    bindings = [{'node_id': 'a', 'subject_id': 'EVENT:gw150914', 'role': 'reports_detection'},
                {'node_id': 'generic', 'subject_id': 'EVENT:gw150914', 'role': 'background'},
                {'node_id': 'event', 'subject_id': 'EVENT:gw150914', 'role': 'tests_prediction'}]
    _, pairs, index = route({}, mapping, list(mapping), ranks, bindings)
    assert not index['generic']
    assert next(p for p in pairs if set([p['source'], p['target']]) == {'a', 'generic'})['shared_subject_ids'] == []
    assert index['event'].keys() & index['a'].keys() == {'EVENT:gw150914'}


def test_unique_figure_reference_is_article_scoped_and_ambiguity_stays_unresolved():
    from run_article_bridge_pilot import unique_explicit_references
    def n(nid, text, article):
        return {'id': nid, 'document': 'doc', 'page': 'page_0001', 'article_id': article,
                'text': text, 'visual_count': 0, 'members': [{'id': 'm', 'kind': 'atom', 'text': text}]}
    nodes = {'source': n('source', 'GW150914 masses are shown in Fig. 1.', 'one'),
             'figure': n('figure', 'FIG. 1. Posterior source-frame masses.', 'one'),
             'other': n('other', 'FIG. 1. Unrelated project.', 'two')}
    policies = {nid: {'eligible': True, 'members': [{'member_id': 'm', 'kind': 'atom', 'eligible': True}]} for nid in nodes}
    refs, issues = unique_explicit_references(nodes, policies)
    assert [(r['source'], r['target']) for r in refs] == [('source', 'figure')]
    nodes['other']['article_id'] = 'one'
    refs, issues = unique_explicit_references(nodes, policies)
    assert not refs
    assert any(issue['reason'] == 'ambiguous_target' for issue in issues)


def test_verifier_binds_nested_catalog_anchors_without_context_substitution(tmp_path, monkeypatch):
    import run_article_bridge_pilot as pilot
    pair = {'source': 'a', 'target': 'b', 'pair_id': 'test', 'cohort': 'frozen_development'}
    pilot.jsonl(tmp_path / 'verification_queue.jsonl', [pair])
    pilot.write(tmp_path / 'proposal_manifest.json', {'queue_sha256': pilot.sha(tmp_path / 'verification_queue.jsonl')})
    nested = {'A': {'A:T000': anchor()}, 'B': {'B:T000': anchor(node='b', article='two')}}
    monkeypatch.setattr(pilot, 'request_targets', lambda *args: ([], nested, []))
    monkeypatch.setattr(pilot, 'cached_call', lambda model, out, name, prompt, images, validate, budget:
                        {'valid': True, 'bound': validate(decision()), 'errors': []})
    bindings = {'a': {'EVENT:gw150914': {'binding_id': 'M0'}}, 'b': {'EVENT:gw150914': {'binding_id': 'M1'}}}
    result = pilot.verify(None, tmp_path, {}, {}, bindings)
    assert result[0]['decision']['source_anchors'][0]['node_id'] == 'a'
    assert result[0]['decision']['target_anchors'][0]['node_id'] == 'b'
