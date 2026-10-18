import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_traffic_relevance_graph as graph


def value(status='ACCEPT'):
    return {'status':status,'relation':'METHOD_CORRESPONDENCE','source_content':'describes mechanism',
        'target_content':'applies mechanism','shared_mechanism':'specific attention operation',
        'conditions':'different tasks','reason':'source grounded','A_evidence_ids':['A:T0'],'B_evidence_ids':['B:T0']}


def test_accept_requires_each_endpoint_own_evidence():
    lookup={'A':{'A:T0':{'kind':'TEXT'}},'B':{'B:T0':{'kind':'TEXT'}}}
    assert graph.validate(value(),lookup)['review_status']=='MODEL_PROPOSAL_SOURCE_REVIEW_REQUIRED'
    v=value();v['A_evidence_ids']=['B:T0']
    with pytest.raises(ValueError,match='anchor_ownership'):graph.validate(v,lookup)
    v=value();v['B_evidence_ids']=[]
    with pytest.raises(ValueError,match='missing_endpoint'):graph.validate(v,lookup)


def test_visual_proof_requires_observation_not_just_description():
    lookup={'A':{'A:T0':{'kind':'VISUAL'}},'B':{'B:T0':{'kind':'TEXT'}}}
    with pytest.raises(ValueError,match='visual_observation'):graph.validate(value(),lookup)


def test_reject_can_have_no_evidence_or_relation():
    v=value('REJECT');v.update(relation='NONE',A_evidence_ids=[],B_evidence_ids=[])
    assert graph.validate(v,{'A':{},'B':{}})['status']=='REJECT'


def test_candidates_do_not_require_subjects_or_use_relevance_labels(tmp_path,monkeypatch):
    import numpy as np
    import run_node_embedding_geometry_pilot as embeddings
    monkeypatch.setattr(graph,'check',lambda root:None)
    monkeypatch.setattr(embeddings,'embed',lambda texts,path:np.array([[1.,0.],[.8,.6],[.6,.8],[0.,1.]]))
    out=tmp_path/'graph';out.mkdir()
    nodes=[{'id':str(i),'document':doc,'members':[{'text':'specific method'}]} for i,doc in enumerate(['paper1','paper1','paper2','paper3'])]
    graph.jsonl(out/'units.jsonl',nodes);graph.write(out/'eligibility.json',{str(i):{'eligible':True} for i in range(4)})
    graph.candidates(tmp_path)
    pairs=graph.rows(out/'semantic_candidates.jsonl')
    assert {p['scope'] for p in pairs}=={'cross_document','intra_article'}
    assert len(pairs)==6
    assert graph.read(out/'candidate_policy.json')['shared_subject_required'] is False
