import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import pytest
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
