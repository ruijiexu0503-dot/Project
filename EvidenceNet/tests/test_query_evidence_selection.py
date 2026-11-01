import sys
from pathlib import Path
import copy

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_query_evidence_selection import validate, select


class Tokenizer:
    def encode(self,text,add_special_tokens=False): return list(text)


def fixture():
    task={'packets':{},'edges':[{'id':'E0','source_packets':['P0'],'target_packets':['P2']}]}
    for i in range(3):
        task['packets'][f'P{i}']={'text':f'Fact {i}.','page':['doc','1'],'member_sha256':str(i),'base_score':3-i,'packet_id':str(i)}
    result={'requirements':[{'id':'F1','text':'first part'},{'id':'F2','text':'second part'}],
      'packets':[{'id':f'P{i}','score':3 if i<2 else 1,'covers':[{'requirement':'F1' if i<2 else 'F2','quote':f'Fact {i}.'}]} for i in range(3)],
      'edges':[{'id':'E0','useful':True,'reason':'necessary context for second requirement'}]}
    return task,result


def test_source_grounding_and_full_id_contract():
    task,result=fixture();validate(result,task)
    bad=copy.deepcopy(result);bad['packets'][0]['covers'][0]['quote']='Invented fact'
    with pytest.raises(ValueError):validate(bad,task)
    bad=copy.deepcopy(result);bad['packets'][1]['id']='P0'
    with pytest.raises(ValueError):validate(bad,task)


def test_coverage_stops_repetition_and_edge_requires_selected_endpoint():
    task,result=fixture()
    direct=select(task,result,'Q0_query_rank',1000,Tokenizer())
    coverage=select(task,result,'Q1_query_coverage',1000,Tokenizer())
    edge=select(task,result,'Q2_query_coverage_edge_gate',1000,Tokenizer())
    assert [p['selection_id'] for p in direct['packets']]==['P0','P1']
    assert [p['selection_id'] for p in coverage['packets']]==['P0']
    assert [p['selection_id'] for p in edge['packets']]==['P0','P2']
    assert edge['packets'][1]['via_edges']==['E0']
    result['edges'][0]['useful']=False
    assert len(select(task,result,'Q2_query_coverage_edge_gate',1000,Tokenizer())['packets'])==1


def test_budget_never_clips_source_or_admits_unsupported_bridge():
    task,result=fixture()
    assert not select(task,result,'Q2_query_coverage_edge_gate',2,Tokenizer())['packets']
    result['packets'][0]['score']=0;result['packets'][0]['covers']=[]
    result['packets'][1]['score']=0;result['packets'][1]['covers']=[]
    assert not select(task,result,'Q2_query_coverage_edge_gate',1000,Tokenizer())['packets']
