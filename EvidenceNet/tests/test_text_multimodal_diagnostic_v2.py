from copy import deepcopy
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_text_multimodal_diagnostic_v2 import validate,is_multimodal,report


def entry():
    return dict(task=dict(task_id='opaque'),lookups=dict(A={'A:E0':dict(node_id='full-text',member_id='a')},
        B={'B:E0':dict(node_id='composite',member_id='caption'),'B:E1':dict(node_id='composite',member_id='crop')}),
        context_lookup={'C:A:0':dict(source_id='title',text='Named venue',purpose='identity only')})


def answer():
    return dict(task_id='opaque',status='LINK',basis='SAME_SPECIFIC_SUBJECT',A_evidence_ids=['A:E0'],
        B_evidence_ids=['B:E1'],context_evidence_ids=['C:A:0'],reason='The same named venue.',
        limitation='Does not establish wider infrastructure or dates.')


def test_owned_anchors_and_identity_context_remain_separate():
    result=validate(answer(),entry())
    assert result['anchors']['A'][0]['node_id']=='full-text'
    assert result['anchors']['B'][0]['node_id']=='composite'
    assert result['identity_context'][0]['source_id']=='title'


@pytest.mark.parametrize('key,value',[('A_evidence_ids',['B:E1']),('A_evidence_ids',['C:A:0']),
                                     ('A_evidence_ids',[]),('context_evidence_ids',['C:OTHER:0'])])
def test_context_or_foreign_evidence_cannot_replace_endpoint(key,value):
    bad=answer();bad[key]=value
    with pytest.raises(ValueError):validate(bad,entry())


def test_nonidentity_content_correspondence_is_supported():
    value=answer();value['basis']='CONTENT_CORRESPONDENCE';value['context_evidence_ids']=[]
    assert validate(value,entry())['basis']=='CONTENT_CORRESPONDENCE'


def test_nonlink_does_not_publish_an_edge_type():
    value=answer();value.update(status='NO_LINK',basis=None,A_evidence_ids=[],B_evidence_ids=[],context_evidence_ids=[])
    assert validate(value,entry())['status']=='NO_LINK'
    value['basis']='SAME_SPECIFIC_SUBJECT'
    with pytest.raises(ValueError):validate(value,entry())


def test_modality_comes_from_eligible_source_members_not_description_text():
    node=dict(members=[dict(id='v',kind='visual',text='A text description')],eligible_members=[dict(member_id='v',kind='visual',eligible=True)])
    assert is_multimodal(node)
    excluded=deepcopy(node);excluded['eligible_members'][0]['eligible']=False
    assert not is_multimodal(excluded)


def test_unfinished_or_invalid_predictions_are_not_correct_negatives(tmp_path):
    import json
    data=tmp_path/'data';data.mkdir();out=tmp_path/'out';out.mkdir()
    (data/'cases.jsonl').write_text('\n'.join(json.dumps(c) for c in [
        dict(case_id='p',label='LINK',group='g'),dict(case_id='n',label='NO_LINK',group='g')])+'\n')
    (out/'predictions.jsonl').write_text(json.dumps(dict(task_id='n',valid=False,result=None))+'\n')
    summary=report(data,out)
    assert not summary['complete'] and summary['counts']['invalid']==1
    assert summary['counts'].get('tn',0)==0
