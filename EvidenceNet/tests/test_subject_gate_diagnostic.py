import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_subject_gate_diagnostic as diagnostic
import run_article_bridge_binding_v2 as v2


def node(nid,text):
    return {'id':nid,'members':[{'id':'m','kind':'atom','text':text}]}


def annotation(nid,kind='PROJECT',quote='AHEAD'):
    return {'node_id':nid,'event_project_content':[{'kind':kind,'subject_id':'PROJECT:AHEAD',
        'member_id':'m','start':0,'end':len(quote),'quote':quote}]}


def test_manual_subject_labels_do_not_coerce_method_type():
    with pytest.raises(ValueError,match='cannot_retype'):
        diagnostic.oracle_bindings([annotation('a','METHOD')],{'a':node('a','AHEAD')},{'a':'article'})


def test_oracle_keeps_original_span_and_shared_subject_gate():
    ns={'a':node('a','AHEAD provides rescue.'),'b':node('b','AHEAD project partners.')}
    mapping={'a':'one','b':'two'}
    bs=diagnostic.oracle_bindings([annotation('a'),annotation('b')],ns,mapping)
    assert v2.derive_pair({'source':'a','target':'b'},bs)['paths']
    with pytest.raises(ValueError,match='span_changed'):
        diagnostic.oracle_bindings([annotation('a',quote='invented')],ns,mapping)


def test_source_reviewed_method_pair_cannot_pass_unchanged_ep_gate():
    ns={'a':node('a','Graph WaveNet adjacency is fixed.'),'b':node('b','Graph WaveNet is fixed after training.')}
    annotations=[{'node_id':n,'event_project_content':[]} for n in ns]
    bs=diagnostic.oracle_bindings(annotations,ns,{'a':'one','b':'two'})
    assert v2.derive_pair({'source':'a','target':'b'},bs)['status']=='NO_SHARED_VERIFIED_SUBJECT'
