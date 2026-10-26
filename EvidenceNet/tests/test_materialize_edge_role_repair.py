from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import materialize_edge_role_repair as repair


def fixture(tmp_path):
    prepared=tmp_path/'prepared'
    nodes=[{'id':str(i),'document':'D','page':i,'source_atom_ids':['a'],
            'members':[{'kind':'atom','type':'text','text':text}]} for i,text in enumerate([
                'Our experiment measured a pressure reduction.',
                'The authors declare no competing interests.', 'Reference entry'])]
    augmented={}
    for n,role in zip(nodes,['para','para','reference']):
        rep={'atoms':[{'atom_id':'a','layout_role':role,'atom_type':'text'}]}
        repair.write(prepared/'D'/f"page_{n['page']:04d}"/'input_representation.json',rep)
        augmented[n['id']]=repair.roles.attach_source_roles(n,rep)
    edges=[{'task_id':str(i),'source':'0','target':str(i),'evidence_propagation_allowed':False,
            'model_result':{'kept_verbatim':True}} for i in range(3)]
    repair.jsonl(tmp_path/'nodes.jsonl',nodes);repair.jsonl(tmp_path/'edges.jsonl',edges)
    repair.write(tmp_path/'audit.json',{'edge_audits':[repair.roles.audit_edge(e,augmented) for e in edges]})
    return tmp_path/'nodes.jsonl',tmp_path/'edges.jsonl',prepared,tmp_path/'audit.json',tmp_path/'output'


def test_lossless_separate_routes_and_originals_untouched(tmp_path):
    args=fixture(tmp_path)
    before={p:p.read_bytes() for p in (args[0],args[1],args[3])}
    summary=repair.materialize(*args)
    assert summary['routes']=={'semantic':1,'reference_review':1,'administrative_review':1}
    assert summary['edges_deleted']==0
    assert before=={p:p.read_bytes() for p in before}
    all_edges=[]
    for name in ('related','reference_review','administrative_review'):
        all_edges+=repair.rows(args[-1]/'graph'/(name+'.jsonl'))
    for edge in all_edges:
        edge.pop('source_role_audit')
    assert sorted(all_edges,key=lambda e:e['task_id'])==repair.rows(args[1])
    manifest=repair.read(args[-1]/'manifest.json')
    assert all(repair.sha(args[-1]/n)==h for n,h in manifest['outputs'].items())
    with pytest.raises(ValueError,match='Fresh'):
        repair.materialize(*args)


def test_stale_audit_does_not_create_output(tmp_path):
    args=fixture(tmp_path)
    audit=repair.read(args[3]);audit['edge_audits'][0]['route']='reference_review'
    repair.write(args[3],audit)
    with pytest.raises(ValueError,match='Stale'):
        repair.materialize(*args)
    assert not args[-1].exists()


def test_support_propagation_not_silently_rewritten(tmp_path):
    args=fixture(tmp_path)
    edges=repair.rows(args[1]);edges[0]['evidence_propagation_allowed']=True
    repair.jsonl(args[1],edges)
    with pytest.raises(ValueError,match='non-propagating'):
        repair.materialize(*args)
    assert not args[-1].exists()
