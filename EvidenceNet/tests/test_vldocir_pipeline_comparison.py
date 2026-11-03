import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import json
import numpy as np
import pytest
from types import SimpleNamespace
import vldocir_candidate_comparison as candidates
import vldocir_reading_backbone as reading
from run_vldocir_pipeline_comparison import select_pages


def test_every_node_gets_distinct_target_even_when_router_pool_omits_it():
    nodes={n:{'id':n,'article_id':n} for n in ('a','b','c')}
    views=[{'node_id':n,'view_id':'v'+str(i)} for i,n in enumerate(('a','a','b','c'))]
    v=np.array([[1,0],[1,0],[.8,.6],[0,1]],dtype=np.float32)
    pool={('a','b'):{'source':'a','target':'b','retrieval_score':.9}}
    pairs,decisions=candidates.every_node(pool,views,v,nodes,1)
    assert all(len(d['candidates'])==1 for d in decisions)
    assert len(pairs)==2
    assert any(p['source']=='b' and p['target']=='c' for p in pairs)
    assert not any(p['source']==p['target'] for p in pairs)
    assert set(decisions[-1]['candidates'][0])=={'b','c'}


def test_multiview_duplicates_do_not_consume_topk_nodes():
    nodes={n:{'id':n,'article_id':'doc'} for n in ('a','b','c')}
    views=[{'node_id':n,'view_id':str(i)} for i,n in enumerate(('a','a','a','b','c'))]
    v=np.array([[1,0],[1,0],[1,0],[1,0],[0,1]],dtype=np.float32)
    pairs,decisions=candidates.every_node({},views,v,nodes,2)
    assert len(pairs)==3
    assert all(len(d['candidates'])==2 for d in decisions)


def test_short_and_formula_nodes_gain_views_without_rewriting_members():
    nodes={'x':{'id':'x','article_id':'d','members':[{'id':'m','kind':'atom','text':'$$x$$'}]},
           'blank':{'id':'blank','article_id':'d','members':[{'id':'b','kind':'atom','text':' '}]}}
    policies={n:{'eligible':True,'members':[{'member_id':m['id'],'kind':'atom','eligible':True} for m in row['members']]}
              for n,row in nodes.items()}
    views,excluded=candidates.missing_views(nodes,policies,[])
    assert len(views)==1 and views[0]['quote']=='$$x$$'
    assert views[0]['char_start']==0 and views[0]['char_end']==5
    assert excluded==[{'node_id':'blank','reason':'no_nonempty_eligible_member'}]


def graph():
    nodes={n:{'document':'doc','page':1} for n in ('a','b','c')}
    assignments={n:{'article_id':'article'} for n in nodes}
    return nodes,assignments


def test_reading_preserves_singletons_and_reports_coverage():
    n,a=graph();e=[dict(source='a',target='b',type='NEXT',article_id='article')]
    result=reading.validate_edges(n,e,a)
    assert result['next_edges']==1 and result['nodes_without_next']==['c']
    assert result['cross_page_next']==0


def test_reading_rejects_cross_document_edges_and_cycles():
    n,a=graph();n['b']['document']='other'
    e=[dict(source='a',target='b',type='NEXT',article_id='article')]
    with pytest.raises(ValueError,match='document'):reading.validate_edges(n,e,a)
    n['b']['document']='doc'
    e+=[dict(source='b',target='a',type='NEXT',article_id='article')]
    with pytest.raises(ValueError,match='cycle'):reading.validate_edges(n,e,a)


def test_reading_adjacency_never_crosses_unresolved_article():
    n,a=graph();a['b']['article_id']=None
    with pytest.raises(ValueError,match='boundary'):
        reading.validate_edges(n,[dict(source='a',target='b',type='NEXT',article_id='article')],a)


def test_shared_page_budget_deduplicates_reading_and_semantic_paths():
    direct=[('doc',str(i)) for i in range(30)]
    reading=[(direct[0],{'edge_type':'NEXT'}),(direct[22],{'edge_type':'NEXT'})]
    semantic=[(direct[22],{'edge_id':'same_page'}),(direct[23],{'edge_id':'new'})]
    pages,trace=select_pages(direct,reading,semantic)
    assert len(pages)==20 and len(set(pages))==20
    assert pages[:10]==direct[:10]
    assert direct[22] in pages and direct[23] in pages
    assert trace[0]['decision']=='already_selected' and trace[2]['decision']=='already_selected'


