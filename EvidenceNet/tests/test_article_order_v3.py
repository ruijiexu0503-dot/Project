from copy import deepcopy
from pathlib import Path
import json
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_article_reading_order_v3 as v3
from test_article_first_pilot import fixture


def test_quoted_term_is_candidate_but_independent_quotation_stays_blocked():
    assert v3.sentence_block('the social gathering known as a', '"moussen"\n- an annual fair') is None
    assert v3.sentence_block('It is called', '“the engine” — a mechanism') is None
    assert v3.sentence_block('open-source software and hardware,', '"The publication gives a solid framework') == 'new_quoted_paragraph'
    assert v3.sentence_block('This is a full sentence.', '"term" — a definition') == 'closed_sentence_or_list'


def test_quoted_continuation_reaches_candidates_and_preserves_source_when_merged(monkeypatch):
    rep,desc,raw,l,member=fixture()
    for atom in rep['atoms']:
        if atom['atom_id']=='a':atom['text_fragments'][0]['text']='It is known as a'
        if atom['atom_id']=='b':atom['text_fragments'][0]['text']='"moussen" — an annual gathering.'
    for node in raw['payload']['nodes']:
        if node['id']=='a':node['members'][0]['text']='It is known as a'
        if node['id']=='b':node['members'][0]['text']='"moussen" — an annual gathering.'
    monkeypatch.setattr(v3.base,'sentence_block',v3.sentence_block)
    order=dict(flows=[dict(kind='body',nodes=[l['a'],l['b'],l['c']])],unsequenced=[])
    vectors={n:[1.,0.] for n in raw['block_lookup']}
    pool,_,_=v3.compose_candidates(raw,member,order,vectors,(300,120))
    assert len(pool['pairs'])==1 and pool['pairs'][0]['right']==l['b']
    assert 'review_hint' in pool['pairs'][0]
    decision=dict(pairs=[dict(candidate_id=pool['pairs'][0]['candidate_id'],decision='CONTINUATION')],figures=[])
    nodes,_,checks=v3.v2.assemble(raw,member,pool,decision,rep,desc,'task')
    merged=next(n for n in nodes if n['source_atom_ids']==['a','b'])
    assert merged['plain_text']=='It is known as a\n"moussen" — an annual gathering.'
    assert all(checks.values())


