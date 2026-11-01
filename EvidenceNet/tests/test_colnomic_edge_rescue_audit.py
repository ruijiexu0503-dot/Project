from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_colnomic_edge_rescue import graph_paths


def edge(eid, a, b):
    return {'edge_id':eid,'endpoints':{s:{'document_id':p[0],'page_number':p[1]}
            for s,p in zip(('A','B'),(a,b))}}


def test_reachability_is_bidirectional_but_only_one_hop():
    a,b,c=('a','1'),('b','2'),('c','3')
    graph=[edge('ab',a,b),edge('bc',b,c),edge('aa',a,a)]
    paths=graph_paths(graph,[a])
    assert set(paths)=={b}
    assert paths[b][0]=={'edge_id':'ab','seed_page':a,'seed_rank':1}
    assert graph_paths(graph,[b])[a][0]['edge_id']=='ab'


def test_numeric_page_ids_normalized_without_gold():
    graph=[edge('e',('a',1),('b',2))]
    assert ('b','2') in graph_paths(graph,[('a','1')])
    assert not graph_paths(graph,[('z','9')])