def test_same_page_reading_does_not_fabricate_page_recall():
    direct=[('doc',str(i)) for i in range(25)]
    pages,_=select_pages(direct,[(direct[2],{'edge_type':'NEXT'})],[])
    assert pages==direct[:20]


def test_candidate_outside_frozen_corpus_fails():
    with pytest.raises(ValueError,match='corpus'):
        select_pages([('doc','1')],[(('evil','2'),{})],[],budget=1,core=1)


def test_article_prepare_filters_unselected_batch_neighbour_before_input_read():
    import run_hybrid_article_clustering as article
    args=SimpleNamespace(include_task=[],include_document=['wanted-document'])
    assert article.task_selected(args,'wanted-document/page_0001')
    assert not article.task_selected(args,'unpackaged-neighbour/page_0025')
    args.include_task=['wanted-document/page_0002']
    assert not article.task_selected(args,'wanted-document/page_0001')
    assert article.task_selected(args,'wanted-document/page_0002')


def test_complete_matched_report_scores_same_query_pages_and_rejects_partial(tmp_path,monkeypatch):
    import json
    import run_vldocir_pipeline_comparison as driver
    from run_node_context_edges import jsonl,write,sha
    from run_cached_query_reranker import input_sha
    from evaluate_vldocir import TYPES
    out=tmp_path/'out';trace=tmp_path/'trace';base=tmp_path/'base'
    monkeypatch.setattr(driver,'check_graph',lambda p:None)
    monkeypatch.setattr(driver,'TRACE',trace);monkeypatch.setattr(driver,'BASE',base)
    queries=[dict(question_id=str(i),question='query '+str(i),question_type=t) for i,t in enumerate(TYPES)]
    pages=[('doc',str(i)) for i in range(25)]
    jsonl(trace/'queries.jsonl',queries)
    jsonl(trace/'gold_evidence.jsonl',[dict(question_id=q['question_id'],document_id='doc',page_number=0) for q in queries])
    jsonl(base/'pilot/image_pages.jsonl',[dict(document_id=p[0],page_number=p[1]) for p in pages])
    selections=[];contexts=[];mapping=[];tasks=[];scores=[]
    for q in queries:
        qid=q['question_id']; ids={}
        for i,p in enumerate(pages[:20]):
            rid=qid+':'+str(i);r=dict(id=rid,query=q['question'],text='passage '+str(i));tasks.append(r)
            ids[json.dumps(p)]=[rid]
            scores.append(dict(id=rid,input_sha256=input_sha(r),score=-i,original_tokens=4,truncated=False))
        for arm in driver.ARMS:selections.append(dict(question_id=qid,arm=arm,pages=pages[:20]))
        contexts.append(dict(question_id=qid,direct=pages,ColNomic=pages))
        mapping.append(dict(question_id=qid,pages=ids))
    for name,values in [('query_candidates',selections),('ranking_contexts',contexts),('page_reranker_ids',mapping),('reranker_inputs',tasks),('reranker_scores',scores)]:
        jsonl(out/(name+'.jsonl'),values)
    write(out/'retrieval_manifest.json',dict(files={name+'.jsonl':sha(out/(name+'.jsonl')) for name in ('query_candidates','ranking_contexts','page_reranker_ids','reranker_inputs')},queries_sha256=sha(trace/'queries.jsonl')))
    write(out/'graph_summary.json',dict(complete=True))
    assert driver.report(out)['complete']
    result=json.loads((out/'results.json').read_text())
    assert len(result['metrics'])==7
    assert result['metrics']['all_node_pipeline']['macro_six_types']['mAP@5']==1
    assert result['paired_AP5']['all_node_pipeline_vs_sparse_pipeline']==dict(wins=0,losses=0,ties=6)
    jsonl(out/'reranker_scores.jsonl',scores[:-1])
    with pytest.raises(ValueError,match='Incomplete scores'):driver.report(out)


