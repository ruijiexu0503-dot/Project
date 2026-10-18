import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_article_bridge_binding_v2 import (
    alias_candidates, canonicalize, validate_binding, context_catalog,
    select_routes, navigation, derive_pair,
)


def group(gid, name, article='one', kind='PROJECT'):
    return {'group_id': gid, 'name': name, 'article_id': article, 'kind': kind}


def bind(nid, aid, aspect='other', sid='event', status='SUPPORTED'):
    return {'binding_id': 'B'+nid, 'node_id': nid, 'article_id': aid, 'subject_id': sid, 'status': status,
            'decision': {'aspect_type': aspect, 'local_anchors': [{'node_id': nid, 'quote': 'original'}],
                         'context_sources': []}}


def test_alias_proposals_do_not_merge_component_or_cross_article_ocr():
    groups = [group('a', 'AHEAD'), group('b', 'the AHEAD project'),
              group('c', 'CAFEIN'), group('d', 'UMBRELLA'), group('e', 'UMRELLA'),
              group('f', 'UMRELLA', article='different')]
    pairs = {frozenset((p['source_group'],p['target_group'])) for p in alias_candidates(groups)}
    assert frozenset(('a','b')) in pairs
    assert frozenset(('d','e')) in pairs
    assert frozenset(('d','f')) not in pairs
    assert frozenset(('c','d')) not in pairs


def test_canonical_merge_cannot_chain_across_conflicting_identity():
    groups = [group('a','AHEAD'),group('b','AHEAD project'),group('c','The AHEAD project')]
    ds = [{'alias_pair_id':a+b,'source_group':a,'target_group':b,'status':status} for a,b,status in
          [('a','b','SAME'),('b','c','SAME'),('a','c','DIFFERENT')]]
    subjects, mapping = canonicalize(groups, ds)
    assert mapping['a'] == mapping['b']
    assert mapping['a'] != mapping['c']
    assert len(subjects) == 2


def test_missing_index_does_not_make_supported_schema_negative_a_format_failure():
    value={'status':'NOT_ABOUT_SUBJECT','reason':'Different object.', 'local_evidence_ids':['LOCAL:T000'],
           'context_ids':[], 'aspect_type':'other'}
    result=validate_binding(value,{'LOCAL:T000':{'kind':'TEXT','node_id':'a'}},{})
    assert result['status']=='NOT_ABOUT_SUBJECT'
    value['local_evidence_ids']=['CTX:foreign']
    with pytest.raises(ValueError,match='local_anchor_ownership'):
        validate_binding(value,{'LOCAL:T000':{'kind':'TEXT'}},{'CTX:foreign':{}})


def test_visual_binding_requires_original_observation():
    v={'status':'SUPPORTED','reason':'plot','aspect_type':'parameter_estimation',
       'local_evidence_ids':['LOCAL:V000'],'context_ids':[]}
    with pytest.raises(ValueError,match='visual_observation_required'):
        validate_binding(v,{'LOCAL:V000':{'kind':'VISUAL'}},{})


def test_explicit_context_cannot_cross_articles():
    item={'node_id':'target','context_proposals':[{'reference':{'source':'source','target':'target'}}]}
    with pytest.raises(ValueError,match='context_crosses_article_or_target'):
        context_catalog(item,{}, {'source':'article1','target':'article2'})


def test_different_aspects_derive_weak_edge_and_keep_provenance_separate():
    a=bind('a','one','detection_significance');b=bind('b','two','gravity_test')
    b['decision']['context_sources']=[{'source_node':'ctx','target_node':'b'}]
    result=derive_pair({'source':'a','target':'b'},[a,b])
    assert result['status']=='DERIVED_RELATED_VIA_SUBJECT'
    assert result['paths'][0]['target_context'][0]['source_node']=='ctx'
    assert result['paths'][0]['source_context']==[]
    b['status']='BACKGROUND'
    assert derive_pair({'source':'a','target':'b'},[a,b])['status']=='NO_SHARED_VERIFIED_SUBJECT'


def test_article_navigation_is_consumed_and_budget_and_fallback_are_preserved():
    ids=['source']+[f'g{i}' for i in range(8)]+['b0','b1','b2','c0','c1']
    mapping={n:n for n in ids};mapping.update({'b0':'B','b1':'B','b2':'B','c0':'C','c1':'C'})
    ranking={'source':ids[1:]}
    bindings=[bind('source','source','detection_significance'),bind('b0','B','parameter_estimation'),
              bind('b1','B','parameter_estimation'),bind('b2','B','gravity_test'),
              bind('c0','C','instrument_calibration'),bind('c1','C','gravity_test')]
    edges=navigation(bindings)
    result=select_routes(ranking,mapping,bindings,edges,True)[0]
    assert len(result['targets'])==8
    assert set(['g0','g1','g2','g3']) <= set(result['targets'])
    assert {r['article_id'] for r in result['article_allocations']}=={'B','C'}
    assert next(r for r in result['article_allocations'] if r['article_id']=='B')['targets']==['b0','b2']
    empty=select_routes(ranking,mapping,bindings,[],True)[0]
    assert empty['targets']==[f'g{i}' for i in range(8)]


def test_duplicate_binding_cannot_silently_overwrite_source():
    binding=bind('a','one')
    with pytest.raises(ValueError,match='duplicate_node_subject_binding'):
        select_routes({'a':[]},{'a':'one'},[binding,binding],[],True)


def test_diagnostic_probe_cannot_inject_an_edge_even_when_model_accepts_it():
    a=bind('a','one');b=bind('b','two')
    b['purposes']=['negative_binding_probe']
    assert navigation([a,b])==[]
    assert derive_pair({'source':'a','target':'b'},[a,b])['status']=='NO_SHARED_VERIFIED_SUBJECT'


def test_malformed_json_shape_is_retryable_validation_failure():
    with pytest.raises(ValueError,match='binding_object_required'):
        validate_binding([],{}, {})
