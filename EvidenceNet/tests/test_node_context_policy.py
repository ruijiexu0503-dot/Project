import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from node_context_policy import eligibility, usable_window, markers, structured_pairs, select_candidates
from run_node_context_edges import make_views
from verify_node_context import validate
from test_node_context_edges import node, OffsetTokenizer


def test_bad_windows_removed_but_raw_offsets_and_math_retained():
    n=node('a','A scientific equation describes uncertainty. '+('~ '*500))
    views,excluded=make_views([n],OffsetTokenizer(),eligibility([n]))
    assert views and excluded
    assert all(v['text']==n['members'][0]['text'][v['char_start']:v['char_end']] for v in views)
    assert all('~~~~~' not in v['retrieval_text'] and v['retrieval_text'].count('~')<5 for v in views)
    assert usable_window(r'\frac{x}{y}=z',{'role':'equ'})
    assert not usable_window('~ '*200,{'role':'equ'})


def test_furniture_filter_is_member_level():
    n=node('a','Europe PMC Funders Author Manuscripts')
    n['members'][0]['role']='watermark'
    n['members'].append({'id':'math','kind':'atom','role':'equ','text':'x=y'})
    p=eligibility([n]);assert p['a']['eligible']
    views,_=make_views([n],OffsetTokenizer(),p)
    assert [v['member_id'] for v in views]==['math']


def test_unique_references_protected_and_external_decimal_not_resolved():
    a=node('a','See Fig. 1 for the observed waveform.')
    b=node('b','FIG. 1. Observed waveform and uncertainty.')
    for n in [a,b]:n.update(document='paper',article_id='article')
    ns={n['id']:n for n in [a,b]};pairs,issues=structured_pairs(ns,eligibility(list(ns.values())),[])
    assert len(pairs)==1 and pairs[0]['references'][0]['source']=='a'
    assert list(markers('their Fig. 1 and Eq. 4.7'))==[]
    c=node('c','FIG. 1. Another possible waveform caption.');c.update(document='paper',article_id='article')
    ns['c']=c;pairs,issues=structured_pairs(ns,eligibility(list(ns.values())),[])
    assert not any(p['references'] for p in pairs) and issues


def test_caption_declaration_never_becomes_reference_to_other_caption():
    a=node('a','Fig. 1 Measurements of the lifetime and energy.')
    b=node('b','Fig. 1. Gamma mass distribution for different events.')
    for n in [a,b]:n.update(document='magazine',article_id='article')
    ns={n['id']:n for n in [a,b]}
    pairs,issues=structured_pairs(ns,eligibility([a,b]),[])
    assert not pairs and not issues


def test_same_article_budget_counts_distinct_nodes_not_windows():
    import numpy as np
    ns=[node(str(i),'Some scientific source words here.') for i in range(5)]
    for n in ns:n.update(document='paper',article_id='article')
    views=[{'node_id':'0','kind':'source_text'}]+[{'node_id':str(i),'kind':'source_text'} for i in range(1,5) for _ in range(6)]
    matrix=np.zeros((len(views),len(views)));matrix[0]=np.arange(len(views),0,-1)
    pairs=select_candidates({n['id']:n for n in ns},views,{'dense':matrix},[])
    assert {p['target'] for p in pairs if p['source']=='0'}=={'1','2','3','4'}


def test_verification_cannot_quote_generated_descriptions_or_watermarks():
    a=node('a','A graph shows glacier retreat over time.',True)
    b=node('b','The measured glacier retreats over time.')
    ns={n['id']:n for n in [a,b]};p={'pair_id':'p','source':'a','target':'b'}
    v={'pair_id':'p','status':'ACCEPT','reason':'Shared glacier observation',
       'anchor_a':{'kind':'TEXT','member_id':'member','quote':a['members'][0]['text']},
       'anchor_b':{'kind':'TEXT','member_id':'member','quote':b['members'][0]['text']}}
    assert validate(v,p,ns,eligibility(list(ns.values())))
    v['anchor_a']={'kind':'VISUAL','member_id':'member','observation':'Graph of declining glacier extent'}
    assert validate(v,p,ns,eligibility(list(ns.values())))==[]
