import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import formula_retrieval_views as f


def fixture():
    text=[('intro','Mean absolute loss is adopted to train the model.','para','a'),
          ('formula',r'$$L=\|Y-Y^{gt}\| _ { 1 } \quad(5)$$','equ','a'),
          ('after','where Y is the predicted traffic speed.','para','a'),
          ('foreign','Equation (5) describes a completely different physical model.','para','b')]
    nodes={nid:dict(id=nid,article_id=art,document='doc',page=1,members=[dict(id='m',kind='atom',role=role,text=text)]) for nid,text,role,art in text}
    policy={nid:dict(eligible=True,members=[dict(member_id='m',kind='atom',eligible=True)]) for nid in nodes}
    reading=[dict(source='intro',target='formula',type='NEXT'),dict(source='formula',target='after',type='NEXT'),dict(source='foreign',target='formula',type='NEXT')]
    return nodes,policy,reading


def test_short_formula_preserved_with_original_quote_and_math_type():
    nodes,policy,reading=fixture();vs,b=f.build_formula_views(nodes,policy,reading,False)
    raw=next(v for v in vs if v['kind']=='formula_original')
    assert raw['quote']==nodes['formula']['members'][0]['text']
    assert raw['evidence_kind']=='FORMULA' and raw['structure_tags']==['L1 norm']
    assert raw['context_spans']==[] and raw['formula_number']=='5'


def test_context_is_separately_owned_and_never_crosses_article():
    nodes,policy,reading=fixture();vs,bs=f.build_formula_views(nodes,policy,reading,True)
    context=next(b['context_spans'] for b in bs if b['formula']['node_id']=='formula')
    assert {c['node_id'] for c in context}=={'intro','after'}
    for c in context:
        assert c['quote']==nodes[c['node_id']]['members'][0]['text'][c['char_start']:c['char_end']]
    assert all(v['node_id']=='formula' and not v['context_is_endpoint_content'] for v in vs if v['kind']=='formula_context')


def test_ambiguous_reading_and_unknown_article_do_not_borrow_context():
    nodes,policy,reading=fixture();reading.append(dict(source='after',target='formula',type='NEXT'))
    _,bs=f.build_formula_views(nodes,policy,reading,True)
    assert not any(c['route']=='adjacent_introducer' for c in bs[0]['context_spans'])
    nodes['formula']['article_id']='doc::UNRESOLVED_PAGE_BUCKET::1'
    _,bs=f.build_formula_views(nodes,policy,reading,True)
    assert bs[0]['context_spans']==[]


def test_explicit_reference_requires_unique_equation_in_same_article():
    nodes,policy,reading=fixture()
    nodes['intro']['members'][0]['text']='The objective in Eq. (5) is used for training.'
    _,bs=f.build_formula_views(nodes,policy,[],True)
    assert any(c['route']=='explicit_equation_reference' for c in bs[0]['context_spans'])
    nodes['second']={**nodes['formula'],'id':'second'};policy['second']=policy['formula']
    _,bs=f.build_formula_views(nodes,policy,[],True)
    assert all(not b['context_spans'] for b in bs)


def test_nonformula_views_unchanged_and_no_ungrounded_norm_tag():
    nodes,policy,reading=fixture();base=f.h.make_views(nodes,policy)
    vs,_=f.build_formula_views(nodes,policy,reading,True)
    strip=lambda v:{k:x for k,x in v.items() if k!='view_id'}
    assert [strip(v) for v in base if v['node_id']!='formula']==[strip(v) for v in vs if v['node_id']!='formula']
    assert f.structure_tags(r'$$L=Y-X$$')==[]
    assert f.structure_tags(r'\ell_1 loss')==['L1 norm']
    assert f.formula_number('Eq (1) followed by words') is None
