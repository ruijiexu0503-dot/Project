import sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from replay_article_bridge_identity_v3 import identity_gate, name_span, publish_intra


def fixture(text='GW150914 was detected.'):
    anchor = {'kind':'TEXT','node_id':'a','article_id':'paper','member_id':'m',
              'char_start':0,'char_end':len(text),'quote':text}
    nodes = {'a':{'members':[{'kind':'atom','id':'m','text':text}]}}
    binding = {'binding_id':'b','node_id':'a','article_id':'paper','subject_id':'s','status':'SUPPORTED',
               'purposes':['content_index'],'original_local_catalog':[anchor],
               'decision':{'status':'SUPPORTED','aspect_type':'other','local_anchors':[anchor],'context_sources':[]}}
    return binding, {'source_spellings':['GW150914']}, nodes, {'a':'paper'}


def test_hypothesized_event_cannot_turn_generic_noise_into_identity():
    args=fixture('20 Hz agrees with the official advanced LIGO design noise curve.')
    result=identity_gate(*args)
    assert result['status']=='UNRESOLVED'
    assert args[0]['status']=='SUPPORTED'
    assert result['model_status']=='SUPPORTED'


def test_exact_identity_preserved_and_substring_or_fabricated_quote_blocked():
    args=fixture()
    assert identity_gate(*args)['status']=='SUPPORTED'
    assert name_span('GW1509140', ['GW150914']) is None
    args[0]['original_local_catalog'][0]['quote']='GW150914 fabricated'
    assert identity_gate(*args)['status']=='UNRESOLVED'


def test_unnamed_figure_can_use_explicit_same_article_reference():
    b,s,n,m=fixture('Posterior mass distribution.')
    text='GW150914 parameters are shown in Fig. 1.'
    n['ctx']={'members':[{'kind':'atom','id':'c','text':text}]};m['ctx']='paper'
    anchor={'kind':'TEXT','node_id':'ctx','article_id':'paper','member_id':'c','char_start':0,'char_end':len(text),'quote':text}
    ref={'source':'ctx','target':'a','source_member':'c','source_start':text.index('Fig.'),'source_end':text.index('Fig.')+6,
         'source_quote':'Fig. 1','target_member':'m','target_quote':n['a']['members'][0]['text'],
         'verification':'unique marker within confirmed article identity'}
    b['decision']['context_sources']=[{'source_node':'ctx','target_node':'a','anchor':anchor,'reference':ref}]
    assert identity_gate(b,s,n,m)['status']=='SUPPORTED'
    m['ctx']='other-paper'
    assert identity_gate(b,s,n,m)['status']=='UNRESOLVED'
    m['ctx']='paper';ref['target_quote']='wrong caption'
    assert identity_gate(b,s,n,m)['status']=='UNRESOLVED'


def test_same_article_publication_excludes_probe_and_unresolved_bindings():
    a=fixture()[0];b=deepcopy(a);b.update(node_id='b',binding_id='bb')
    assert len(publish_intra([a,b]))==1
    b['purposes']=['negative_binding_probe']
    assert publish_intra([a,b])==[]
    b['purposes']=['content_index'];b['status']='UNRESOLVED'
    assert publish_intra([a,b])==[]
