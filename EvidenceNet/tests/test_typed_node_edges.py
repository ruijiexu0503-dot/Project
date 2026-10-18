import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_node_context_edges import node
from run_typed_node_edges import entities, catalog, select_queue, validate_response, judge
from verify_node_context_v3 import verification_policy


def test_entity_index_uses_source_atoms_not_visual_descriptions():
    a = node('a', 'GW150914 was observed by LIGO in the detector frame.')
    b = node('b', 'GW150914 was observed by LIGO.', True)
    policies = verification_policy([a, b])
    assert {'gw150914', 'ligo'} <= {e['key'] for e in entities(a, policies['a'])}
    assert entities(b, policies['b']) == []
    for e in entities(a, policies['a']):
        assert a['members'][0]['text'][e['char_start']:e['char_end']] == e['name']


def test_catalog_preserves_raw_context_and_offsets(tmp_path):
    a = node('a', 'Detector frame masses: ' + 'measurement\n' * 100)
    policies = verification_policy([a])
    public, lookup = catalog(a, policies['a'], 'A', tmp_path)
    assert len(public) > 1
    for anchor in lookup.values():
        assert a['members'][0]['text'][anchor['char_start']:anchor['char_end']] == anchor['quote']
    anchors = list(lookup.values())
    assert anchors[1]['char_start'] < anchors[0]['char_end']


def test_queue_preserves_scope_strata_and_prefers_unrepresented_nodes():
    nodes = {n: {'visual_count': 0} for n in ['a', 'b', 'c', 'd', 'e', 'f']}
    def pair(pid, a, b, scope='intra_article'):
        return {'pair_id': pid, 'source': a, 'target': b, 'scope': scope,
                'relation_type': 'RELATED_CONTENT', 'rank_signal': 1}
    candidates = [pair('old', 'a', 'b'), pair('busy', 'a', 'c'),
                  pair('fresh', 'd', 'e'), pair('cross', 'a', 'f', 'cross_document')]
    queue = select_queue(candidates, nodes, [candidates[0]], limit=3)
    assert {p['pair_id'] for p in queue} == {'old', 'fresh', 'cross'}


def test_rejection_also_requires_actual_endpoint_anchors():
    lookups = {'A': {'A:T000': {'kind': 'TEXT'}}, 'B': {'B:T000': {'kind': 'TEXT'}}}
    value = {'status': 'REJECT', 'reason': 'Different events.', 'direction': 'SYMMETRIC',
             'anchor_a': 'A:T000', 'anchor_b': 'B:T000'}
    assert validate_response(value, lookups, 'SAME_ENTITY') == []
    value['anchor_b'] = 'A:T000'
    assert validate_response(value, lookups, 'SAME_ENTITY') == ['anchor_not_in_endpoint_catalog']
    value['anchor_b'] = {}
    assert validate_response(value, lookups, 'SAME_ENTITY') == ['anchor_not_in_endpoint_catalog']


def test_format_failure_remains_pending_and_blind_repeat_changes_task():
    class Model:
        def __init__(self): self.prompts = []
        def generate_raw_with_images(self, system, prompt, images, tokens):
            self.prompts.append(prompt)
            return type('Result', (), {'raw': '{}'})()
    model = Model()
    pair = {'relation_type': 'EXPLAINS', 'entity_hints': []}
    result = judge(model, pair, [], {'A': {}, 'B': {}}, [])
    assert result['status'] == 'FORMAT_PENDING'
    first = model.prompts[0]
    judge(model, pair, [], {'A': {}, 'B': {}}, [], audit=True)
    assert model.prompts[2] != first
    assert 'alternative interpretation' in model.prompts[2]
