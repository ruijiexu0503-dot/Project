import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_relation_first_corpus_shadow as r
import run_frozen_prompt_comparison as comparison


class GroundedPromptTests(unittest.TestCase):
    def test_prompt_switch_invalidates_resume_and_preserves_source_addresses(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'page.png';Image.new('RGB',(100,100),'white').save(image)
            r.write(root/'work/output_json/page.json',[
                {'label':'text','text':'The measured signal rises and then falls.','bbox':[0,0,100,35]},
                {'label':'fig','text':'','bbox':[0,45,100,100]}])
            r.write(root/'work/run_summary.json',{'image_size':[100,100]})
            r.write(root/'manifest.json',{'sources':[{'document_id':'D','page':'page_0001',
                'mode':'case','work':str(root/'work'),'image':str(image)}]})
            prompts=[]
            def generate(system,prompt,images,budget):
                prompts.append(prompt);candidates=json.loads(prompt.rsplit('Candidates: ',1)[1]);uid=next(iter(candidates))
                return SimpleNamespace(raw=json.dumps({'visual_label':'VISUAL_01','edges':[{
                    'text_unit_id':uid,'relation':'ILLUSTRATES',
                    'anchor_span_id':candidates[uid]['evidence_spans'][0]['span_id'],
                    'basis':'The curve depicts the rise and fall.','text_quality':'UNVERIFIED'}]}))
            args=argparse.Namespace(sources=root/'manifest.json',output=root/'out',fresh_root=root,
                staged_sources=root,pptx_audit=root,model='fake',local_check=False,resume=True,
                shard_index=0,shard_count=1,recovery_policy='none',anchor_protocol='span-id-v2',edge_prompt_policy='legacy')
            with patch.object(r.base,'create_llm',return_value=SimpleNamespace(generate_raw_with_images=generate)),patch.object(r,'make_flow',side_effect=lambda rep,*a:r.local_flow(rep)):
                r.run(args);args.edge_prompt_policy='grounded-v3';r.run(args);r.run(args)
            self.assertEqual(len(prompts),2)
            self.assertIn('DECISION ORDER',prompts[1]);self.assertNotIn('DECISION ORDER',prompts[0])
            page=root/'out/D/page_0001';edge=r.base.read(page/'relations.json')[0]
            self.assertEqual(edge['anchor'],'The measured signal rises and then falls.')
            self.assertTrue(edge['source_spans'])
            self.assertEqual(r.base.read(page/'V_001_edge_prompt.json')['edge_prompt_policy'],'grounded-v3')

    def test_frozen_comparison_does_not_change_candidates_and_rejects_image_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);page=root/'baseline/shard_0/D/page_0001'
            image=root/'source.png';Image.new('RGB',(10,10),'white').save(image)
            r.write(page/'input_representation.json',{'source_image':str(image),
                'visual_bundles':[{'visual_bundle_id':'V','presentation':str(image)}]})
            candidate={'unit_id':'T','text':'Fig. 1. A measured signal.','caption_policy':'allowed'}
            r.write(page/'candidate_ledger.json',{'V':{'selected':[candidate]}})
            before=(page/'candidate_ledger.json').read_bytes()
            r.write(page/'flow.json',{'content_items':[]})
            r.write(page/'V_edge_prompt.json',{'prompt':'Review image. Return at most one edge per text_unit_id.'})
            manifest=root/'frozen.json'
            with patch.object(comparison,'CASES',[('D','page_0001','V','positive_control')]):
                comparison.prepare(root/'baseline',manifest)
                with self.assertRaises(ValueError):comparison.prepare(root/'baseline',manifest)
            self.assertEqual(before,(page/'candidate_ledger.json').read_bytes())
            case=r.base.read(manifest)['cases'][0]
            self.assertEqual(case['candidates']['T']['evidence_spans'][0]['anchor'],candidate['text'])
            self.assertEqual(set(case['prompts']),{'legacy-v2','grounded-v3'})
            image.write_bytes(b'changed')
            with patch.object(r.base,'create_llm') as factory, self.assertRaisesRegex(ValueError,'image drift'):
                comparison.run(SimpleNamespace(manifest=manifest))
            factory.assert_not_called()


if __name__=='__main__':unittest.main()
