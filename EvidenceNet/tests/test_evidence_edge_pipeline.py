import copy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import run_evidence_edge_pipeline as pipeline
from run_node_context_edges import read, rows, write, jsonl


def corpus(tmp_path):
    nodes = []
    for i in range(3):
        nodes.append({'id': f'n{i}', 'document': f'd{i}', 'article_id': f'd{i}::article',
            'page': 1, 'members': [{'id':'m', 'kind':'atom', 'type':'text',
            'text':'DCRNN models graph diffusion and recurrent temporal dependencies.', 'boxes':[[0,0,10,10]]}]})
    policies = {n['id']: {'eligible':True,'members':[{'kind':'atom','member_id':'m','eligible':True}]} for n in nodes}
    jsonl(tmp_path/'nodes.jsonl',nodes)
    write(tmp_path/'policies.json',policies)
    model = tmp_path/'model'
    write(model/'config.json',{'model_type':'test'})
    write(model/'tokenizer.json',{'test':True})
    return nodes, policies, model


def prepare(tmp_path):
    nodes, policies, model = corpus(tmp_path)
    out = tmp_path/'run'
    pipeline.prepare(out,tmp_path/'nodes.jsonl',tmp_path/'policies.json','qwen3-8b',model,
                     budget=3,escape_budget=1,reference_budget=1)
    return out, model


def test_prepare_excludes_unknown_and_ineligible_without_mutating_input(tmp_path):
    ns, policies, model=corpus(tmp_path)
    ns[0]['article_id']='UNKNOWN'; policies['n1']['members'][0]['eligible']=False
    jsonl(tmp_path/'nodes.jsonl',ns);write(tmp_path/'policies.json',policies)
    original=(tmp_path/'nodes.jsonl').read_bytes()
    pipeline.prepare(tmp_path/'run',tmp_path/'nodes.jsonl',tmp_path/'policies.json','qwen3-8b',model)
    views=rows(tmp_path/'run/views.jsonl')
    assert {v['node_id'] for v in views}=={'n2'}
    assert (tmp_path/'nodes.jsonl').read_bytes()==original
    assert read(tmp_path/'run/config.json')['embedding']['profile']=='qwen3-8b'
    with pytest.raises(ValueError,match='Fresh output'):
        pipeline.prepare(tmp_path/'run',tmp_path/'nodes.jsonl',tmp_path/'policies.json','qwen3-8b',model)


def test_profile_pooling_and_cache_invalidation(tmp_path,monkeypatch):
    out, model=prepare(tmp_path)
    calls=[]
    def encoder(texts,path,batch,length,device,pooling,padding):
        calls.append((pooling,padding));return np.eye(len(texts),dtype=np.float32),{'mock':True}
    monkeypatch.setattr(pipeline.encoders,'embed',encoder)
    pipeline.embed(out,'cpu');pipeline.embed(out,'cpu')
    assert calls==[('last_token','left')]
    assert pipeline.model_identity('bge-large-en',model)['pooling']=='cls'
    write(model/'tokenizer.json',{'changed':True})
    with pytest.raises(ValueError,match='Encoder profile'):
        pipeline.embed(out,'cpu')


@pytest.mark.parametrize('vectors',[np.zeros((3,2)),np.ones((2,2)),np.array([[np.nan]]),np.ones(3)])
def test_invalid_vectors(vectors):
    with pytest.raises(ValueError):pipeline.validate_vectors(vectors,3)


def entry_and_prediction(decision,basis,shared=None):
    entry={'task':{'task_id':'t','A':{'node_id':'a'},'B':{'node_id':'b'}}}
    result={'decision':decision,'basis':basis,'discovery_level':2,'shared_identity':shared,
            'matched_claim':'same bounded claim','anchors':{s:[{'kind':'ORIGINAL_TEXT'}] for s in ['A','B']}}
    return entry,{'valid':True,'result':result}


def test_navigation_without_identity_quarantined_not_silently_relabelled():
    entry,p=entry_and_prediction('NAVIGATION_LINK','SHARED_NAMED_COMPONENT')
    saved=copy.deepcopy(p)
    bucket,record=pipeline.export_record(entry,p,set())
    assert bucket=='review' and 'navigation_missing_checked_identity' in record['review_reasons']
    assert p==saved and not record['evidence_propagation_allowed']


