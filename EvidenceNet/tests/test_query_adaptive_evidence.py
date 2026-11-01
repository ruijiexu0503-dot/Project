import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import query_evidence_policy as policy
import run_query_adaptive_evidence as runner
import run_span_evidence_selection as spans
from build_reader_anchor_ablation import render,sha

class Tok:
    def encode(self,text,add_special_tokens=False):return text.split()
    def apply_chat_template(self,messages,**kwargs):return ' '.join(m['content'] for m in messages).split()


def plan(kind='scalar'):
    return {'requirements':[{'id':'R1','request':'Rates in both years','kind':kind,'constraints':['2019','2024']}]}


def assessment(value,scope='2019',status='partial',pid='P0'):
    return {'requirements':[{'id':'R1','status':status,'exhaustive':False,
      'facts':[{'subject':'A2063G','scope':scope,'attribute':'positive rate','value':value,'span_ids':[pid+':S0000']}],
      'missing':[] if status=='sufficient' else ['other year rate']}]}


def packet(text,node='n0',score=1):
    return {'packet_id':node,'node_id':node,'member_id':node,'text':text,'page':['doc','1'],
            'member_sha256':sha(text),'base_score':score,'initial_node_rank':1}


def test_partial_complement_survives_same_requirement_and_budget():
    pp={'P0':packet('A2063G 2019 75.2',score=2),'P1':packet('A2063G 2024 81.4',node='n1')}
    aa={'P0':assessment('75.2'),'P1':assessment('81.4','2024',pid='P1')}
    result=policy.pack(pp,aa,100,Tok(),render)
    assert result['selected_ids']==['P0','P1']
    assert len(Tok().encode(render(result['packets'])))<=100
    tight=policy.pack(pp,aa,len(Tok().encode(render([pp['P0']]))),Tok(),render)
    assert tight['selected_ids']==['P0'] and tight['dropped'][0]['reason']=='whole_packet_over_budget'


def test_false_sufficient_does_not_suppress_other_fact():
    pp={'P0':packet('A2063G total 76.6',score=2),'P1':packet('A2063G 2024 81.4',node='n1')}
    aa={'P0':assessment('76.6','total','sufficient'),'P1':assessment('81.4','2024',pid='P1')}
    assert policy.pack(pp,aa,100,Tok(),render)['selected_ids']==['P0','P1']


def test_list_and_scopes_are_not_invented():
    ss=spans.spans('P0','A2063G 2019 75.2')
    policy.validate_assessment(assessment('75.2'),plan(),'P0',ss)
    bad=assessment('81.4')
    with pytest.raises(ValueError,match='value'):policy.validate_assessment(bad,plan(),'P0',ss)
    with pytest.raises(ValueError,match='scope'):policy.validate_assessment(assessment('75.2','2024'),plan(),'P0',ss)
    with pytest.raises(ValueError,match='exhaustive'):policy.validate_assessment(assessment('75.2',status='sufficient'),plan('set'),'P0',ss)
    other=spans.spans('P1','A2063G 2019 75.2');bad=assessment('75.2',pid='P1')
    with pytest.raises(ValueError,match='outside'):policy.validate_assessment(bad,plan(),'P0',other)


def test_verifier_sees_only_selected_spans_and_joint_support():
    result={'requirements':[{'id':'R1','status':'sufficient','exhaustive':False,
                             'span_ids':['P0:S0000','P1:S0000'],'missing':[]}]}
    allsp={**spans.spans('P0','2019 75.2'),**spans.spans('P1','2024 81.4')}
    policy.validate_verdict(result,plan(),allsp)
    with pytest.raises(ValueError,match='outside'):policy.validate_verdict(result,plan(),spans.spans('P0','2019 75.2'))


def test_bridge_can_be_followed_without_answer_coverage_and_no_cycles():
    edges=[{'edge_id':'ab','source_node_id':'a','target_node_id':'b'},{'edge_id':'bc','source_node_id':'b','target_node_id':'c'}]
    first=policy.frontier(edges,{'a'},{'a'},1)
    missing=[{'id':'R1','status':'missing','missing':['rate']}]
    decision={'routes':[{'id':first[0]['id'],'follow':True,'requirements':['R1'],'reason':'bridge to rate table'}]}
    policy.validate_routes(decision,first,missing)
    assert [r['target_node'] for r in policy.frontier(edges,{'b'},{'a','b'},2)]==['c']
    with pytest.raises(ValueError):policy.validate_routes(decision,first,[])


class FakeLLM:
    def __init__(self,results):self.results=iter(results);self.calls=0
    def generate_raw_with_images(self,*args):
        self.calls+=1;result=next(self.results)
        if isinstance(result,Exception):raise result
        return SimpleNamespace(raw=json.dumps(result))


def test_call_checkpoint_reused_and_bad_source_retried(tmp_path):
    model=FakeLLM([{'bad':'shape'},plan()]);broker=runner.Broker(tmp_path,'model',10,Tok(),model)
    answer=broker.call('q','plan',policy.PLAN,{'question':'test'},policy.validate_plan)
    assert answer==plan() and model.calls==2
    fresh=runner.Broker(tmp_path,'model',10,Tok(),FakeLLM([]))
    assert fresh.call('q','plan',policy.PLAN,{'question':'test'},policy.validate_plan)==plan()
    assert fresh.llm.calls==0
    with pytest.raises(StopIteration):fresh.call('q','plan',policy.PLAN,{'question':'different'},policy.validate_plan)
    records=list((tmp_path/'calls'/'q').glob('*.json'))
    assert len(records)==1 and len(json.loads(records[0].read_text())['attempts'])==2


