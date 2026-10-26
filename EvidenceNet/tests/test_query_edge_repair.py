import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_query_edge_repair as repair
from evaluate_vldocir import TYPES
from run_cached_query_reranker import input_sha


def test_candidates_keep_core_deduplicate_and_fill():
    direct=[('D',str(i)) for i in range(30)]
    paths=[{'id':'a','target_page':['D','29']}, {'id':'b','target_page':['D','29']},
           {'id':'c','target_page':['D','2']}]
    selected=repair.select_candidates(direct,paths)
    assert selected[:10]==direct[:10]
    assert len(selected)==len(set(selected))==20
    assert direct[29] in selected and direct[19] not in selected
    assert repair.select_candidates(direct,paths,set())==direct[:20]
    assert repair.select_candidates(direct,paths,{'c'})==direct[:20]
    assert direct==[('D',str(i)) for i in range(30)]


def test_candidate_foreign_page_and_bad_budget_rejected():
    with pytest.raises(ValueError,match='outside'):
        repair.select_candidates([('D','1')],[{'id':'x','target_page':['OTHER','1']}])
    with pytest.raises(ValueError,match='budget'):
        repair.select_candidates([],[],budget=5)
    with pytest.raises(ValueError,match='Duplicate'):
        repair.select_candidates([('D','1'),('D','1')],[])


def fixture(out, route='semantic', role='DIRECT'):
    paths=[];contexts=[];inputs=[];scores=[];queries=[];gold=[];predictions=[]
    for qi,kind in enumerate(TYPES):
        qid=f'q{qi}';query=f'What was the outcome of experiment {qi}?'
        direct=[('D',str(i)) for i in range(25)]
        record={'query':query,'seed_hit':{'text':'cached locator'},
                'source':{'anchor':'The experiment used valves.'},
                'target':{'anchor':'The experiment reduced pressure.'}}
        path={'id':qid,'question_id':qid,'target_page':direct[-1],
              'source_role_route':route,'input':record,
              'prompt_sha256':repair.digest(repair.gate.make_prompt(record))}
        paths.append(path)
        page_ids={}
        for i,page in enumerate(direct[:20]+direct[-1:]):
            row={'id':f'{qid}-{i}','query':query,'text':f'page {page}'}
            inputs.append(row)
            scores.append({'id':row['id'],'input_sha256':input_sha(row),
                           'score':100 if page==direct[-1] else -i,
                           'original_tokens':10,'truncated':False})
            page_ids[json.dumps(page)]=[row['id']]
        contexts.append({'question_id':qid,'question':query,'direct_ranking':direct,
                         'path_ids':[qid],'page_reranker_ids':page_ids})
        queries.append({'question_id':qid,'question':query,'question_type':kind})
        gold.append({'question_id':qid,'document_id':'D','page_number':0})
        result={'role':role,'reason':'Test-only model stub; no scientific result.',
                'source_quote':'The experiment used valves.',
                'target_quote':'The experiment reduced pressure.',
                'answered_aspect':'Outcome' if role=='DIRECT' else '', 'bridge_step':''}
        predictions.append({'id':qid,'prompt_sha256':path['prompt_sha256'],'valid':True,'result':result})
    for name,data in [('gate_inputs',paths),('query_contexts',contexts),('reranker_inputs',inputs),
                      ('gate_predictions',predictions),('reranker_scores',scores),
                      ('eval_queries',queries),('eval_gold_evidence',gold)]:
        repair.jsonl(out/(name+'.jsonl'),data)
    repair.write(out/'protocol.json',{'test_fixture':True})
    repair.write(out/'manifest.json',{'files':{n.name:repair.sha(n) for n in out.iterdir()
                       if n.name not in {'gate_predictions.jsonl','reranker_scores.jsonl'}},'code':{}})


@pytest.mark.parametrize('route,role,changes', [('semantic','DIRECT',6),
                        ('semantic','UNSUPPORTED',0),('reference_review','DIRECT',0)])
def test_full_report_isolates_reranker_and_graph_effects(tmp_path,route,role,changes):
    fixture(tmp_path,route,role)
    repair.report(tmp_path)
    result=repair.read(tmp_path/'results.json')
    assert result['complete']
    assert result['metrics']['cached_dense']['mAP@5']==1
    assert result['metrics']['dense_rerank']['mAP@5']==1
    assert result['metrics']['graph_rerank']['mAP@5']==.5
    assert result['candidate_set_changes_vs_dense20']['query_gate_graph_rerank']==changes
    expected=.5 if changes else 1
    assert result['metrics']['query_gate_graph_rerank']['mAP@5']==expected
    assert result['paired']['graph_rerank']['control']=='dense_rerank'
    assert result['paired']['graph_rerank']['AP@5_losses']==6
    assert repair.read(tmp_path/'status.json')['complete']
    traces=repair.rows(tmp_path/'search_paths.jsonl')
    assert len(traces)==6 and len(traces[0]['paths'])==1


def test_report_rejects_scores_for_changed_text(tmp_path):
    fixture(tmp_path)
    scores=repair.rows(tmp_path/'reranker_scores.jsonl')
    scores[0]['input_sha256']='wrong'
    repair.jsonl(tmp_path/'reranker_scores.jsonl',scores)
    with pytest.raises(ValueError,match='content mismatch'):
        repair.report(tmp_path)


def test_report_does_not_publish_incomplete_metrics(tmp_path):
    fixture(tmp_path)
    repair.jsonl(tmp_path/'gate_predictions.jsonl',[])
    repair.report(tmp_path)
    assert not repair.read(tmp_path/'status.json')['complete']
    assert not (tmp_path/'results.json').exists()


def test_frozen_input_change_fails_closed(tmp_path):
    fixture(tmp_path)
    repair.jsonl(tmp_path/'eval_gold_evidence.jsonl',[])
    with pytest.raises(ValueError,match='Changed input'):
        repair.report(tmp_path)
