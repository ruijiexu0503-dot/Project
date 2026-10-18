import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_node_context_edges import node
from verify_node_context_v3 import verification_policy
from node_context_coreference import validate_v4, duplicate_caption


def fixture():
    a=node('a','Event-X was observed as a coalescing binary with SNR 24.')
    b=node('b','Event-X parameters were inferred from a compact binary signal.')
    ns={n['id']:n for n in [a,b]};pol=verification_policy([a,b]);pair={'pair_id':'p','source':'a','target':'b'}
    v={'pair_id':'p','status':'ACCEPT','reason':'Complementary facts about one event',
       'relation_basis':'SAME_NAMED_ENTITY','concept_a':'observed binary event','concept_b':'parameter inference',
       'shared_entity':'Event-X','entity_type':'EVENT','entity_fact_a':'A binary was observed with SNR 24.',
       'entity_fact_b':'Parameters were inferred from its signal.',
       'evidence_role_a':'CONTENT','evidence_role_b':'CONTENT',
       'anchor_a':{'kind':'TEXT','member_id':'member','quote':a['members'][0]['text']},
       'anchor_b':{'kind':'TEXT','member_id':'member','quote':b['members'][0]['text']}}
    return ns,pol,pair,v


def test_complementary_event_facts_are_allowed_without_equal_measurements():
    ns,pol,p,v=fixture();assert validate_v4(v,p,ns,pol)==[]


def test_shared_entity_cannot_come_from_unselected_member():
    ns,pol,p,v=fixture();v['shared_entity']='Event-Y'
    ns['b']['members'].append({'id':'other','kind':'atom','text':'Event-Y was also observed.'})
    assert validate_v4(v,p,ns,pol)==['shared_entity_not_in_both_anchors']


def test_generic_task_name_is_not_a_named_entity():
    ns,pol,p,v=fixture();v['shared_entity']='object detection'
    assert validate_v4(v,p,ns,pol)==['generic_topic_is_not_entity']


def test_entity_names_use_word_boundaries():
    ns,pol,p,v=fixture();v['shared_entity']='Event'
    # Hyphenated entity names can include ordinary word boundaries; avoid numeric prefix matches.
    v['shared_entity']='Event-X1'
    assert validate_v4(v,p,ns,pol)==['shared_entity_not_in_both_anchors']


def test_event_requires_facts_at_both_endpoints():
    ns,pol,p,v=fixture();v['entity_fact_b']='Event-X'
    assert validate_v4(v,p,ns,pol)==['entity_fact_missing']


def test_overlapping_caption_duplicates_excluded_but_separate_panels_not():
    a=node('a','Fig. 1. Limit on stop pair production with decays through top quarks and LSPs.')
    b=node('b','Fig. 1. Limits on stop pair production with decays through top quarks and LSPS.')
    for n in [a,b]:n.update(document='doc',page='1')
    a['members'][0]['boxes']=[[1042,408,1265,463]]
    b['members'][0]['boxes']=[[1051,407,1149,666]]
    pol=verification_policy([a,b]);assert duplicate_caption(a,b,pol)
    b['members'][0]['boxes']=[[0,0,100,100]]
    assert not duplicate_caption(a,b,pol)
    b['members'][0]['boxes']=a['members'][0]['boxes'];b.update(page='2')
    assert not duplicate_caption(a,b,pol)
