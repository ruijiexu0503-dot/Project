import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_span_evidence_selection as span


def fixture():
    t={'question_id':'q','prompt_sha256':'hash','prompt':'assess','edge_prompt':'edges',
       'coverage_contract':span.CONTRACT,'packets':{'P0':{'text':'2004\nChampion.\n\n2005 runner-up.'}},
       'edges':[{'id':'E0'}]}
    t['source_spans']=span.spans('P0',t['packets']['P0']['text'])
    r={'requirements':[{'id':'F1','text':'winner in 2004'}],
       'packets':[{'id':'P0','score':3,'covers':[{'requirement':'F1','span_ids':['P0:S0000']}]}],'edges':[]}
    return t,r


def test_offsets_preserve_ocr_and_table_headers():
    text='A\nB.\n\nC'
    ss=span.spans('P0',text)
    assert ''.join(s['text'] for s in ss.values())==text
    assert list(ss.values())[0]['text']=='A\nB.\n\n'
    table='<table><tr>Year</tr>\n\n<tr>2004</tr></table>'
    assert len(span.spans('P0',table))==1


def test_wrong_packet_duplicate_and_tampering_rejected():
    t,r=fixture();span.base.validate(r,{**t,'edges':[]})
    for ids in (['P1:S0000'],[],['P0:S0000','P0:S0000']):
        bad=copy.deepcopy(r);bad['packets'][0]['covers'][0]['span_ids']=ids
        with pytest.raises(ValueError):span.base.validate(bad,{**t,'edges':[]})
    t['source_spans']['P0:S0000']['text']='2005 champion'
    with pytest.raises(ValueError):span.base.validate(r,{**t,'edges':[]})


class Model:
    def __init__(self, values):self.values=iter(values);self.calls=[]
    def generate_raw_with_images(self,system,prompt,images,limit):
        self.calls.append(prompt)
        value=next(self.values)
        if isinstance(value,Exception):raise value
        return SimpleNamespace(raw=json.dumps(value))


def test_edge_failure_resume_does_not_repeat_assessment(tmp_path):
    t,r=fixture();path=tmp_path/'q.json'
    model=Model([r,{'edges':[]},{'edges':[]}])
    first=span.process_task(t,path,model,json.loads,'model')
    assert not first['valid'] and first['assessment']==r
    assert len(first['attempts'])==3
    resumed=Model([{'edges':[{'id':'E0','useful':True,'reason':'needed'}]}])
    second=span.process_task(t,path,resumed,json.loads,'model')
    assert second['valid'] and len(resumed.calls)==1 and resumed.calls[0].startswith('edges')
    assert second['assessment']['edges']==[]
    assert len(second['attempts'])==4
    untouched=Model([])
    span.process_task(t,path,untouched,json.loads,'model')
    assert not untouched.calls


def test_crash_retains_assessment_and_stale_checkpoint_rejected(tmp_path):
    t,r=fixture();path=tmp_path/'q.json'
    with pytest.raises(RuntimeError):
        span.process_task(t,path,Model([r,RuntimeError('GPU failure')]),json.loads,'model')
    assert json.loads(path.read_text())['assessment']==r
    with pytest.raises(ValueError,match='stale'):
        span.process_task({**t,'prompt_sha256':'changed'},path,Model([]),json.loads,'model')


def test_deadline_stops_before_generation(tmp_path):
    t,r=fixture();model=Model([])
    state=span.process_task(t,tmp_path/'q.json',model,json.loads,'model',deadline=0)
    assert not state['valid'] and not model.calls