def test_direct_complement_without_pointer_and_all_propagation_blocked():
    entry,p=entry_and_prediction('EVIDENCE_LINK','DIRECT_COMPLEMENT')
    assert pipeline.export_record(entry,p,set())[0]=='review'
    bucket,record=pipeline.export_record(entry,p,{('a','b')})
    assert bucket=='related' and record['edge_type']=='RELATED'
    assert record['direction']=='UNDIRECTED' and not record['evidence_propagation_allowed']


def source_role_node(node_id, roles, text='A bounded mechanism is described.'):
    """Match the adapter's generic text member plus exact parser provenance."""
    atom_ids = [f'{node_id}_atom_{i}' for i in range(len(roles))]
    node = {'id': node_id, 'node_type': 'TEXT', 'source_atom_ids': atom_ids,
            'members': [{'id': f'{node_id}_text', 'kind': 'atom', 'type': 'text',
                         'role': 'text', 'text': text}]}
    representation = {'atoms': [
        {'atom_id': atom_id, 'atom_type': 'text', 'layout_role': role}
        for atom_id, role in zip(atom_ids, roles)]}
    return pipeline.edge_source_roles.attach_source_roles(node, representation)


def test_administrative_statement_goes_to_separate_review_not_rejected():
    entry, prediction = entry_and_prediction('EVIDENCE_LINK', 'CLAIM_CORRESPONDENCE')
    nodes = {key: source_role_node(key, ['para']) for key in ('a', 'b')}
    nodes['a'] = source_role_node('a', ['para'], 'The authors declare no competing interests.')
    bucket, record = pipeline.export_record(entry, prediction, set(), nodes=nodes)
    assert bucket == 'review'
    assert record['source_role_audit']['route'] == 'administrative_review'
    assert record['model_result'] == prediction['result']
    assert not record['evidence_propagation_allowed']
    assert record['review_reasons'] == ['administrative_boilerplate_requires_separate_review']


@pytest.mark.parametrize('endpoint', ['a', 'b'])
@pytest.mark.parametrize('source_roles,expected_role', [
    (['reference'], 'bibliography'),
    (['bibliography'], 'bibliography'),
    (['reference', 'para'], 'mixed_bibliography'),
])
def test_export_routes_exact_bibliography_provenance_to_reference_review(endpoint, source_roles, expected_role):
    entry, prediction = entry_and_prediction('EVIDENCE_LINK', 'CLAIM_CORRESPONDENCE')
    nodes = {key: source_role_node(key, ['para']) for key in ('a', 'b')}
    nodes[endpoint] = source_role_node(endpoint, source_roles)
    saved = copy.deepcopy((entry, prediction, nodes))

    bucket, record = pipeline.export_record(entry, prediction, set(), nodes=nodes)

    assert bucket == 'review'
    assert 'edge_type' not in record
    assert record['review_reasons'] == ['bibliography_or_unresolved_source_requires_reference_review']
    assert record['source_role_audit']['route'] == 'reference_review'
    side = 'source' if endpoint == 'a' else 'target'
    assert record['source_role_audit']['endpoints'][side]['role'] == expected_role
    assert record['source_role_audit']['edge_id'] == entry['task']['task_id']
    assert record['direction'] == 'UNDIRECTED'
    assert not record['evidence_propagation_allowed']
    assert (entry, prediction, nodes) == saved


@pytest.mark.parametrize('source_roles,text', [
    (['para'], 'We use SSIM [31] and compare PSNR in Table 2.'),
    (['body_text'], 'Wang, Z.: Image quality assessment. IEEE Transactions 13, 600–612 (2004).'),
    ([], 'Wang et al. (2004) introduced SSIM; our model improves its score by 0.02.'),
])
def test_export_keeps_body_content_and_inline_citations_on_semantic_route(source_roles, text):
    entry, prediction = entry_and_prediction('EVIDENCE_LINK', 'CLAIM_CORRESPONDENCE')
    nodes = {'a': source_role_node('a', source_roles, text),
             'b': source_role_node('b', ['para'])}

    bucket, record = pipeline.export_record(entry, prediction, set(), nodes=nodes)

    assert bucket == 'related'
    assert record['edge_type'] == 'RELATED'
    assert record['source_role_audit']['route'] == 'semantic'
    assert not record['evidence_propagation_allowed']


