import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from trace_vldocir_edges import expand

def test_path_is_an_actual_edge_and_has_rank_score_explanation():
    pages={'A':('doc','1'),'B':('doc','2'),'C':('other','1')}
    hits={'A':{'score':.9,'window_input_line':1},'B':{'score':.85,'window_input_line':2},'C':{'score':.1}}
    original={('doc','1'):.9,('doc','2'):.85,('other','1'):.1}
    edges=[{'task_id':'AB','source':'A','target':'B'}]
    scores,paths,seeds=expand('Q',hits,pages,edges,original)
    assert paths and all(p['edge_id']=='AB' for p in paths)
    assert all(p['target_node']!='C' for p in paths)
    p=next(p for p in paths if p['seed_node']=='A')
    assert p['decision']=='accepted' and p['seed_hit']['window_input_line']==1
    assert p['target_original_rank']==2 and p['target_final_rank']<=2
    assert p['applied_page_boost']>0 and not p['evidence_propagation_allowed']

def test_same_page_and_irrelevant_targets_are_recorded_without_boost():
    pages={'A':('doc','1'),'B':('doc','1'),'C':('other','1')}
    hits={'A':{'score':.9},'B':{'score':.85},'C':{'score':.1}}
    edges=[{'task_id':'AB','source':'A','target':'B'},{'task_id':'AC','source':'A','target':'C'}]
    scores,paths,_=expand('Q',hits,pages,edges,{('doc','1'):.9,('other','1'):.1})
    assert any(p['decision']=='same_page_no_new_page' for p in paths)
    assert any(p['decision']=='target_query_similarity_too_low' for p in paths)
    assert all(p['proposed_boost']==0 for p in paths if p['seed_node']=='A')

def test_no_edges_preserves_page_ranking_and_returns_seeds():
    scores,paths,seeds=expand('Q',{'A':{'score':.9}}, {'A':('d','1')},[],{('d','1'):.9,('d','2'):.8})
    assert not paths and seeds[0]['node_id']=='A'
    assert sorted(scores,key=scores.get,reverse=True)==[('d','1'),('d','2')]