def test_deadline_does_not_make_new_model_call(tmp_path):
    broker=runner.Broker(tmp_path,'model',0,Tok(),FakeLLM([]))
    with pytest.raises(runner.Deadline):broker.call('q','plan',policy.PLAN,{},policy.validate_plan)
    assert broker.llm.calls==0


def test_end_to_end_bridge_to_second_hop_and_dense_control(tmp_path):
    # The bridge has no answer facts and is NOT forced into reader text.
    packets={'P0':packet('initial background','a',3),'P1':packet('bridge context','b',2),'P2':packet('A2063G 2024 81.4','c',1)}
    ss={sid:s for pid,p in packets.items() for sid,s in spans.spans(pid,p['text']).items()}
    task={'question_id':'q','question':'2024 rate?','packets':packets,'source_spans':ss,
          'documents':{pid:'D1' for pid in packets},'seed_nodes':['a'],'node_ranking':['a','b','c'],
          'by_node':{'a':['P0'],'b':['P1'],'c':['P2']}}
    edges=[{'edge_id':'ab','source_node_id':'a','target_node_id':'b'}, {'edge_id':'bc','source_node_id':'b','target_node_id':'c'}]
    class Broker:
        tok=Tok()
        def __init__(self):self.requests=[]
        def call(self,qid,phase,instruction,payload,validator,max_tokens=8192):
            self.requests.append((phase,payload))
            if phase=='query_plan':r=plan()
            elif phase=='assessment':
                if payload['packet']['id']=='P2':r=assessment('81.4','2024','sufficient','P2')
                else:r={'requirements':[{'id':'R1','status':'missing','exhaustive':False,'facts':[],'missing':['rate']} ]}
            elif phase=='navigation':r={'routes':[{'id':x['id'],'follow':True,'requirements':['R1'],'reason':'seek rate via bridge'} for x in payload['routes']]}
            else:r={'requirements':[{'id':'R1','status':'sufficient','exhaustive':False,'span_ids':['P2:S0000'],'missing':[]}]}
            return validator(r)
    broker=Broker();r=runner.run_task(task,edges,'navigation',broker)
    graph=[x for x in r['records'] if x['arm']=='graph_adaptive']
    assert all(x['selected_ids']==['P2'] for x in graph)
    assert r['trace'][1]['followed'][0]['target_node']=='c'
    assert r['trace'][-1]['count_match'] and r['trace'][-1]['inspected_nodes']==['a','b','c']
    assert broker.requests[0]==('query_plan',{'question':'2024 rate?'})
    assert all(set(payload)=={'question','requirements','packet'} for phase,payload in broker.requests if phase=='assessment')
    assert all([p['id'] for p in payload['packets']]==['P2'] for phase,payload in broker.requests if phase=='selected_set_audit')


def test_noncontiguous_value_and_unknown_scope_not_merged():
    ss={**spans.spans('P0','A2063G 2019\n\n75.2')}
    bad=assessment('2019 75.2');bad['requirements'][0]['facts'][0]['span_ids']=list(ss)
    with pytest.raises(ValueError,match='single'):policy.validate_assessment(bad,plan(),'P0',ss)
    pp={'P0':packet('A2063G 75.2','n0',2),'P1':packet('A2063G 75.2 context','n1',1)}
    aa={'P0':assessment('75.2',''),'P1':assessment('75.2','',pid='P1')}
    assert len(policy.pack(pp,aa,100,Tok(),render)['packets'])==2


def test_real_federer_and_rate_complements_fit_1024():
    # Actual frozen source blocks from the diagnosed failures, not model predictions.
    # These hand-labelled support fixtures test the selection rule, NOT LLM accuracy.
    from transformers import AutoTokenizer
    from build_reader_anchor_ablation import ROOT,MODEL
    source=ROOT/'migration/span_results_5218364_20261030/query_span_selection_20261030/tasks.jsonl'
    tasks={t['question_id']:t for t in map(json.loads,source.read_text().splitlines())}
    tok=AutoTokenizer.from_pretrained(MODEL,local_files_only=True)
    for qid,ids,values,scope_values,subject in [
      ('df2f051f-86f0-4424-a66e-7ce0bd4d5e16',['P020','P025'],['Australian Open','Wimbledon'],['2004','2005'],'Roger Federer'),
      ('d36e190e-51f0-4e33-8ad8-9826bb387491',['P030','P013'],['76.6','81.4'],['September 1, 2019, to March 31, 2024','2024.1-3'],'A2063G')]:
        t=tasks[qid];pp={pid:t['packets'][pid] for pid in ids};aa={}
        for pid,value,scope in zip(ids,values,scope_values):
            r=assessment(value,scope,pid=pid);r['requirements'][0]['facts'][0]['subject']=subject
            aa[pid]=r
        packed=policy.pack(pp,aa,1024,tok,render)
        assert set(packed['selected_ids'])==set(ids)
        assert len(tok.encode(render(packed['packets']),add_special_tokens=False))<=1024
