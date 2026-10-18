import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from repair_remaining_edge_candidates import (
    citation_entities, reference_context_lane, contiguous_reading_lane, fixed_budget, pair_key)


def node(nid, text, article='a', page=1, order=1, bbox=(0, 0, 100, 100)):
    return {'id': nid, 'text': text, 'document': 'd', 'article_id': article,
            'page': page, 'min_order': order, 'bbox': list(bbox), 'members': []}


def policies(nodes):
    return {nid: {'eligible': True, 'members': []} for nid in nodes}


def test_article_local_citation_alias_resolution():
    nodes = {'definition': node('definition', 'DCRNN [8] uses diffusion.'),
             'citation': node('citation', 'In [8], forward diffusion is used.'),
             'other': node('other', 'In [8], unrelated.', article='b')}
    entities, provenance = citation_entities(nodes)
    assert 'DCRNN' in entities['citation'] and provenance['citation']['DCRNN'][0]['source_node'] == 'definition'
    assert 'DCRNN' not in entities['other']


def test_reference_context_is_bounded_and_same_page():
    nodes = {str(i): node(str(i), 'text', order=i) for i in range(1, 10)}
    refs = [{'reference_anchors': [{'referring_node': '9', 'target_node': '1',
              'reference_kind': 'figure', 'number': '4', 'quote': 'Fig. 4', 'member_id': 'm'}]}]
    result = reference_context_lane(refs, nodes, policies(nodes), previous_orders=6)
    assert {pair_key(p) for p in result} == {tuple(sorted((str(i), '1'))) for i in range(3, 9) if i != 9 and i != 1}


def test_touching_same_column_reading_candidate():
    nodes = {'a': node('a', 'force feedback', order=20, bbox=(10, 0, 100, 50)),
             'b': node('b', 'torque motors', order=21, bbox=(10, 50, 100, 90)),
             'c': node('c', 'other column', order=22, bbox=(200, 90, 300, 130))}
    result = contiguous_reading_lane(nodes, policies(nodes))
    assert [pair_key(p) for p in result] == [('a', 'b')]


def test_fixed_budget_is_unique_and_deterministic():
    pair = lambda a,b:{'source':a,'target':b}
    selected = fixed_budget([[pair('a','b'),pair('b','a')]], [pair('c','d'),pair('e','f')], budget=3)
    assert [pair_key(p) for p in selected] == [('a','b'),('c','d'),('e','f')]
