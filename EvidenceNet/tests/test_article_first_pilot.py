"""Source accounting and article constraints for the opt-in raw-block-first diagnostic."""
import copy
from pathlib import Path
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_article_first_pilot import raw_input, validate_raw, assemble, candidates, validate_nodes


def fixture():
    def atom(aid, kind, text, order, box):
        return dict(atom_id=aid, atom_type=kind, layout_role='para', deepseek_order=order,
                    text_fragments=[dict(fragment_id=aid+'::F',text=text)],
                    geometry_members=[dict(bbox=box)])
    rep=dict(document_id='mag',page='page_0001',atoms=[
        atom('h','heading','Story one',0,[0,0,100,10]),
        atom('a','text','The method continues',1,[0,10,100,20]),
        atom('b','text','into the next column.',2,[0,20,100,30]),
        atom('c','caption','This parser-caption is actually a substantive narrative paragraph.',3,[0,30,100,40]),
        atom('d','text','A figure caption.',4,[0,50,100,60]),
        atom('e','text','Another independent article.',5,[150,10,250,20]),
        atom('f','text','NEWS ANALYSIS',6,[150,0,250,10]),
        atom('i','furniture','1',7,[0,100,10,110])],
        visual_bundles=[dict(visual_bundle_id=v,bbox=[x,60,x+40,90],geometry_members=[dict(bbox=[x,60,x+40,90])],
                            native_components=[dict(member_id=v+'::native')]) for v,x in [('v1',0),('v2',50),('logo',200)]])
    desc={v['visual_bundle_id']:dict(description='An original visual.',crop='crop.png',crop_sha256='hash') for v in rep['visual_bundles']}
    raw=raw_input(rep,desc)
    byid={v['source_id']:k for k,v in raw['block_lookup'].items()}
    roles={byid[a]:r for a,r in [('a','BODY'),('b','BODY'),('c','BODY'),('d','CAPTION'),('e','BODY'),('f','PAGE_CONTEXT'),('v1','VISUAL'),('v2','VISUAL'),('logo','PAGE_CONTEXT')]}
    value=dict(groups=[dict(id='g1',kind='article',nodes=[byid[a] for a in ['a','b','c','d','v1','v2']],title_ids=['T001'],flows=[]),
                       dict(id='g2',kind='article',nodes=[byid['e']],title_ids=[],flows=[]),
                       dict(id='ctx',kind='page_context',nodes=[byid['f'],byid['logo']],title_ids=[],flows=[])],
               page_context_title_ids=[],unassigned_nodes=[],conflicted_nodes=[],roles=roles)
    return rep,desc,raw,byid,validate_raw(value,raw['payload'])


def test_roles_override_parser_caption_without_mutating_source_and_retain_titles():
    rep,desc,raw,labels,member=fixture()
    assert member['roles'][labels['c']]=='BODY'
    assert rep['atoms'][3]['atom_type']=='caption'
    bad=copy.deepcopy(member);bad['roles'].pop(labels['c'])
    with pytest.raises(ValueError,match='cover every raw block'): validate_raw(bad,raw['payload'])
    bad=copy.deepcopy(member);bad['roles'][labels['f']]='BODY'
    with pytest.raises(ValueError,match='PAGE_CONTEXT'): validate_raw(bad,raw['payload'])


def test_assembly_preserves_every_source_once_and_can_combine_shared_caption_visuals():
    rep,desc,raw,l,member=fixture()
    pool=dict(pairs=[dict(candidate_id='P1',left=l['a'],right=l['b'])],
              captions=[dict(candidate_id='C1',caption=l['d'],visual=l['v1']),dict(candidate_id='C2',caption=l['d'],visual=l['v2'])])
    dec=dict(pairs=[dict(candidate_id='P1',decision='CONTINUATION')],
             captions=[dict(candidate_id=c,decision='ATTACH') for c in ['C1','C2']])
    validate_nodes(dec,pool)
    nodes,excluded,checks=assemble(raw,member,pool,dec,rep,desc,'mag/page_0001')
    assert all(checks.values())
    figure=next(n for n in nodes if n['source_visual_bundle_ids'])
    assert set(figure['source_visual_bundle_ids'])=={'v1','v2'}
    assert figure['source_atom_ids']==['d']
    assert next(n for n in nodes if 'c' in n['source_atom_ids'])['unit_type']=='TEXT'
    assert next(n for n in nodes if 'a' in n['source_atom_ids'])['source_atom_ids']==['a','b']
    assert {'f','logo','h','i'} <= {r['source_id'] for r in excluded}


def test_even_corrupted_candidates_cannot_merge_different_articles_or_attach_body():
    rep,desc,raw,l,member=fixture()
    pool=dict(pairs=[dict(candidate_id='P1',left=l['a'],right=l['e'])],captions=[])
    with pytest.raises(ValueError,match='article ownership'):
        assemble(raw,member,pool,dict(pairs=[dict(candidate_id='P1',decision='CONTINUATION')],captions=[]),rep,desc,'task')
    pool=dict(pairs=[],captions=[dict(candidate_id='C1',caption=l['c'],visual=l['v1'])])
    with pytest.raises(ValueError,match='actual captions'):
        assemble(raw,member,pool,dict(pairs=[],captions=[dict(candidate_id='C1',decision='ATTACH')]),rep,desc,'task')


def test_candidate_pool_uses_only_same_article_and_checked_roles():
    rep,desc,raw,l,member=fixture()
    vectors={n:[1.,0.] for n in raw['block_lookup']}
    pool=candidates(raw,member,rep,vectors,(300,120))
    assert all(r['right']!=l['e'] for r in pool['pairs'])
    assert all(r['caption']==l['d'] and r['visual'] in {l['v1'],l['v2']} for r in pool['captions'])
    assert pool['captions']


def test_unresolved_content_retained_as_evidence_but_not_assigned_or_composed():
    rep,desc,raw,l,member=fixture()
    member['groups'][0]['nodes'].remove(l['c']);member['unassigned_nodes']=[l['c']];member['roles'][l['c']]='UNRESOLVED'
    validate_raw(member,raw['payload'])
    nodes,excluded,checks=assemble(raw,member,dict(pairs=[],captions=[]),dict(pairs=[],captions=[]),rep,desc,'task')
    node=next(n for n in nodes if n['source_atom_ids']==['c'])
    assert node['assignment_status']=='UNRESOLVED' and node['article_id'] is None
    assert all(checks.values()) and 'c' not in {r['source_id'] for r in excluded}