def test_export_preserves_reference_pointer_contract_without_bypassing_source_role_review():
    entry, prediction = entry_and_prediction('EVIDENCE_LINK', 'DIRECT_COMPLEMENT')
    nodes = {key: source_role_node(key, ['para']) for key in ('a', 'b')}
    reference_keys = {('a', 'b')}

    no_pointer_bucket, no_pointer = pipeline.export_record(entry, prediction, set(), nodes=nodes)
    assert no_pointer_bucket == 'review'
    assert no_pointer['review_reasons'] == ['direct_complement_without_verified_source_pointer_requires_review']
    assert pipeline.export_record(entry, prediction, reference_keys, nodes=nodes)[0] == 'related'

    # A known pointer remains available to the separate citation workflow; it
    # does not turn a bibliography endpoint into empirical semantic evidence.
    nodes['b'] = source_role_node('b', ['reference'])
    saved = copy.deepcopy((reference_keys, nodes, prediction))
    bucket, record = pipeline.export_record(entry, prediction, reference_keys, nodes=nodes)
    assert bucket == 'review'
    assert record['source_role_audit']['route'] == 'reference_review'
    assert record['review_reasons'] == ['bibliography_or_unresolved_source_requires_reference_review']
    assert (reference_keys, nodes, prediction) == saved


def test_export_missing_endpoint_is_reviewed_without_deleting_reference_pointer():
    entry, prediction = entry_and_prediction('EVIDENCE_LINK', 'CLAIM_CORRESPONDENCE')
    nodes = {'a': source_role_node('a', ['para'])}
    reference_keys = {('a', 'b')}
    bucket, record = pipeline.export_record(entry, prediction, reference_keys, nodes=nodes)
    assert bucket == 'review'
    assert record['source_role_audit']['endpoints']['target']['role'] == 'missing_node'
    assert reference_keys == {('a', 'b')}


def test_offline_end_to_end_and_resume(tmp_path,monkeypatch):
    out, model=prepare(tmp_path)
    monkeypatch.setattr(pipeline.encoders,'embed',lambda texts,*args:(np.eye(len(texts),dtype=np.float32),{'mock':True}))
    pipeline.embed(out,'cpu')
    result=pipeline.retrieve(out)
    assert 0 < result['candidates'] <= 3
    assert pipeline.retrieve(out)['status']=='CANDIDATES_ALREADY_FROZEN'
    image=tmp_path/'source.png';image.write_bytes(b'mocked image for offline pipeline plumbing')
    monkeypatch.setattr(pipeline.multimodal,'node_crop',lambda node,dest:image)
    prepared=pipeline.prepare_verifier(out,model)
    assert not prepared['preparation_failures']
    entries=rows(out/'verifier/control/inputs.jsonl')
    cache=[]
    for entry in entries:
        raw={'task_id':entry['task']['task_id'],'discovery_level':2,'decision':'EVIDENCE_LINK',
             'basis':'CLAIM_CORRESPONDENCE','shared_identity':None,'identity_conflicts':[],
             'A_evidence_ids':['A:E000'],'B_evidence_ids':['B:E000'],
             'matched_claim':'Both describe graph diffusion.','reason':'Bounded mechanism.','limitation':'Different documents.'}
        cache.append({'task_id':raw['task_id'],'inference_key':entry['inference_key'],'valid':True,
            'result':pipeline.verifier.gate.validate(raw,entry),'executed_arm':'control',
            'attempts':[{'raw':json.dumps(raw),'valid':True}],'metadata_repairs':[]})
    jsonl(out/'verifier/cache.jsonl',cache)
    frozen_references = (out/'reference_candidates.jsonl').read_bytes()
    summary=pipeline.export(out)
    assert summary['complete'] and summary['counts']['related']==len(entries)
    assert not summary['automatic_evidence_propagation']
    assert (out/'reference_candidates.jsonl').read_bytes() == frozen_references
    assert all(record['source_role_audit']['route'] == 'semantic'
               for record in rows(out/'graph/related.jsonl'))
    # Completed runs exit before importing/loading any GPU model.
    pipeline.run_verifier(out,model,tmp_path,1)
    assert pipeline.verifier.ARMS==('control','multimodal_context','text_scope','text_readable')
    assert read(out/'verifier/summary.json')['complete']


def test_tampered_candidate_rejected(tmp_path,monkeypatch):
    out,model=prepare(tmp_path)
    monkeypatch.setattr(pipeline.encoders,'embed',lambda texts,*args:(np.eye(len(texts),dtype=np.float32),{}))
    pipeline.embed(out,'cpu');pipeline.retrieve(out)
    jsonl(out/'node_candidates.jsonl',[])
    with pytest.raises(ValueError,match='Changed artifact'):
        pipeline.prepare_verifier(out,model)
