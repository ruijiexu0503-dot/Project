import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from replay_article_bridge_routing_v4 import select, pairs


def test_additive_routing_preserves_global_and_uses_new_slots_fairly():
    ids=[f'g{i}' for i in range(8)]+['b0','b1','b2','c0','c1']
    mapping={n:n for n in ['s']+ids}
    mapping.update({n:n[0] for n in ids if n[0] in 'bc'})
    bindings=[{'node_id':n,'subject_id':'event','status':'SUPPORTED','purposes':['content_index']} for n in ['s','g0','b0','b1','b2','c0','c1']]
    result=select({'s':ids},mapping,bindings,8,4)[0]
    assert result['targets'][:8]==ids[:8]
    assert result['guided_new_targets']==['b0','c0','b1','c1']
    assert len(set(result['targets']))==12


def test_probe_and_unresolved_do_not_guide_and_short_pool_falls_back():
    ids=['a','b','c'];mapping={n:n for n in ['s']+ids}
    bs=[{'node_id':'s','subject_id':'event','status':'SUPPORTED'},
        {'node_id':'c','subject_id':'event','status':'SUPPORTED','purposes':['negative_binding_probe']}]
    result=select({'s':ids},mapping,bs,1,3)[0]
    assert result['targets']==ids
    assert result['guided_new_targets']==[]
    assert len(pairs([result]))==3
