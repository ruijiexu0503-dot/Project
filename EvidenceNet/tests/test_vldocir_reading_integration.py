import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_node_context_edges import jsonl,write,sha
import check_vldocir_reading_integration as integration
import vldocir_reading_backbone as backbone


def article_root(tmp_path):
    root=tmp_path/'article'
    nodes=[{'id':'a','document':'doc','page':1},{'id':'b','document':'doc','page':2},
           {'id':'singleton','document':'doc','page':2}]
    assignments=[{'node_id':node['id'],'article_id':'doc::article'} for node in nodes]
    edges=[{'source':'a','target':'b','type':'NEXT','article_id':'doc::article','cross_page':True}]
    jsonl(root/'units.jsonl',nodes);jsonl(root/'article_assignments.jsonl',assignments)
    jsonl(root/'reading_edges.jsonl',edges)
    files={name:sha(root/name) for name in ('article_assignments.jsonl','reading_edges.jsonl')}
    write(root/'article_graph_manifest.json',{'ready_for_downstream':True,'reading_ready':True,'files':files})
    return root


def test_validated_import_creates_inverse_and_every_edge_is_navigable(tmp_path):
    root=article_root(tmp_path);out=tmp_path/'integration'
    report=integration.run([root],out)
    assert report['complete'] and report['directed_edges']==2
    assert report['next_paths']==report['previous_paths']==1
    assert report['cross_page_paths']==2 and not report['retrieval_quality_measured']
    paths=[json.loads(line) for line in (out/'navigation_paths.jsonl').read_text().splitlines()]
    assert {(row['seed_node'],row['target_node'],row['edge_type']) for row in paths}=={
        ('a','b','NEXT'),('b','a','PREVIOUS')}


def test_navigation_rejects_unknown_seed(tmp_path):
    nodes={'a':{'id':'a','document':'doc','page':1}}
    with pytest.raises(ValueError,match='unknown reading seed'):
        backbone.navigate(nodes,[],['missing'])


def test_import_rejects_known_failed_cross_page_gate(tmp_path):
    root=article_root(tmp_path)
    manifest=json.loads((root/'article_graph_manifest.json').read_text())
    manifest.update(cross_page_evaluated=True,cross_page_ready=False)
    write(root/'article_graph_manifest.json',manifest)
    with pytest.raises(ValueError,match='incomplete cross-page'):
        backbone.build(root/'units.jsonl',[root],tmp_path/'out')
