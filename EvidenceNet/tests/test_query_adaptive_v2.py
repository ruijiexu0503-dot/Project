import copy
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import query_evidence_policy_v2 as policy
import run_query_adaptive_evidence_v2 as runner
import run_span_evidence_selection as spans
from test_query_adaptive_evidence import Tok,FakeLLM,packet


def plan():
    return {'requirements':[{'id':rid,'request':rid,'kind':'scalar','constraints':[]} for rid in ('R1','R2')]}


def item(rid='R1',sid='P0:S0000',status='sufficient'):
    return {'id':rid,'status':status,'exhaustive':False,
            'facts':[{'meaning':'a semantic interpretation, NOT a quote','span_ids':[sid]}],
            'missing':[] if status=='sufficient' else ['other requested detail']}


def test_one_bad_citation_keeps_other_requirement_unknown_not_missing():
    ss=spans.spans('P0','Year 2019: 75.2')
    raw={'requirements':[item(),item('R2','P9:S0000')]}
    split=policy.partition_requirements(raw,plan(),lambda r,p:policy.validate_assessment(r,p,'P0',ss))
    assert split['requirements'][0]==raw['requirements'][0]
    assert split['requirements'][1]['status']=='unknown'
    assert split['requirements'][1]['facts']==[]
    assert split['validation_issues'][0]['requirement_id']=='R2'


def test_set_without_exhaustiveness_conservatively_downgraded():
    p={'requirements':[{'id':'R1','request':'all medals','kind':'set','constraints':[]}]}
    raw={'requirements':[item()]};ss=spans.spans('P0','silver medal')
    split=policy.partition_requirements(raw,p,lambda r,p:policy.validate_assessment(r,p,'P0',ss))
    assert split['requirements'][0]['status']=='partial'
    assert split['requirements'][0]['facts']==raw['requirements'][0]['facts']
    assert split['normalizations'] and not split['validation_issues']
    assert raw['requirements'][0]['status']=='sufficient'  # raw output is immutable


def test_meaning_is_not_quote_and_does_not_create_multiple_facts():
    a=item();b=copy.deepcopy(a);b['facts'][0]['meaning']='different wording'
    assert policy.fact_key('R1',a['facts'][0],'P0')==policy.fact_key('R1',b['facts'][0],'P0')
    with pytest.raises(ValueError,match='outside'):
        policy.validate_assessment({'requirements':[item(sid='P9:S0000')]},{'requirements':[plan()['requirements'][0]]},'P0',spans.spans('P0','source'))


def test_targeted_repair_reuses_success_and_cache(tmp_path):
    ss=spans.spans('P0','original source');p=plan();payload={'question':'question','requirements':p['requirements']}
    raw={'requirements':[item(),item('R2','bad')]}
    model=FakeLLM([raw,{'requirements':[item('R2')]}]);broker=runner.Broker(tmp_path,'model',10,Tok(),model)
    strict=lambda r,p:policy.validate_assessment(r,p,'P0',ss)
    result=runner.isolated_requirements({'question_id':'q'},'assessment',policy.ASSESS,payload,p,broker,strict)
    assert model.calls==2 and not result['validation_issues']
    calls=[json.loads(f.read_text()) for f in (tmp_path/'calls'/'q').glob('*.json')]
    repair=next(c for c in calls if c['phase']=='assessment_repair')
    assert [r['id'] for r in repair['request']['requirements']]==['R2']
    fresh=runner.Broker(tmp_path,'model',10,Tok(),FakeLLM([]))
    again=runner.isolated_requirements({'question_id':'q'},'assessment',policy.ASSESS,payload,p,fresh,strict)
    assert again==result and fresh.llm.calls==0


def test_failed_targeted_repair_preserves_valid_evidence(tmp_path):
    ss=spans.spans('P0','source');p=plan();raw={'requirements':[item(),item('R2','bad')]}
    broker=runner.Broker(tmp_path,'model',10,Tok(),FakeLLM([raw,{'requirements':[item('R2','bad')]},{'requirements':[item('R2','bad')]}]))
    result=runner.isolated_requirements({'question_id':'q'},'assessment',policy.ASSESS,
        {'requirements':p['requirements']},p,broker,lambda r,p:policy.validate_assessment(r,p,'P0',ss))
    assert result['requirements'][0]['status']=='sufficient'
    assert result['requirements'][1]['status']=='unknown' and result['validation_issues']
    assert policy.pack({'P0':packet('source')},{'P0':result},100,Tok(),lambda ps:' '.join(p['text'] for p in ps))['selected_ids']==['P0']


