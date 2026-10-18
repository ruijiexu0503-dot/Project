import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_traffic_relevance_cpu as cpu


def inputs(tmp_path):
    out=tmp_path/'graph';out.mkdir()
    cpu.write(tmp_path/'prepared/manifest.json',{'batches':[]})
    nodes=[{'id':str(i),'document':str(i),'page':1,'members':[{'id':'m','kind':'atom',
        'role':'para','text':'This method applies a specific diffusion convolution mechanism.'}]} for i in range(3)]
    cpu.graph.jsonl(out/'units.jsonl',nodes)
    from node_context_policy import eligibility
    cpu.graph.write(out/'eligibility.json',eligibility(nodes))
    queue=[{'pair_id':f'pair{i}','source':str(a),'target':str(b)} for i,(a,b) in enumerate([(0,1),(0,2),(1,2)])]
    cpu.graph.jsonl(out/'semantic_candidates.jsonl',queue)
    return out


class FakeModel:
    def __init__(self,device='cpu'):
        self.calls=0
        self.model=SimpleNamespace(parameters=lambda:iter([SimpleNamespace(device=device)]))

    def generate_raw_with_images(self,system,prompt,images,tokens):
        self.calls+=1
        public=json.loads(prompt.rsplit('\n',1)[-1])
        result={'status':'ACCEPT','relation':'METHOD_CORRESPONDENCE','source_content':'diffusion convolution',
            'target_content':'diffusion convolution','shared_mechanism':'diffusion convolution',
            'conditions':'','reason':'Both describe the mechanism.',
            'A_evidence_ids':[public['A'][0]['id']],'B_evidence_ids':[public['B'][0]['id']]}
        return SimpleNamespace(raw=json.dumps(result))


def test_smoke_keeps_checkpoints_but_does_not_publish_complete_graph(tmp_path,monkeypatch):
    out=inputs(tmp_path);model=FakeModel()
    monkeypatch.setattr(cpu.graph,'check',lambda root:None)
    monkeypatch.setattr(cpu.models,'create_llm',lambda config:model)
    original_rows=cpu.graph.rows
    cpu.verify(tmp_path,smoke=True)
    assert model.calls==2
    assert len(list((out/'decisions').glob('*.json')))==2
    assert not (out/'semantic_edges.jsonl').exists()
    assert cpu.read(out/'summary.json')['phase']=='PARTIAL_OR_PENDING'
    assert cpu.graph.rows is original_rows
    cpu.verify(tmp_path,max_hours=48)
    assert model.calls==3  # existing smoke decisions resume without new inference
    assert len(cpu.rows(out/'semantic_edges.jsonl'))==3
    assert cpu.read(out/'cpu_full_status.json')['pairs']==3


def test_runtime_gate_defers_before_loading_model(tmp_path,monkeypatch):
    out=inputs(tmp_path)
    cpu.write(out/'cpu_smoke.json',{'state':'COMPLETE','all_valid':True,'projected_full_hours_with_margin':100})
    def forbidden(config):raise AssertionError('Model must not load for deferred run')
    monkeypatch.setattr(cpu.models,'create_llm',forbidden)
    cpu.verify(tmp_path,max_hours=40)
    assert cpu.read(out/'cpu_full_status.json')['state']=='DEFERRED_RUNTIME_ESTIMATE'


def test_cpu_run_rejects_accidental_gpu_placement(tmp_path,monkeypatch):
    inputs(tmp_path)
    monkeypatch.setattr(cpu.models,'create_llm',lambda config:FakeModel('cuda:0'))
    with pytest.raises(ValueError,match='non_cpu_model_placement'):
        cpu.verify(tmp_path,smoke=True)
