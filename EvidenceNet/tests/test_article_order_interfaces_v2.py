from pathlib import Path
import sys
from copy import deepcopy
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_article_first_pilot import fixture
from compare_article_reading_order_v2 import task_payload,validate_member,validate_order,assemble


def member_answer(raw,member):
    payload=task_payload(raw['payload'],member['roles']);expected={n['label'] for n in payload['nodes']}
    value=deepcopy(member);value.pop('roles')
    for g in value['groups']:g['nodes']=[n for n in g['nodes'] if n in expected]
    value['groups']=[g for g in value['groups'] if g['nodes']]
    return value


def test_uncertain_article_ownership_does_not_force_content_role_change():
    rep,desc,raw,l,member=fixture();answer=member_answer(raw,member)
    answer['groups'][0]['nodes'].remove(l['c']);answer['unassigned_nodes']=[l['c']]
    result=validate_member(answer,raw['payload'],member['roles'])
    assert result['roles'][l['c']]=='BODY' and l['c'] in result['unassigned_nodes']
    nodes,_,checks=assemble(raw,result,dict(pairs=[],figures=[]),dict(pairs=[],figures=[]),rep,desc,'task')
    node=next(n for n in nodes if n['source_atom_ids']==['c'])
    assert node['article_id'] is None and node['source_block_roles'][l['c']]=='BODY'
    assert all(checks.values())


def test_known_metadata_in_unsequenced_is_audited_without_weakening_flow_checks():
    rep,desc,raw,l,member=fixture();roles=member['roles']
    body=[n for n in roles if roles[n]=='BODY'];caps=[n for n in roles if roles[n]=='CAPTION']
    visuals=[n for n in roles if roles[n]=='VISUAL'];meta=[n for n in roles if roles[n]=='PAGE_CONTEXT']
    value=dict(flows=[dict(kind='body',nodes=body),dict(kind='caption',nodes=caps)],unsequenced=visuals+meta)
    normalized=validate_order(value,raw['payload'],roles)
    assert normalized['excluded_unsequenced']==meta
    assert normalized['unsequenced']==visuals
    assert value['unsequenced']==visuals+meta
    bad=deepcopy(value);bad['flows'][0]['nodes'].append(meta[0])
    with pytest.raises(ValueError):validate_order(bad,raw['payload'],roles)
    bad=deepcopy(value);bad['unsequenced'].append('UNKNOWN')
    with pytest.raises(ValueError,match='unknown'):validate_order(bad,raw['payload'],roles)


def test_page_chrome_eligibility_can_be_excluded_without_retyping_source_visual():
    rep,desc,raw,l,member=fixture();member['roles'][l['logo']]='VISUAL'
    answer=member_answer(raw,member)
    result=validate_member(answer,raw['payload'],member['roles'])
    assert result['roles'][l['logo']]=='VISUAL'
    nodes,excluded,checks=assemble(raw,result,dict(pairs=[],figures=[]),dict(pairs=[],figures=[]),rep,desc,'task')
    logo=next(r for r in excluded if r['source_id']=='logo')
    assert logo['source_role']=='VISUAL' and logo['role']=='PAGE_CONTEXT'
    assert all('logo' not in n['source_visual_bundle_ids'] for n in nodes)
    assert all(checks.values())


def test_missing_body_and_duplicate_titles_remain_real_validation_errors():
    rep,desc,raw,l,member=fixture();answer=member_answer(raw,member)
    answer['groups'][0]['nodes'].remove(l['c'])
    with pytest.raises(ValueError,match='missing=.*'+l['c']):validate_member(answer,raw['payload'],member['roles'])
    answer=member_answer(raw,member);answer['page_context_title_ids']=['T001']
    with pytest.raises(ValueError,match='title duplicate/extra=.*T001'):
        validate_member(answer,raw['payload'],member['roles'])
