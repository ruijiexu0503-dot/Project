import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import compare_retrieval_text_views as c


def fixture():
    members = [dict(id='a',kind='atom',text='A general method maps local dependencies. Another specific method learns global features. However, its structure remains fixed after training.'),
               dict(id='v',kind='visual',text='A diagram showing branches and feature fusion in an image model.'),
               dict(id='table',kind='atom',text='<table><tr><td>Data</td><td>Size</td></tr><tr><td>Example</td><td>20</td></tr></table>'),
               dict(id='footer',kind='atom',text='Excluded copyright and author contact information.')]
    n=dict(id='node',article_id='paper',members=members)
    policies={'node':dict(eligible=True,members=[dict(member_id=m['id'],kind=m['kind'],eligible=m['id']!='footer') for m in members])}
    return {'node':n}, policies


def test_sentence_offsets_and_anaphoric_context_are_source_owned():
    nodes, policies=fixture()
    views=c.text_views(nodes,policies,'sentence')
    context=next(v for v in views if v['kind']=='sentence_context' and 'However' in v['quote'])
    assert context['quote'].startswith('Another specific method')
    member=nodes['node']['members'][0]['text']
    assert member[context['char_start']:context['char_end']]==context['quote']
    assert member[context['focus_char_start']:context['focus_char_end']].startswith('However')


def test_nontext_views_identical_and_excluded_text_never_leaks():
    nodes,policies=fixture()
    reference=None
    for arm in c.ARMS:
        views=c.text_views(nodes,policies,arm)
        special=[{k:v for k,v in x.items() if k!='view_id'} for x in views if x['member_id'] in {'v','table'}]
        special=sorted(special,key=lambda x:(x['member_id'],x['kind'],x['char_start']))
        if reference is None:reference=special
        assert special==reference
        assert all('Excluded copyright' not in x['retrieval_text'] for x in views)
        assert {x['node_id'] for x in views}=={'node'}
        assert len({x['view_id'] for x in views})==len(views)


def test_whole_view_records_each_original_span_and_has_no_fake_member():
    nodes,policies=fixture()
    v=next(v for v in c.text_views(nodes,policies,'whole') if v['kind']=='whole_text_node')
    assert v['member_id'] is None and v['quote'] is None
    assert v['source_spans'][0]['member_id']=='a'
    assert v['source_spans'][0]['quote']==nodes['node']['members'][0]['text']


def test_sentence_split_preserves_abbreviations_and_dehyphenation_offsets():
    text='See Fig. 2 for the archi-\ntecture. A separate result improves accuracy.'
    spans=c.sentence_spans(text)
    assert len(spans)==2
    assert text[spans[0][0]:spans[0][1]].startswith('See Fig. 2')
    assert 'architecture' in c.h.clean(text[spans[0][0]:spans[0][1]])


def test_whole_concatenation_cannot_add_previously_unrepresented_node():
    members=[dict(id='x',kind='atom',text='Tiny fragment'),dict(id='y',kind='atom',text='Another fragment')]
    nodes={'short':dict(id='short',article_id='p',members=members)}
    policies={'short':dict(eligible=True,members=[dict(member_id=m['id'],kind='atom',eligible=True) for m in members])}
    assert all(c.text_views(nodes,policies,arm)==[] for arm in c.ARMS)
