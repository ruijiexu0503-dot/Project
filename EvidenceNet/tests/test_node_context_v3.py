import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_node_context_edges import node
from verify_node_context_v3 import verification_policy, source_spans, bind_spans, validate_v3
from verify_node_context import final_edges
from run_node_context_edges import write, jsonl


def value():
    return {'pair_id':'p','status':'ACCEPT','reason':'Specific concept correspondence',
            'relation_basis':'METHOD_MECHANISM','concept_a':'semantic segmentation','concept_b':'semantic segmentation',
            'evidence_role_a':'CONTENT','evidence_role_b':'CONTENT',
            'anchor_a':{'kind':'TEXT','member_id':'member','span_id':'A:member:000'},
            'anchor_b':{'kind':'VISUAL','member_id':'member','observation':'Convolution layers produce a pixel-wise output mask'}}


def fixture():
    a=node('a','Semantic segmentation\nassigns a class to each pixel.')
    b=node('b','The image shows a convolutional network.',True)
    ns={n['id']:n for n in [a,b]};pol=verification_policy(list(ns.values()))
    _,spans=source_spans(a,pol['a'],'A')
    return ns,pol,{'pair_id':'p','source':'a','target':'b'},{'A':spans,'B':{}}


def test_span_selection_preserves_raw_newlines_and_offsets():
    ns,pol,p,lookups=fixture();v=bind_spans(value(),lookups)
    assert '\n' in v['anchor_a']['quote']
    assert ns['a']['members'][0]['text'][v['anchor_a']['char_start']:v['anchor_a']['char_end']]==v['anchor_a']['quote']
    assert validate_v3(v,p,ns,pol)==[]


def test_anchors_cannot_select_other_endpoint_spans():
    _,_,_,lookups=fixture();v=value();v['anchor_a']['span_id']='B:member:000'
    with pytest.raises(ValueError,match='span_not_in_target_member'):bind_spans(v,lookups)


def test_formula_padding_removed_only_from_presentation():
    a=node('a',r'\Lambda(x)=p(x|signal)/p(x|noise) '+('~ '*500)+' (8)')
    pol=verification_policy([a]);members,spans=source_spans(a,pol['a'],'A')
    assert '~' not in str(members)
    assert len(spans)==2
    for s in spans.values():assert a['members'][0]['text'][s['char_start']:s['char_end']]==s['quote']


def test_primary_circular_logo_and_thin_navigation_blocked_but_content_diagram_kept():
    logo=node('logo','The image displays a circular logo for the organization.',True)
    nav=node('nav','The image displays a purple banner with navigation icons.',True)
    nav['members'][0]['boxes']=[[0,1042,738,1088]]
    content=node('content','The image shows a circular diagram explaining open science, with a logo at its center.',True)
    pol=verification_policy([logo,nav,content])
    assert not pol['logo']['eligible'] and not pol['nav']['eligible']
    assert pol['content']['eligible']


def test_final_gate_rejects_logo_even_when_model_says_content():
    ns,pol,p,lookups=fixture();v=bind_spans(value(),lookups)
    v['anchor_b']['observation']='The CERN logo visible in the corner'
    assert validate_v3(v,p,ns,pol)==['visual_furniture_anchor']


def test_pixel_mask_cannot_be_called_localization():
    ns,pol,p,lookups=fixture();v=bind_spans(value(),lookups);v['concept_b']='object localization'
    assert validate_v3(v,p,ns,pol)==['visual_concept_contradicts_observation']


def test_broad_similarity_not_an_allowed_relation_basis():
    ns,pol,p,lookups=fixture();v=bind_spans(value(),lookups);v['relation_basis']='SAME_TOPIC'
    assert validate_v3(v,p,ns,pol)==['relation_basis_invalid']


def test_task_juxtaposition_cannot_claim_explicit_comparison():
    ns,pol,p,lookups=fixture();v=bind_spans(value(),lookups)
    v['relation_basis']='DIRECT_COMPARISON';v['comparison_quote']=v['anchor_a']['quote']
    assert validate_v3(v,p,ns,pol)==['comparison_not_explicit']


@pytest.mark.parametrize('version',[3,4])
def test_final_edges_require_critic_confirmation_and_preserve_selected_occurrence(tmp_path,version):
    a=node('a','The same named project has measured a change.\n'*2)
    b=node('b','The named project measures the same physical change.')
    ns={n['id']:n for n in [a,b]};pol=verification_policy([a,b])
    pair={'pair_id':'p','source':'a','target':'b','scope':'cross_document','routes':[]}
    write(tmp_path/'manifest.json',{'verifier_version':version});write(tmp_path/'verification_eligibility.json',pol)
    jsonl(tmp_path/'verification_queue.jsonl',[pair])
    quote=a['members'][0]['text'].splitlines(keepends=True)[0]
    v={'pair_id':'p','status':'ACCEPT','reason':'Same specific measurement',
       'relation_basis':'SAME_MEASUREMENT','concept_a':'project change','concept_b':'project change',
       'evidence_role_a':'CONTENT','evidence_role_b':'CONTENT',
       'anchor_a':{'kind':'TEXT','member_id':'member','quote':quote,'char_start':len(quote)},
       'anchor_b':{'kind':'TEXT','member_id':'member','quote':b['members'][0]['text'],'char_start':0}}
    decision={'pair':{k:pair[k] for k in ['pair_id','source','target']},'verifier_version':version,'valid':True,'value':v}
    write(tmp_path/'context_decisions/p.json',decision)
    assert final_edges(tmp_path,[pair],ns)==[]
    decision['critic']={'status':'CONFIRM','reason':'Source measurement corresponds'}
    write(tmp_path/'context_decisions/p.json',decision)
    edges=final_edges(tmp_path,[pair],ns)
    assert edges[0]['anchor_a']['char_start']==len(quote)
