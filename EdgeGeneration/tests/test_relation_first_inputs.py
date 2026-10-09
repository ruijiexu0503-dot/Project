import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('adapter',Path(__file__).resolve().parents[1]/'scripts/prepare_relation_first_inputs.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AdapterTests(unittest.TestCase):
    def unit(self, uid, doc='D', local='D::p1::CI_1', article=None):
        return {'unit_id':uid,'doc_id':doc,'local_content_item_id':local,'article_id':article,
                'shadow_candidate_eligible':True,'text':'gravitational wave measurement detector','source_visual_ids':[]}

    def test_local_ids_do_not_imply_cross_page_article(self):
        a=self.unit('a'); b=self.unit('b',local='D::p2::CI_1')
        self.assertEqual(m.scope(a,b),'same_document_article_unresolved')
        self.assertEqual(m.scope(a,self.unit('c')),'intra_local_item')

    def test_explicit_article_and_cross_document(self):
        self.assertEqual(m.scope(self.unit('a',article='D::A'),self.unit('b',article='D::A')),'intra_article')
        self.assertEqual(m.scope(self.unit('a',article='D::A'),self.unit('b',article='D::B')),'cross_article')
        self.assertEqual(m.scope(self.unit('a'),self.unit('b',doc='E')),'cross_document')

    def test_existing_relations_not_new_semantic_edges(self):
        us=[self.unit('a'),self.unit('b',doc='E')]
        self.assertEqual(len(m.candidates(us,[],1)),1)
        self.assertEqual(m.candidates(us,[{'source_unit_id':'a','target_unit_id':'b'}],1),[])
        us[1]['shadow_candidate_eligible']=False
        self.assertEqual(m.candidates(us,[],1),[])

    def test_strict_semantic_scope_only_keeps_same_article_pairs(self):
        us=[self.unit('a',article='D::A'),self.unit('b',local='D::p2::CI_1',article='D::A'),
            self.unit('c',local='D::p2::CI_2',article='D::B')]
        us[2]['text']='unrelated botanical illustration pigment'
        pairs=m.candidates(us,[],5,'intra_article_only')
        self.assertEqual({(p['source_unit_id'],p['target_unit_id']) for p in pairs},{('a','b')})
        self.assertTrue(all(p['scope']=='intra_article' for p in pairs))

    def test_page_furniture_and_structural_logos_are_not_evidence(self):
        for role in ('page_furniture','logo'):
            included,reason=m.evidence_inclusion({'node_type':'structural_component','role':role})
            self.assertFalse(included)
            self.assertEqual(reason,f'non_content_structural_role:{role}')
        self.assertEqual(m.evidence_inclusion({'node_type':'structural_component','role':'section_heading'}),(True,None))
        self.assertEqual(m.evidence_inclusion({'node_type':'text_component','role':'page_furniture'}),(True,None))

    def test_grounded_caption_can_recover_misclassified_page_furniture(self):
        unit={'unit_id':'caption','unit_kind':'structural_component','structural_role':'page_furniture',
              'text':'Bottom image: the control room shows the interactive display.',
              'review_candidate':True,'evidence_included':False,'article_id':'D::A',
              'article_binding':'explicit_map','shadow_candidate_eligible':False}
        relation={'source_unit_id':'caption','target_unit_id':'image',
                  'source_relation':{'relation_type':'CAPTION_FOR','anchor':'Bottom image: the control room.'}}
        self.assertEqual(m.recover_grounded_captions([unit],[relation]),['caption'])
        self.assertTrue(unit['evidence_included'])
        self.assertEqual(unit['structural_role'],'caption')
        self.assertIsNone(unit['article_id'])

    def test_page_number_is_not_recovered_without_caption_evidence(self):
        unit={'unit_id':'page','unit_kind':'structural_component','structural_role':'page_furniture',
              'text':'Page 18','review_candidate':True,'evidence_included':False}
        self.assertEqual(m.recover_grounded_captions([unit],[]),[])
        self.assertFalse(unit['evidence_included'])

    def test_reviewed_logo_stays_addressable_but_proxy_cannot_enable_retrieval(self):
        role={'role':'LOGO','review_status':'source_reviewed','exclude_from_semantic_candidates':True}
        text='A scientific sentence describing an unrelated observation.'
        files={'summary.json':{'document_id':'D','page':'p1','status':'partial'},
            'input_representation.json':{'atoms':[{'text_fragments':[{'fragment_id':'F','text':text}]}],
                                         'visual_bundles':[{'visual_bundle_id':'V'}]},
            'flow.json':{'content_items':[{'content_item_id':'C','flows':[{'fragment_ids':['F']}],
                                           'structural_fragments':[],'visual_panel_ids':['V']}]},
            'review_units.json':[{'text_unit_id':'T','fragment_ids':['F'],'text':text}],
            'text_units.json':[{'text_unit_id':'T'}], 'visual_presentations.json':[],
            'components.json':[{'node_id':'T','node_type':'text_component','fragment_ids':['F'],'visual_ids':[]},
                               {'node_id':'V','node_type':'visual_component','fragment_ids':[],'visual_ids':['V'],'visual_role':role}],
            'relations.json':[{'source_node_id':'T','target_node_id':'V','anchor':text,'text_quality':'UNVERIFIED'}]}
        units,relations,_=m.convert(files,Path('/fixture'),'v',{})
        visual=next(u for u in units if u['unit_id']=='V')
        self.assertEqual(visual['visual_role'],role)
        self.assertTrue(visual['linked_text_proxies'])
        self.assertFalse(visual['shadow_candidate_eligible'])
        self.assertEqual(len(units),2)
        self.assertEqual(len(relations),1)


if __name__=='__main__': unittest.main()