def _worker_plan(documents=('a','b')):
    return {'shards':1,'documents':list(documents),'worker_documents':{'0':list(documents)},'inputs':{},
            'document_work':{doc:{'page_tasks':[doc+'/page_0001'],'page_count':1,'node_count':1}
                             for doc in documents}}


def _article_artifact(driver,root,*,membership,reading_ready,reading_failure=False):
    from run_node_context_edges import jsonl,write,sha
    jsonl(root/'article_assignments.jsonl',[{'node_id':root.name+'_node'}] if membership else [])
    jsonl(root/'reading_edges.jsonl',[])
    jsonl(root/'issues.jsonl',[] if membership else [{'type':'PAGE_CLUSTER_FAILED'}])
    jsonl(root/'reading_issues.jsonl',[{'type':'PAGE_READING_UNRESOLVED'}] if reading_failure else [])
    files={name:sha(root/name) for name in ('article_assignments.jsonl','reading_edges.jsonl','issues.jsonl','reading_issues.jsonl')}
    write(root/'article_graph_manifest.json',{'ready_for_downstream':membership,
          'reading_ready':reading_ready,'files':files})


def _patch_cpu_worker(monkeypatch,driver,out,plan):
    from run_node_context_edges import write
    write(out/'verifier_shards/0/summary.json',{'complete':True})
    monkeypatch.setattr(driver,'validate_plan',lambda _:plan)
    monkeypatch.setattr(driver.verifier,'run',lambda *a,**k:None)
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda:None)))


@pytest.mark.parametrize('first_artifact',[
    {'membership':False,'reading_ready':False,'reading_failure':False},
    {'membership':True,'reading_ready':False,'reading_failure':True},
])
def test_first_incomplete_document_never_skips_second(tmp_path,monkeypatch,first_artifact):
    import run_vldocir_pipeline_comparison as driver
    out=tmp_path/'out';plan=_worker_plan();_patch_cpu_worker(monkeypatch,driver,out,plan)
    calls=[]
    def run(command,check=False):
        doc=command[command.index('--document')+1];calls.append(doc)
        root=out/'articles'/doc
        if doc=='a':
            _article_artifact(driver,root,**first_artifact);return SimpleNamespace(returncode=1)
        _article_artifact(driver,root,membership=True,reading_ready=True);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(driver.subprocess,'run',run)
    result=driver.worker(out,Path('/model'),0)
    assert calls==['a','b']
    assert result['document_statuses']=={'a':'partial','b':'complete'}
    assert json.loads((out/'document_status/a.json').read_text())['error']=='reading subprocess exit 1'


