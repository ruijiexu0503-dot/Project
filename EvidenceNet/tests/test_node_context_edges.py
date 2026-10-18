import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_node_context_edges import choose_edges, make_views, tokens, scope


class OffsetTokenizer:
    def __call__(self,text,**kwargs):
        return {'offset_mapping':[(m.start(),m.end()) for m in re.finditer(r'\S+',text)]}


def node(nid,text,visual=False):
    return {'id':nid,'document':nid,'page':'1','article_id':None,'visual_count':int(visual),
            'members':[{'id':'member','kind':'visual' if visual else 'atom','text':text,
                        **({'crop':'original.jpg'} if visual else {})}]}


class ContextEdgesTests(unittest.TestCase):
    def test_short_generic_heading_is_not_a_retrieval_view(self):
        views,excluded=make_views([node('a','Equilibrium:')],OffsetTokenizer())
        self.assertEqual(views,[])
        self.assertEqual(excluded[0]['reason'],'empty_or_short_member')

    def test_long_windows_preserve_offsets_without_creating_new_nodes(self):
        n=node('a',' '.join(f'word{i}' for i in range(450)))
        views,_=make_views([n],OffsetTokenizer())
        self.assertGreater(len(views),1)
        self.assertEqual({v['node_id'] for v in views},{'a'})
        for v in views:
            self.assertEqual(n['members'][0]['text'][v['char_start']:v['char_end']],v['text'])

    def test_semantic_softwrap_view_keeps_raw_anchor_offsets(self):
        raw = 'The model captures long-range\ntemporal dependencies efficiently.'
        n = node('a', raw)
        n['members'][0]['semantic_text'] = 'The model captures long-range temporal dependencies efficiently.'
        views, _ = make_views([n], OffsetTokenizer())
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0]['text'], raw)
        self.assertEqual(views[0]['retrieval_text'], n['members'][0]['semantic_text'])
        self.assertEqual(raw[views[0]['char_start']:views[0]['char_end']], views[0]['text'])

    def test_description_match_never_becomes_verified_visual_evidence(self):
        ns=[node('a','The observation records glacier retreat.'),
            node('b','A graph shows glacier retreat over time.',True)]
        vs,_=make_views(ns,OffsetTokenizer())
        scored=[{'source':'a','target':'b','scope':'cross_document','pair_id':'p','routes':['dense'],
                 'alignments':[{'a':0,'b':1,'score':0.95}]}]
        edge=choose_edges(scored,{n['id']:n for n in ns},vs)[0]
        self.assertEqual(edge['source'],'a')
        self.assertEqual(edge['target'],'b')
        self.assertEqual(edge['representation_basis'],'description_assisted')
        self.assertEqual(edge['visual_verification'],'PENDING')
        self.assertEqual(edge['anchor_b']['kind'],'GENERATED_DESCRIPTION')
        self.assertFalse(edge['anchor_b']['source_verified'])
        self.assertEqual(edge['type'],'RELATED_CONTEXT')
        self.assertEqual(edge['direction'],'SYMMETRIC')
        scored[0]['alignments'][0]['score']=0.2
        self.assertEqual(choose_edges(scored,{n['id']:n for n in ns},vs),[])

    def test_stale_anchor_is_rejected(self):
        ns=[node('a','Some actual source text here.'),node('b','Another actual source text here.')]
        vs,_=make_views(ns,OffsetTokenizer());vs[0]['text']='Invented quote'
        pair={'source':'a','target':'b','scope':'cross_document','pair_id':'p','routes':[],
              'alignments':[{'a':0,'b':1,'score':0.99}]}
        with self.assertRaisesRegex(ValueError,'Anchor offset'):
            choose_edges([pair],{n['id']:n for n in ns},vs)

    def test_html_structure_is_not_a_lexical_signal_and_unknown_article_stays_unknown(self):
        self.assertEqual(tokens('<table><td>glacier</td><td>retreat</td></table>'),['glacier','retreat'])
        a=node('a','Some actual source text here.');b=node('b','Some different source text here.')
        a.update(document='doc',page='1',article_id='local1')
        b.update(document='doc',page='2',article_id='local2')
        self.assertEqual(scope(a,b),'same_document_article_unresolved')


if __name__=='__main__':unittest.main()
