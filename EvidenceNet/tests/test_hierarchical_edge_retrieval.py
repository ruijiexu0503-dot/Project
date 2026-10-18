import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_hierarchical_edge_retrieval as h


def node(nid,article,text,kind='atom'):
    return {'id':nid,'article_id':article,'document':article.split(':')[0],
        'members':[{'id':'m','kind':kind,'text':text}]}


def policies(nodes):
    return {n['id']:{'eligible':True,'members':[{'member_id':'m','kind':n['members'][0]['kind'],'eligible':True}]}
        for n in nodes}


def test_table_views_keep_complete_row_with_header_and_original_anchor():
    text='<table><tr><td>Dataset</td><td>Size</td><td>Area</td></tr><tr><td>EuroSAT</td><td>64</td><td>11059 km2</td></tr></table>'
    n=node('a','paper:a',text);views=h.make_views({'a':n},policies([n]))
    row=next(v for v in views if v['kind']=='table_row' and 'EuroSAT' in v['retrieval_text'])
    assert 'Columns: Dataset | Size | Area' in row['retrieval_text']
    assert row['quote']=='<tr><td>EuroSAT</td><td>64</td><td>11059 km2</td></tr>'
    assert 'eurosat' in row['identifiers']


def test_article_route_is_candidate_only_and_global_escape_survives():
    ns={n['id']:n for n in [node('a','p:a','Graph WaveNet'),node('b','p:b','Graph WaveNet'),
                             node('c','p:c','unrelated'),node('d','p:d','unrelated')]}
    pairs={('a','b'):{'source':'a','target':'b','retrieval_score':.9,'signals':{},'best_views':{},'routes':['dense']},
           ('c','d'):{'source':'c','target':'d','retrieval_score':.8,'signals':{},'best_views':{},'routes':['dense']}}
    articles,candidates=h.route_and_select(ns,pairs,article_neighbors=1,pairs_per_article=1,global_escape=2,intra_per_article=0)
    assert all(a['status']=='ROUTING_CANDIDATE_NOT_SEMANTIC_EDGE' for a in articles)
    assert {frozenset((p['source'],p['target'])) for p in candidates}=={frozenset(('a','b')),frozenset(('c','d'))}
    assert all('global_escape' in p['selection_routes'] for p in candidates)


def test_identifier_index_does_not_treat_generic_terms_as_identity():
    assert 'graph wavenet' in h.identifiers('Graph WaveNet is fixed after training.')
    assert 'dataset' not in h.identifiers('The dataset uses a Transformer model.')


def test_source_window_joins_dolphin_wrap_but_keeps_raw_quote():
    raw = 'The model captures long-range\ntemporal dependencies efficiently.'
    n = node('a', 'paper:a', raw)
    n['members'][0]['semantic_text'] = 'The model captures long-range temporal dependencies efficiently.'
    view = next(v for v in h.make_views({'a': n}, policies([n])) if v['kind'] == 'source_window')
    assert view['quote'] == raw
    assert view['retrieval_text'] == n['members'][0]['semantic_text']