def test_document_scoped_exception_is_persisted_and_next_runs(tmp_path,monkeypatch):
    import run_vldocir_pipeline_comparison as driver
    out=tmp_path/'out';plan=_worker_plan();_patch_cpu_worker(monkeypatch,driver,out,plan);calls=[]
    def run(command,check=False):
        doc=command[command.index('--document')+1];calls.append(doc)
        if doc=='a':raise RuntimeError('broken document payload')
        _article_artifact(driver,out/'articles'/doc,membership=True,reading_ready=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(driver.subprocess,'run',run)
    result=driver.worker(out,Path('/model'),0)
    assert calls==['a','b'] and result['document_statuses']=={'a':'failed','b':'complete'}
    assert 'broken document payload' in json.loads((out/'document_status/a.json').read_text())['error']


def test_interrupted_status_remains_visible_and_does_not_fake_success(tmp_path,monkeypatch):
    import run_vldocir_pipeline_comparison as driver
    out=tmp_path/'out';plan=_worker_plan();_patch_cpu_worker(monkeypatch,driver,out,plan)
    driver.initialize_document_statuses(out,plan)
    state=driver.load_document_status(out,plan,'a');state['status']='running'
    driver.atomic_status(driver.status_path(out,'a'),state);calls=[]
    def run(command,check=False):
        doc=command[command.index('--document')+1];calls.append(doc)
        _article_artifact(driver,out/'articles'/doc,membership=True,reading_ready=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(driver.subprocess,'run',run)
    result=driver.worker(out,Path('/model'),0)
    assert calls==['b']
    assert result['document_statuses']['a']=='failed'
    assert 'interrupted' in json.loads((out/'document_status/a.json').read_text())['error']


def test_good_artifact_reused_and_bad_artifact_requires_explicit_recovery(tmp_path,monkeypatch):
    import run_vldocir_pipeline_comparison as driver
    out=tmp_path/'out';plan=_worker_plan(('good','bad'))
    driver.initialize_document_statuses(out,plan)
    _article_artifact(driver,out/'articles/good',membership=True,reading_ready=True)
    _article_artifact(driver,out/'articles/bad',membership=False,reading_ready=False)
    monkeypatch.setattr(driver.subprocess,'run',lambda *a,**k:pytest.fail('existing checkpoint must not call model'))
    good=driver.run_document(out,Path('/model'),plan,'good')
    bad=driver.run_document(out,Path('/model'),plan,'bad')
    assert good['status']=='complete' and good['reused'] is True
    assert bad['status']=='partial' and bad['reused'] is True
    assert 'explicit versioned recovery required' in bad['error']


def test_duplicate_document_workers_lock_and_reuse_one_valid_result(tmp_path,monkeypatch):
    import multiprocessing
    import run_vldocir_pipeline_comparison as driver
    out=tmp_path/'out';plan=_worker_plan(('only',));driver.initialize_document_statuses(out,plan)
    context=multiprocessing.get_context('fork');calls=context.Value('i',0)
    def run(command,check=False):
        with calls.get_lock():calls.value+=1
        _article_artifact(driver,out/'articles/only',membership=True,reading_ready=True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(driver.subprocess,'run',run)
    def target():
        state=driver.run_document(out,Path('/model'),plan,'only')
        assert state['status']=='complete'
    processes=[context.Process(target=target) for _ in range(2)]
    for process in processes:process.start()
    for process in processes:
        process.join(10);assert process.exitcode==0
    assert calls.value==1
    assert json.loads((out/'document_status/only.json').read_text())['status']=='complete'



def test_scope_gate_is_opt_in_and_keeps_legacy_selection_unchanged():
    direct=[('doc',str(i)) for i in range(6)]
    semantic=[(direct[4],{'edge_id':'edge-wrong'}),(direct[5],{'edge_id':'edge-right'})]
    legacy,legacy_trace=select_pages(direct,[],semantic,budget=4,core=2)
    assert legacy==[direct[0],direct[1],direct[4],direct[5]]
    assert [r['decision'] for r in legacy_trace]==['added','added']
    assert all('scope_decision' not in r for r in legacy_trace)


def test_query_scope_gate_rejects_mismatched_decision_object_and_backfills_budget():
    # Mismatch stands for director-election query vs auditor-ratification target.
    direct=[('doc',str(i)) for i in range(7)]
    semantic=[(direct[4],{'edge_id':'auditor-ratification'}),
              (direct[5],{'edge_id':'director-election'})]
    pages,trace=select_pages(direct,[],semantic,budget=4,core=2,
                            scope_decisions={'auditor-ratification':'mismatch',
                                             'director-election':'match'})
    assert pages==[direct[0],direct[1],direct[5],direct[2]]
    assert [row['decision'] for row in trace]==['scope_mismatch','added']
    assert [row['scope_decision'] for row in trace]==['mismatch','match']
    assert len(pages)==len(set(pages))==4


def test_query_scope_gate_abstains_on_missing_edge_and_does_not_touch_reading():
    direct=[('doc',str(i)) for i in range(8)]
    reading=[(direct[4],{'edge_type':'NEXT'})]
    semantic=[(direct[5],{'edge_id':'unknown'})]
    pages,trace=select_pages(direct,reading,semantic,budget=5,core=2,scope_decisions={})
    assert pages==[direct[0],direct[1],direct[4],direct[2],direct[3]]
    assert trace[0]['decision']=='added' and trace[0]['lane']=='reading'
    assert trace[1]['decision']=='scope_abstain'
    assert trace[1]['scope_decision']=='abstain'


def test_query_scope_gate_rejects_invalid_labels():
    direct=[('doc',str(i)) for i in range(5)]
    with pytest.raises(ValueError,match='invalid query-scope decision'):
        select_pages(direct,[],[(direct[4],{'edge_id':'edge'})],budget=4,core=2,
                     scope_decisions={'edge':'maybe'})
