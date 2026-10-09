import copy
import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import source_grounding as g
import run_relation_first_corpus_shadow as runner


class GroundingTests(unittest.TestCase):
    def test_v2_keeps_caption_prefixes_and_abbreviations_with_description(self):
        for text in ['Fig. 6. Decomposition of a choice.', 'FIG. 1. Posterior probability.',
                     '7. Linden Hall, Pennsylvania.', 'Residence of Mrs. Sarah B. Cochran.']:
            spans = g.evidence_spans('T', text, protocol='span-id-v2')
            self.assertEqual(len(spans), 1, spans)
            self.assertEqual(spans[0]['anchor'],text)
            self.assertEqual(g.resolve_span({'text':text,'evidence_spans':spans},spans[0]['span_id'])['anchor'],text)

    def test_v2_rejects_credits_and_markers_but_keeps_short_content(self):
        for text in ['Fig.', 'FIG. 1.', '7.', 'PHOTO: ULLIUS HIRTZBERGER']:
            c={'text':text,'anchor_protocol':'span-id-v2','evidence_spans':g.evidence_spans('T',text)}
            e={'text_unit_id':'T','relation':'ILLUSTRATES','anchor_span_id':c['evidence_spans'][0]['span_id'],
               'supporting_span_ids':[],'basis':'Visible association','text_quality':'UNVERIFIED'}
            result,rejected=runner.validate_edges_individually({'visual_label':'V','edges':[e]},'V',{'T':c},True)
            self.assertFalse(result['edges']); self.assertTrue(rejected)
        for text in ['cat', 'Object detection', 'Fig. 1. A wave.', 'Photo: a wave moves. It crosses the coast.']:
            g.validate_primary_semantics(text)

    def candidate(self):
        text = 'Repeated sentence. Repeated sentence. Visible second panel has a wave.'
        return {'text': text, 'caption_policy': 'body_only', 'evidence_spans': g.evidence_spans('T', text)}

    def edge(self, candidate):
        return {'text_unit_id': 'T', 'relation': 'ILLUSTRATES',
                'anchor_span_id': candidate['evidence_spans'][1]['span_id'],
                'supporting_span_ids': [], 'basis': 'The image shows the wave.', 'text_quality': 'UNVERIFIED'}

    def test_exact_offsets_cover_unicode_and_long_unbroken_text(self):
        text = ' 重复 αβ sentence.\n\n' + '长' * 1400 + '\nFinal sentence. '
        spans = g.evidence_spans('U', text)
        covered = set()
        for s in spans:
            self.assertEqual(text[s['source_char_start']:s['source_char_end']], s['anchor'])
            self.assertLessEqual(len(s['anchor']), 600)
            covered.update(range(s['source_char_start'], s['source_char_end']))
        self.assertTrue(all(i in covered for i,c in enumerate(text) if not c.isspace()))

    def test_repeated_text_resolves_selected_occurrence(self):
        c = self.candidate(); edge = self.edge(c)
        result, rejected = runner.validate_edges_individually({'visual_label':'V','edges':[edge]},'V',{'T':c},True)
        self.assertFalse(rejected)
        resolved = result['edges'][0]
        self.assertEqual(resolved['anchor'],'Repeated sentence.')
        self.assertEqual(resolved['source_char_start'],19)
        self.assertEqual(resolved['anchor_span_id'],edge['anchor_span_id'])

    def test_invalid_support_is_logged_and_primary_kept(self):
        c = self.candidate(); edge = self.edge(c)
        edge['supporting_span_ids'] = ['OTHER::span::fake', c['evidence_spans'][2]['span_id']]
        result, rejected = runner.validate_edges_individually({'visual_label':'V','edges':[edge]},'V',{'T':c},True)
        self.assertEqual(len(result['edges'][0]['supporting_spans']),2)
        self.assertEqual(rejected[0]['span_id'],'OTHER::span::fake')
        self.assertTrue(rejected[0]['edge_retained'])

    def test_unknown_primary_generated_quote_and_body_caption_rejected(self):
        c = self.candidate()
        for update in ({'anchor_span_id':'FAKE'}, {'anchor':'Invented generated quote.'}, {'relation':'CAPTION_FOR'}):
            edge = {**self.edge(c), **update}
            with self.subTest(update=update):
                result, rejected = runner.validate_edges_individually({'visual_label':'V','edges':[edge]},'V',{'T':c},True)
                self.assertFalse(result['edges']); self.assertTrue(rejected)

    def test_prompt_keeps_layout_rules_without_old_quote_schema(self):
        c = self.candidate()
        prompt = g.span_prompt('Require direct visible support. Return at most one edge per text_unit_id. OLD QUOTE SCHEMA','V',{'T':c})
        self.assertIn('Require direct visible support.',prompt)
        self.assertNotIn('OLD QUOTE SCHEMA',prompt)
        self.assertIn('anchor_span_id',prompt)

    def test_reviewed_role_is_bound_to_full_page_crop_and_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source=root/'page'; crop=root/'crop'
            source.write_bytes(b'fullpage'); crop.write_bytes(b'crop')
            visual={'visual_bundle_id':'V','presentation':str(crop),'geometry_members':[{'bbox':[1,2,3,4]}]}
            rep={'document_id':'D','page':'P','visual_bundles':[visual]}
            self.assertEqual(g.visual_roles(rep,source,{})['V']['role'],'UNKNOWN')
            record={'document_id':'D','page':'P','visual_id':'V','role':'LOGO','review_status':'source_reviewed',
                    'reviewer':'assistant_visual_review','basis':'Reviewed page and crop.',
                    'source_image_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'crop_sha256':hashlib.sha256(crop.read_bytes()).hexdigest(),'geometry_members':visual['geometry_members']}
            config=root/'roles.json';config.write_text(json.dumps({'visual_roles':[record]}))
            mapping=g.load_role_map(config)
            self.assertTrue(g.visual_roles(rep,source,mapping)['V']['exclude_from_semantic_candidates'])
            for what in ('page','crop','geometry'):
                changed=copy.deepcopy(rep)
                source.write_bytes(b'fullpage' if what!='page' else b'changed')
                crop.write_bytes(b'crop' if what!='crop' else b'changed')
                if what=='geometry': changed['visual_bundles'][0]['geometry_members']=[]
                with self.subTest(what=what),self.assertRaises(ValueError):g.visual_roles(changed,source,mapping)

    def test_full_runner_materializes_span_provenance_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'page.png';Image.new('RGB',(100,100),'white').save(image)
            work=root/'work'
            runner.write(work/'output_json/page.json',[
                {'label':'text','text':'The measured signal rises and then falls. The second panel shows the residual.', 'bbox':[0,0,100,40]},
                {'label':'fig','text':'','bbox':[0,45,100,100]}])
            runner.write(work/'run_summary.json',{'image_size':[100,100]})
            manifest=root/'manifest.json'
            runner.write(manifest,{'sources':[{'document_id':'D','page':'page_0001','mode':'case',
                                               'work':str(work),'image':str(image)}]})
            class Model:
                calls=0
                def generate_raw_with_images(self,system,prompt,images,budget):
                    self.calls+=1
                    candidates=json.loads(prompt.split(' Candidates: ')[-1]);uid=next(iter(candidates))
                    span=candidates[uid]['evidence_spans'][0]
                    return SimpleNamespace(raw=json.dumps({'visual_label':'VISUAL_01','edges':[{
                        'text_unit_id':uid,'relation':'ILLUSTRATES','anchor_span_id':span['span_id'],
                        'supporting_span_ids':[],'basis':'Synthetic integration fixture.','text_quality':'UNVERIFIED'}]}))
            model=Model()
            args=argparse.Namespace(sources=manifest,output=root/'out',fresh_root=root,staged_sources=root,
                pptx_audit=root,model='fake',local_check=False,resume=False,shard_index=0,shard_count=1,
                recovery_policy='none',anchor_protocol='span-id-v1')
            with patch.object(runner.base,'create_llm',return_value=model),patch.object(runner,'make_flow',side_effect=lambda rep,*a:runner.local_flow(rep)):
                runner.run(args)
                args.resume=True;runner.run(args)
            self.assertEqual(model.calls,1)
            page=root/'out/D/page_0001'
            edge=runner.base.read(page/'relations.json')[0]
            self.assertTrue(edge['anchor_span_id'])
            self.assertTrue(edge['source_spans'])
            self.assertEqual(edge['anchor'],'The measured signal rises and then falls.')
            self.assertEqual(runner.base.read(page/'summary.json')['anchor_protocol'],'span-id-v1')


if __name__ == '__main__':
    unittest.main()
