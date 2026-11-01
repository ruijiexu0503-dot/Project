import sys
from pathlib import Path
import pytest
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_top10_node_navigation import expand
import run_top10_node_navigation as navigation


def edge(a,b,name='e'):
    return {'edge_id':name,'source_node_id':a,'target_node_id':b}


def test_tenth_seed_reaches_low_rank_target_not_global_unconnected_edge():
    ranking=[f'n{i}' for i in range(1,101)]
    r=expand(ranking,[edge('n10','n80'),edge('n81','n82','unconnected')])
    assert len(r['seed_nodes'])==10
    assert r['graph_nodes']==ranking[:10]+['n80']
    assert r['dense_matched_nodes']==ranking[:11]
    assert r['paths'][0]['source_rank']==10
    assert r['paths'][0]['target_initial_rank']==80
    assert r['paths'][0]['outside_top20']


def test_all_neighbors_not_top_two_and_unique_candidates():
    ranking=[str(i) for i in range(30)]
    r=expand(ranking,[edge('9','25','a'),edge('9','26','b'),edge('9','27','c'),edge('0','27','d')])
    assert len(r['paths'])==4
    assert len(r['graph_nodes'])==13
    assert set(r['graph_nodes'])==set(ranking[:10])|{'25','26','27'}


def test_seed_to_seed_paths_do_not_inflate_candidate_budget():
    ranking=[str(i) for i in range(20)]
    r=expand(ranking,[edge('0','9')])
    assert len(r['paths'])==2
    assert r['graph_nodes']==ranking[:10]
    assert not any(p['outside_top10'] for p in r['paths'])


def test_fail_closed_on_unknown_endpoint_and_duplicate_ranks():
    with pytest.raises(ValueError):expand(list('abcdefghij'),[edge('a','unknown')])
    with pytest.raises(ValueError):expand(['a']*10,[])


def test_report_separates_prebudget_rank_from_actual_reader_inclusion(tmp_path,monkeypatch):
    class Tokenizer:
        def encode(self,text,add_special_tokens=False):return list(text)
    monkeypatch.setattr(navigation,'check_navigation',lambda out:None)
    monkeypatch.setattr(navigation.selection,'check_prepared',lambda out,model:None)
    monkeypatch.setattr(navigation.selection,'tokenizer',lambda model:Tokenizer())
    monkeypatch.setattr(navigation,'BUDGETS',(100,))
    packets={}
    for pid,nid,text,base in [('P0','seed','short fact.',1.0),('P1','target','long '*100,0.1)]:
        packets[pid]={'node_id':nid,'packet_id':pid,'page':['doc','1'],'text':text,
                      'member_sha256':pid,'base_score':base}
    task={'question_id':'q','question':'query','prompt_sha256':'hash','packets':packets,
          'edges':[{'id':'E0','edge_id':'edge','source_packets':['P0'],'target_packets':['P1']}]}
    context={'question_id':'q','seed_nodes':['seed'],'graph_nodes':['seed','target'],
             'dense_matched_nodes':['seed'],'node_ranking':['seed','target'],
             'paths':[{'edge_id':'edge','source_node':'seed','target_node':'target'}]}
    result={'requirements':[{'id':'F1','text':'requirement'}],
            'packets':[{'id':'P0','score':2,'covers':[{'requirement':'F1','quote':'short'}]},
                       {'id':'P1','score':3,'covers':[{'requirement':'F1','quote':'long'}]}],
            'edges':[{'id':'E0','useful':True,'reason':'required target'}]}
    (tmp_path/'tasks.jsonl').write_text(json.dumps(task)+'\n')
    (tmp_path/'navigation.jsonl').write_text(json.dumps(context)+'\n')
    (tmp_path/'predictions').mkdir()
    (tmp_path/'predictions/q.json').write_text(json.dumps({'valid':True,'prompt_sha256':'hash','result':result}))
    navigation.report(tmp_path,Path('unused'))
    traces=navigation.rows(tmp_path/'ranked_paths.jsonl')
    t=next(t for t in traces if t['arm']=='seed10_neighbors')
    assert t['paths'][0]['target_prebudget_node_rank']==1
    assert not t['budget_packing'][0]['paths'][0]['target_in_final_input']
    assert t['budget_packing'][0]['paths'][0]['target_input_order'] is None
    selected=navigation.rows(tmp_path/'selected.jsonl')
    assert all(r['evidence_tokens']<=100 for r in selected)