def test_review_rejects_unsupported_added_requirements():
    decisions={'decisions':[{'id':'R1','keep':True,'reason':'question asks rate'},
                            {'id':'R2','keep':False,'reason':'question did not ask for spectroscopy'}]}
    assert policy.validate_plan_review(decisions,plan())==decisions
    decisions['decisions'][0]['keep']=False
    with pytest.raises(ValueError,match='every'):policy.validate_plan_review(decisions,plan())


def test_real_failed_outputs_replay_only_citation_protocol_not_semantic_accuracy():
    root=Path(__file__).resolve().parents[2]/'migration/query_adaptive_smoke_5219198_5219199_20261030/results'
    tasks={t['question_id']:t for t in map(json.loads,(root/'tasks.jsonl').read_text().splitlines())}
    for mode in ('fixed','navigation'):
        records=[json.loads(f.read_text()) for f in (root/mode/'calls').glob('*/*.json')]
        p=next(r['result'] for r in records if r['phase']=='query_plan')
        failed=next(r for r in records if not r['valid']);raw=json.loads(failed['attempts'][-1]['raw'])
        # Explicit test-only migration of the recorded v1 fields to v2 meaning+IDs.
        # Never changes frozen results or treats copied model claims as true.
        for r in raw['requirements']:
            for f in r['facts']:
                sid=f['span_ids'];meaning=f['value'];f.clear();f.update(meaning=meaning,span_ids=sid)
        task=tasks[failed['question_id']];pid='P015' if mode=='fixed' else 'P009'
        result=policy.partition_requirements(raw,p,lambda r,p:policy.validate_assessment(r,p,pid,task['source_spans']))
        assert not result['validation_issues']
        assert all(s in task['source_spans'] for r in result['requirements'] for f in r['facts'] for s in f['span_ids'])
        if mode=='fixed':assert result['requirements'][2]['status']=='partial'


def test_selected_audit_cannot_cite_nonselected_packet():
    p={'requirements':[plan()['requirements'][0]]}
    raw={'requirements':[{'id':'R1','status':'sufficient','exhaustive':False,'span_ids':['P9:S0000'],'missing':[]}]}
    result=policy.partition_requirements(raw,p,lambda r,p:policy.validate_verdict(r,p,spans.spans('P0','source')),True)
    assert result['requirements'][0]['status']=='unknown' and result['validation_issues']


def test_full_fixed_run_keeps_partial_records_but_not_complete(tmp_path):
    pp={'P0':packet('source')};ss=spans.spans('P0','source')
    task={'question_id':'q','question':'two requested facts','packets':pp,'source_spans':ss,
          'documents':{'P0':'D1'},'fixed_packet_ids':['P0'],'fixed_base_scores':{'P0':1}}
    class PartialBroker:
        tok=Tok()
        def call(self,qid,phase,instruction,payload,validator,max_tokens=8192):
            if phase.endswith('_repair'):raise runner.InvalidOutput('source still invalid')
            if phase=='query_plan':r=plan()
            elif phase=='query_plan_review':r={'decisions':[{'id':rid,'keep':True,'reason':'requested'} for rid in ('R1','R2')]}
            elif phase=='assessment':r={'requirements':[item(),item('R2','bad')]}
            else:r={'requirements':[{'id':'R1','status':'sufficient','exhaustive':False,'span_ids':['P0:S0000'],'missing':[]},
                                    {'id':'R2','status':'missing','exhaustive':False,'span_ids':[],'missing':['No evidence']} ]}
            return validator(r)
    result=runner.run_task(task,[],'fixed',PartialBroker())
    assert result['processing_finished'] and not result['complete']
    assert result['validation_issues'] and len(result['records'])==4
    assert all(r['selected_ids']==['P0'] for r in result['records'])
    (tmp_path/'tasks.jsonl').write_text(json.dumps(task)+'\n')
    p=tmp_path/'fixed'/'predictions';p.mkdir(parents=True)
    (p/'q.json').write_text(json.dumps(result))
    runner.report(tmp_path,'fixed')
    status=json.loads((tmp_path/'fixed'/'status.json').read_text())
    assert status['complete_queries']==0 and status['queries'][0]['state']=='partial_validation'
    selected=[json.loads(l) for l in (tmp_path/'fixed'/'selected.jsonl').read_text().splitlines()]
    assert len(selected)==4 and all(not r['query_validation_complete'] for r in selected)
