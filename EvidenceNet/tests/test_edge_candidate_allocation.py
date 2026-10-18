from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from repair_edge_candidate_allocation import eligible_views, references, unique_escape, reserve_references, key


def policy(member, kind='atom', eligible=True):
    return {'eligible': eligible, 'members': [{'member_id': member, 'kind': kind, 'eligible': eligible}]}


def test_excluded_views_and_generated_provenance():
    views = [{'node_id': n, 'member_id': 'm', 'member_kind': k, 'source_status': 'ORIGINAL_TEXT_LINE_STRUCTURE'}
             for n, k in [('footer', 'atom'), ('image', 'visual'), ('text', 'atom')]]
    policies = {'footer': policy('m', eligible=False), 'image': policy('m', 'visual'), 'text': policy('m')}
    cleaned, indices = eligible_views(views, policies)
    assert indices == [1, 2]
    assert cleaned[0]['source_status'] == 'GENERATED_DESCRIPTION_FOR_RETRIEVAL_ONLY'
    assert views[1]['source_status'] == 'ORIGINAL_TEXT_LINE_STRUCTURE'


def test_reference_direction_scope_and_ambiguity():
    def node(nid, document, text, caption=False):
        return {'id': nid, 'document': document, 'article_id': document + '::ARTICLE', 'members': [
            {'id': 'm', 'kind': 'atom', 'text': text, 'type': 'caption' if caption else 'text', 'role': 'cap' if caption else 'para'}]}
    nodes = {'a': node('a', 'doc', 'Shown in Fig. 3 (b).'), 'b': node('b', 'doc', 'Fig. 3. Architecture.', True),
             'c': node('c', 'other', 'Fig. 3. Different architecture.', True)}
    policies = {n: policy('m') for n in nodes}
    found = references(nodes, policies)
    assert len(found) == 1 and key(found[0]) == ('a', 'b')
    anchor = found[0]['reference_anchors'][0]
    assert anchor['referring_node'] == 'a' and anchor['target_node'] == 'b'
    assert nodes['a']['members'][0]['text'][anchor['char_start']:anchor['char_end']] == anchor['quote']
    nodes['d'] = node('d', 'doc', 'Figure 3: Another caption.', True)
    policies['d'] = policy('m')
    assert references(nodes, policies) == []
    del nodes['d']
    nodes['b']['members'][0]['kind'] = 'visual'
    policies['b'] = policy('m', 'visual')
    assert references(nodes, policies) == []


def test_hierarchical_figure_number_is_not_integer_prefix():
    nodes = {'a': {'id': 'a', 'document': 'd', 'article_id': 'article', 'members': [
        {'id': 'm', 'kind': 'atom', 'type': 'text', 'text': 'See figure\n6.1 for subimages.'}]},
        'b': {'id': 'b', 'document': 'd', 'article_id': 'article', 'members': [
            {'id': 'm', 'kind': 'atom', 'type': 'caption', 'text': 'Figure 6: ROC curves.'}]}}
    policies = {n: policy('m') for n in nodes}
    assert references(nodes, policies) == []
    nodes['b']['members'][0]['text'] = 'Figure 6.1: Subimages.'
    assert references(nodes, policies)[0]['reference_anchors'][0]['number'] == '6.1'


def test_escape_spends_slots_on_new_pairs_with_fixed_budget():
    def p(a, b, score):
        return dict(source=a, target=b, source_article='aa', target_article='bb',
                    retrieval_score=score, selection_routes=['article_routed'])
    primary = [p('a', 'b', 1), p('c', 'd', .9), p('e', 'f', .8)]
    pool = primary + [p('g', 'h', .7), p('i', 'j', .6)]
    selected = unique_escape(pool, primary, budget=3, escape_budget=2)
    assert len(selected) == len({key(p) for p in selected}) == 3
    assert {key(p) for p in selected if p['selection_routes'] == ['unique_global_escape']} == {('g', 'h'), ('i', 'j')}
    reserved = reserve_references(selected, [deepcopy(primary[1])], budget=3, reference_budget=1)
    assert len(reserved) == len({key(p) for p in reserved}) == 3
    assert key(reserved[0]) == ('c', 'd')
    assert {key(p) for p in selected if p['selection_routes'] == ['unique_global_escape']} <= {key(p) for p in reserved}
