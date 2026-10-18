from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence_graph.article_order import sentence_block,validate_order,owned_flows,validate_paths,jaccard


def test_comma_does_not_license_new_quotation_but_allows_true_list_continuation():
    assert sentence_block('open-source software and hardware,','"The publication of the policy')=='new_quoted_paragraph'
    assert sentence_block('open-source software and hardware,','research integrity, open infrastructure') is None
    assert sentence_block('These pioneering exper-','iments confirmed the theory.') is None
    assert sentence_block('A complete claim.','Another paragraph')=='closed_sentence_or_list'


def test_reading_paths_can_go_backwards_in_parser_labels_without_reordering_atoms():
    assert validate_paths([('N023','N018'),('N022','N023')])==[['N022','N023','N018']]
    for edges in [[('a','b'),('a','c')],[('a','b'),('c','b')],[('a','b'),('b','a')]]:
        with pytest.raises(ValueError):validate_paths(edges)


def test_reading_requires_coverage_and_preserves_modal_roles():
    payload=dict(nodes=[dict(label='a'),dict(label='b'),dict(label='v'),dict(label='h')])
    roles=dict(a='BODY',b='CAPTION',v='VISUAL',h='STRUCTURAL')
    value=dict(flows=[dict(kind='body',nodes=['a']),dict(kind='caption',nodes=['b'])],unsequenced=['v'])
    assert validate_order(value,payload,roles)==value
    bad=dict(flows=[dict(kind='body',nodes=['a','v'])],unsequenced=['b'])
    with pytest.raises(ValueError):validate_order(bad,payload,roles)
    bad=dict(flows=[dict(kind='body',nodes=['a'])],unsequenced=['v'])
    with pytest.raises(ValueError,match='missing'):validate_order(bad,payload,roles)


def test_article_filter_never_bridges_foreign_intervening_nodes():
    member=dict(groups=[dict(id='g1',kind='article',nodes=['a','c']),dict(id='g2',kind='article',nodes=['b'])],
                roles=dict(a='BODY',b='BODY',c='BODY'))
    flows,cross=owned_flows(dict(flows=[dict(kind='body',nodes=['a','b','c'])]),member)
    assert [f['nodes'] for f in flows]==[['a'],['b'],['c']]
    assert cross==[['a','b'],['b','c']]
    assert jaccard([],[]) is None
