import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_kg_link_prediction_v2 as kg


def jsonl(path,values):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(value)+'\n' for value in values))


def test_text_attributes_preserve_empty_nodes_without_inventing_text():
    full=kg.entity_record({'id':'a','document':'d','page':1,'node_type':'TABLE',
        'members':[{'text':'row one'},{'text':'row two'}]})
    empty=kg.entity_record({'id':'b','document':'d','page':1,'node_type':'TEXT',
        'members':[{'text':''}]})
    assert full['text']=='row one\n\nrow two' and full['text_available']
    assert empty['text']=='' and not empty['text_available']
    assert full['text_source']=='members[].text'


def test_baseline_pool_is_canonical_and_not_relabelled_as_new():
    nodes={'a':{'document':'d1'},'b':{'document':'d2'}}
    result=kg.normalize_baseline_candidates([{'source':'b','target':'a','retrieval_score':.5}],nodes)
    assert result[0]['canonical_source_id']=='a'
    assert result[0]['canonical_target_id']=='b'
    assert result[0]['is_new_to_baseline'] is False
    assert result[0]['candidate_scope']=='cross_document'


def test_full_v2_preparation_keeps_full_universe_and_partial_reading_explicit(tmp_path):
    source=tmp_path/'source';reading=tmp_path/'reading';out=tmp_path/'out'
    nodes=[{'id':'a','document':'d1','page':1,'node_type':'TEXT','members':[{'text':'alpha'}]},
           {'id':'b','document':'d1','page':2,'node_type':'TABLE','members':[{'text':'beta'}]},
           {'id':'c','document':'d2','page':1,'node_type':'TEXT','members':[{'text':''}]}]
    jsonl(source/'nodes.jsonl',nodes)
    jsonl(source/'views.jsonl',[{'view_id':'v1','node_id':'a'},{'view_id':'v2','node_id':'b'}])
    source.mkdir(parents=True,exist_ok=True)
    np.save(source/'view_vectors.npy',np.zeros((2,4),dtype=np.float32))
    (source/'embedding_manifest.json').write_text('{}')
    jsonl(source/'node_candidates.jsonl',[{'source':'a','target':'b','retrieval_score':.3}])
    edge={'source':'a','target':'b','task_id':'t','status':'MODEL_PROPOSED_NOT_HUMAN_VERIFIED',
          'model_result':{'matched_claim':'related','anchors':{'A':[1],'B':[2]}}}
    jsonl(source/'graph/related.jsonl',[edge]);jsonl(source/'graph/review.jsonl',[])
    jsonl(source/'graph/rejected.jsonl',[])

    jsonl(reading/'bounded_nodes.jsonl',nodes[:2])
    directed=[{'source':'a','target':'b','type':'NEXT','edge_type':'NEXT','cross_page':True},
              {'source':'b','target':'a','type':'PREVIOUS','edge_type':'PREVIOUS','cross_page':True}]
    jsonl(reading/'graph/reading_edges.jsonl',directed)
    (reading/'graph/reading_summary.json').write_text('{}')
    graph_files={name:kg.sha(reading/'graph'/name) for name in ('reading_edges.jsonl','reading_summary.json')}
    (reading/'graph/reading_manifest.json').write_text(json.dumps({'files':graph_files}))
    report={'complete':True,'directed_edges':2,'navigated_paths':2}
    (reading/'integration_report.json').write_text(json.dumps(report))
    (reading/'navigation_paths.jsonl').write_text('')
    integration_files={name:kg.sha(reading/name) for name in
        ('bounded_nodes.jsonl','navigation_paths.jsonl','integration_report.json')}
    (reading/'integration_manifest.json').write_text(json.dumps({'files':integration_files}))

    audit=kg.prepare(source,reading,out,review_per_group=0)
    assert audit['corpus']=={'documents':2,'pages':3,'nodes':3,
        'modalities':{'TEXT':2,'TABLE':1}}
    assert audit['text']['available']==2 and audit['text']['empty']==1
    assert audit['frozen_embeddings']['primary_fair_comparison_nodes']==2
    assert audit['reading']['validated_assignment_nodes']==2
    assert audit['reading']['next_edges']==audit['reading']['previous_edges']==1
    assert audit['semantic']['ground_truth'] is False
    assert audit['protocol']['execution']['candidate_generation_run'] is False
    assert len(kg.rows(out/'candidate_universe.jsonl'))==3
    assert len(kg.rows(out/'baseline_candidate_pairs.jsonl'))==1
    kg.check(out)
