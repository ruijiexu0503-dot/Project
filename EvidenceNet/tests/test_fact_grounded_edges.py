import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_fact_grounded_edges import validate_facts, validate_relation, endpoint_facts, extract_node
from test_node_context_edges import node
from verify_node_context_v3 import verification_policy


def fact():
    return {'id': 'F000', 'subject': 'LIGO', 'subject_kind': 'ORGANIZATION',
            'predicate': 'operates detectors', 'qualifiers': '', 'observation': '',
            'evidence_ids': ['N:T000'], 'subject_evidence_id': 'N:T000'}


def lookups():
    return {'A': {'A:T000': {'kind': 'TEXT', 'quote': 'LIGO operates detectors.'}},
            'B': {'B:T000': {'kind': 'TEXT', 'quote': 'LIGO observes GW150914.'}}}


def positive(kind='SAME_EVENT', status='ACCEPT'):
    return {'status': status, 'relation_type': kind, 'direction': 'SYMMETRIC',
            'reason': 'Both endpoint facts refer to the same occurrence.',
            'fact_a': 'F000', 'fact_b': 'F000', 'anchor_a': 'A:T000', 'anchor_b': 'B:T000'}


def test_rejection_does_not_require_a_nonexistent_direction():
    assert validate_relation({'status': 'REJECT', 'reason': 'Different events.', 'direction': 'NONE'}, lookups()) == {'anchors': {}}


def test_institution_cannot_be_promoted_to_specific_event():
    fs = {label: endpoint_facts({'supported_facts': [fact()]}, label) for label in ['A', 'B']}
    with pytest.raises(ValueError, match='identity_subject_kind_mismatch'):
        validate_relation(positive(), lookups(), fs)


def test_organization_link_is_saved_only_as_index_context():
    with pytest.raises(ValueError, match='organization_context_is_index_only'):
        validate_relation(positive('ORGANIZATION_CONTEXT'), lookups())
    assert validate_relation(positive('ORGANIZATION_CONTEXT', 'INDEX_ONLY'), lookups())['anchors']


def test_fact_subject_requires_its_own_source_mention():
    with pytest.raises(ValueError, match='subject_not_in_source'):
        validate_facts({'facts': [fact()]}, {'N:T000': {'kind': 'TEXT', 'quote': 'A general observatory operates detectors.'}})


def test_fact_anchor_must_support_the_selected_endpoint_fact():
    fs = {label: endpoint_facts({'supported_facts': [{**fact(), 'subject_kind': 'EVENT'}]}, label) for label in ['A', 'B']}
    ls = lookups();ls['A']['A:T001'] = {'kind': 'TEXT', 'quote': 'An unrelated claim.'}
    v = positive();v['anchor_a'] = 'A:T001'
    with pytest.raises(ValueError, match='anchor_not_supporting_selected_fact'):
        validate_relation(v, ls, fs)


def test_endpoint_id_mapping_does_not_mutate_independent_extraction():
    record = {'supported_facts': [fact()]};old = copy.deepcopy(record)
    mapped = endpoint_facts(record, 'B')
    assert mapped[0]['evidence_ids'] == ['B:T000']
    assert mapped[0]['subject_evidence_id'] == 'B:T000'
    assert record == old


def test_caption_requires_original_visual_at_other_endpoint():
    v = positive('CAPTION_FOR');v['direction'] = 'A_TO_B'
    with pytest.raises(ValueError, match='caption_requires_text_to_original_visual'):
        validate_relation(v, lookups())


def test_unsupported_fact_is_excluded_before_partner_is_seen(tmp_path):
    n = node('a', 'LIGO operates detectors to observe gravitational waves.')
    policies = verification_policy([n])
    class Model:
        prompts = []
        replies = [{'facts': [fact()]}, {'checks': [{'fact_id': 'F000', 'status': 'UNSUPPORTED', 'reason': 'Test negative support decision.'}]}]
        def generate_raw_with_images(self, system, prompt, images, tokens):
            self.prompts.append(prompt)
            return type('Result', (), {'raw': json.dumps(self.replies.pop(0))})()
    model = Model();record = extract_node(model, n, policies['a'], tmp_path)
    assert record['status'] == 'READY'
    assert record['supported_facts'] == []
    assert len(model.prompts) == 2
    assert 'targets' not in model.prompts[0]