def test_no_figure_task_or_model_call_when_candidates_empty(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Empty task must not invoke model')
    monkeypatch.setattr(v3, 'source_call', forbidden)
    raw=dict(payload=dict(nodes=[]))
    pool=dict(pairs=[],figures=[])
    rec=v3.split_call(None,tmp_path/'composition.json',v3.composition_prompt(raw,{},pool),[],
                     lambda x:v3.base.validate_composition(x,pool),100)
    assert rec['valid'] and rec['value']==dict(pairs=[],figures=[])
    assert rec['attempts']==[]
    assert set(rec['task_execution'].values())=={'deterministic_empty_candidate_task'}


def test_body_and_caption_tasks_reject_invented_rows_and_report_exact_ids():
    pool=dict(pairs=[dict(candidate_id='P1',left='a',right='b')],figures=[])
    with pytest.raises(ValueError,match='duplicate/extra=.*P2'):
        v3.validate_body(dict(pairs=[dict(candidate_id='P1',decision='CONTINUATION'),
                                    dict(candidate_id='P2',decision='SEPARATE')]),pool)
    with pytest.raises(ValueError,match='only'):
        v3.validate_body(dict(pairs=[],figures=[dict(caption='credit')]),pool)
    with pytest.raises(ValueError,match='duplicate/extra=.*credit'):
        v3.validate_figures(dict(figures=[dict(caption='credit')]),pool)


def test_bounded_body_task_does_not_expose_credit_labels(tmp_path, monkeypatch):
    rep,desc,raw,l,member=fixture()
    pool=dict(pairs=[dict(candidate_id='P1',left=l['a'],right=l['b'])],figures=[])
    calls=[]
    def fake(model,path,prompt,images,validator,tokens):
        calls.append(prompt)
        answer=validator(dict(pairs=[dict(candidate_id='P1',decision='CONTINUATION')]))
        return dict(valid=True,value=answer,attempts=[dict(raw=json.dumps(answer),valid=True)])
    monkeypatch.setattr(v3,'source_call',fake)
    result=v3.split_call(None,tmp_path/'composition.json',v3.composition_prompt(raw,member,pool),[],
                         lambda x:v3.base.validate_composition(x,pool),100)
    assert result['valid'] and len(calls)==1
    assert 'NEWS ANALYSIS' not in calls[0] and 'An original visual.' not in calls[0]
    assert result['value']['figures']==[]


def test_visual_candidates_include_body_without_metadata_or_article_leakage():
    rep,desc,raw,l,member=fixture()
    vectors={n:[1.,0.] for n in raw['block_lookup']}
    pool=v3.visual_candidates(raw,member,vectors)
    assert any(p['text']=='c' and p['visual']=='v1' for p in pool)
    assert all(p['text'] not in {'e','f'} and p['visual']!='logo' for p in pool)
    reversedraw=deepcopy(raw);reversedraw['payload']['nodes'].reverse()
    assert v3.visual_candidates(reversedraw,member,vectors)==pool


def test_grounding_and_caption_roles_are_checked():
    value=dict(status='ACCEPT',relation='ILLUSTRATES',direction='VISUAL_TO_TEXT',
               text_anchor='sunken football pitch',visual_anchor='The pitch lies below the surrounding spectator stands.',
               reason='The rendering depicts the stated sunken pitch.')
    assert v3.validate_relation(value,'A sunken football pitch is proposed.','BODY')==value
    bad=dict(value,text_anchor='A made up sentence')
    with pytest.raises(ValueError,match='exact'):v3.validate_relation(bad,'A sunken football pitch is proposed.','BODY')
    bad=dict(value,relation='CAPTION_FOR',direction='TEXT_TO_VISUAL')
    with pytest.raises(ValueError,match='BODY'):v3.validate_relation(bad,'A sunken football pitch is proposed.','BODY')
    bad=dict(value,direction='TEXT_TO_VISUAL')
    with pytest.raises(ValueError,match='direction'):v3.validate_relation(bad,'A sunken football pitch is proposed.','BODY')
    bad=dict(value,relation='REFERENCES',direction='TEXT_TO_VISUAL')
    with pytest.raises(ValueError,match='marker'):v3.validate_relation(bad,'A sunken football pitch is proposed.','BODY')


def test_export_keeps_nodes_separate_and_diagnostic_negatives_never_enter_graph():
    nodes=[dict(node_id='text',article_id='story',source_atom_ids=['a','b'],source_visual_bundle_ids=[]),
           dict(node_id='visual',article_id='story',source_atom_ids=[],source_visual_bundle_ids=['v']),
           dict(node_id='foreign',article_id='other',source_atom_ids=['x'],source_visual_bundle_ids=[])]
    original=deepcopy(nodes)
    accepted=dict(valid=True,value=dict(status='ACCEPT',relation='ILLUSTRATES',direction='VISUAL_TO_TEXT',
        text_anchor='exact source text',visual_anchor='specific visible feature',reason='specific match'))
    pool=[dict(text='a',visual='v',export_eligible=True),dict(text='b',visual='v',export_eligible=True),
          dict(text='x',visual='v',export_eligible=True),dict(text='z',visual='v',export_eligible=False)]
    decisions={r['text']+'__v':accepted for r in pool}
    edges,internal=v3.export_visual_edges(nodes,pool,decisions)
    assert nodes==original and not internal
    assert len(edges)==1 and edges[0]['source']=='visual' and edges[0]['target']=='text'
    assert {g['text_source_id'] for g in edges[0]['grounding']}=={'a','b'}


def test_caption_inside_composite_is_an_internal_relation_not_self_edge():
    node=dict(node_id='composite',article_id='story',source_atom_ids=['caption'],source_visual_bundle_ids=['v'])
    accepted=dict(valid=True,value=dict(status='ACCEPT',relation='CAPTION_FOR',direction='TEXT_TO_VISUAL',
        text_anchor='actual caption',visual_anchor='a visible curve',reason='caption describes it'))
    edges,internal=v3.export_visual_edges([node],[dict(text='caption',visual='v',export_eligible=True)],
                                          {'caption__v':accepted})
    assert not edges and len(internal)==1
