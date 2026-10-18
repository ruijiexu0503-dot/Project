from pathlib import Path
import sys
from copy import deepcopy
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_article_first_pilot import fixture
from compare_article_reading_order import (validate_roles,validate_member,compose_candidates,validate_composition,
    assemble,evaluate,snapshot,report)


def test_frozen_common_roles_cannot_change_between_arms():
    rep,desc,raw,l,member=fixture()
    assert validate_roles(dict(roles=member['roles']),raw['payload'])['roles']==member['roles']
    bad=deepcopy(member);bad['roles'][l['c']]='CAPTION'
    with pytest.raises(ValueError,match='roles frozen'):
        validate_member(bad,raw['payload'],member['roles'])


def test_backwards_source_path_assembles_in_reading_not_parser_order():
    rep,desc,raw,l,member=fixture()
    # A parser-later block ends mid-sentence, and actually continues into parser-earlier a.
    rep['atoms'][3]['text_fragments'][0]['text']='This paragraph explains'
    raw['payload']['nodes'][2]['members'][0]['text']='This paragraph explains'
    pool=dict(pairs=[dict(candidate_id='P1',left=l['c'],right=l['a']),dict(candidate_id='P2',left=l['a'],right=l['b'])],figures=[])
    dec=dict(pairs=[dict(candidate_id=p,decision='CONTINUATION') for p in ['P1','P2']],figures=[])
    validate_composition(dec,pool)
    nodes,excluded,checks=assemble(raw,member,pool,dec,rep,desc,'task')
    merged=next(n for n in nodes if len(n['source_atom_ids'])==3)
    assert merged['source_atom_ids']==['c','a','b']
    assert merged['plain_text'].startswith('This paragraph explains\nThe method')
    assert all(checks.values())


def test_partial_figure_is_retained_separately_and_complete_scope_can_group_crops():
    rep,desc,raw,l,member=fixture()
    pool=dict(pairs=[],figures=[dict(caption=l['d'],visuals=[dict(visual=l['v1']),dict(visual=l['v2'])])])
    partial=dict(pairs=[],figures=[dict(caption=l['d'],visuals=[l['v1']],scope='PARTIAL')])
    validate_composition(partial,pool)
    nodes,_,_=assemble(raw,member,pool,partial,rep,desc,'task')
    assert all(not(n['source_atom_ids'] and n['source_visual_bundle_ids']) for n in nodes)
    complete=dict(pairs=[],figures=[dict(caption=l['d'],visuals=[l['v1'],l['v2']],scope='COMPLETE')])
    validate_composition(complete,pool)
    nodes,_,_=assemble(raw,member,pool,complete,rep,desc,'task')
    figure=next(n for n in nodes if n['unit_type']=='COMPOSITE')
    assert set(figure['source_visual_bundle_ids'])=={'v1','v2'}
    bad=deepcopy(complete);bad['figures'][0]['visuals'].append(l['logo'])
    with pytest.raises(ValueError,match='candidate ownership'):validate_composition(bad,pool)


def test_both_arms_have_same_candidate_and_assembly_rules():
    rep,desc,raw,l,member=fixture()
    order=dict(flows=[dict(kind='body',nodes=[l['a'],l['b'],l['c']])],unsequenced=[])
    vectors={n:[1.,0.] for n in raw['block_lookup']}
    a,flows,cross=compose_candidates(raw,member,order,vectors,(300,120))
    reversedraw=deepcopy(raw);reversedraw['payload']['nodes'].reverse()
    b,_,_=compose_candidates(reversedraw,member,order,vectors,(300,120))
    assert a==b and len(a['pairs'])==1
    assert a['pairs'][0]['left']==l['a'] and a['pairs'][0]['right']==l['b']


def test_evaluation_distinguishes_wrong_article_edges_and_partial_figures():
    rep,desc,raw,l,member=fixture()
    nodes,excluded,_=assemble(raw,member,dict(pairs=[],figures=[]),dict(pairs=[],figures=[]),rep,desc,'task')
    ref=dict(article_groups=[['a','b','c','d','v1','v2'],['e']],reading_chains=[['a','b','c']],
             excluded=['f','logo'],continuations=[['a','b']],forbidden_continuations=[['c','e']],figures={'d':['v1','v2']})
    order=dict(flows=[dict(kind='body',nodes=[l['a'],l['e'],l['b'],l['c']])],unsequenced=[])
    result=evaluate(raw,member,order,nodes,excluded,ref)
    assert result['article_pair_confusion'].get('fp',0)==0
    assert result['raw_cross_article_adjacencies']==2
    assert result['reading_recovered']==1 # b->c; no shortcut from a across e.
    assert result['figure_scope_exact']==0
    assert result['excluded_correct']==2
    snap=snapshot(raw,member,order,nodes)
    assert ('a','b') not in snap['reading_edges']


def test_missing_runs_are_not_reported_as_complete(tmp_path):
    assert report(tmp_path)['complete'] is False
    assert report(tmp_path)['available_results']==0
