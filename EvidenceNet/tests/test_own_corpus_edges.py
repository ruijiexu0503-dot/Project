import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_own_corpus_edges import validate_ownership, validate_relation, scope


class OwnCorpusEdgesTests(unittest.TestCase):
    def test_ownership_requires_exact_coverage_and_separate_flows(self):
        page={'nodes':[{'label':'N001'},{'label':'N002'}]}
        valid={'groups':[{'title':'Article','nodes':['N001','N002'],'flows':[['N001'],['N002']]}]}
        self.assertEqual(validate_ownership(valid,page),[])
        valid['groups'][0]['flows'].append(['N001'])
        self.assertIn('node_in_multiple_flows',validate_ownership(valid,page))
        valid['groups'][0]['nodes']=['N001']
        valid['groups'][0]['flows']=[]
        self.assertIn('node_coverage',validate_ownership(valid,page))

    def test_source_anchors_cannot_use_visual_description_or_another_node(self):
        nodes={'a':{'members':[{'kind':'atom','text':'The measurement was 42 units.'}]},
               'b':{'members':[{'kind':'atom','text':'The theory explains the measurement.'},
                                {'kind':'visual','text':'Hallucinated description of a third figure.','crop':'crop.jpg'}]}}
        pair={'pair_id':'p','source':'a','target':'b'}
        r={'type':'SUPPORTS','direction':'A_TO_B',
           'anchor_a':{'kind':'TEXT','quote':'measurement was 42 units'},
           'anchor_b':{'kind':'TEXT','quote':'theory explains the measurement'},'reason':'Matched measurement'}
        value={'pair_id':'p','status':'ACCEPT','relations':[r]}
        self.assertEqual(validate_relation(value,pair,nodes),[])
        r['anchor_b']['quote']='description of a third figure'
        self.assertIn('anchor_not_in_source_atom',validate_relation(value,pair,nodes))
        r['anchor_b']={'kind':'VISUAL','observation':'Visible graph labelled measurement'}
        self.assertEqual(validate_relation(value,pair,nodes),[])

    def test_uncertainty_does_not_materialize_edges(self):
        pair={'pair_id':'p'}
        self.assertEqual(validate_relation({'pair_id':'p','status':'UNCERTAIN','relations':[]},pair,{}),[])
        self.assertIn('unaccepted_relations',validate_relation(
            {'pair_id':'p','status':'UNCERTAIN','relations':[{}]},pair,{}))

    def test_unknown_page_ownership_is_not_cross_article(self):
        a={'document':'doc','page':'p1','article_id':'local1'}
        b={'document':'doc','page':'p2','article_id':'local2'}
        self.assertEqual(scope(a,b),'same_document_article_unresolved')
        b['document']='other'
        self.assertEqual(scope(a,b),'cross_document')


if __name__=='__main__':unittest.main()
