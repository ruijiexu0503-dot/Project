import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_relation_first_corpus_shadow as runner


class RelationFirstTest(unittest.TestCase):
    def test_individual_rejections_preserve_valid_edges(self):
        text = 'The visible instrument measures the green light.'
        good = {'text_unit_id': 'T1', 'relation': 'ILLUSTRATES', 'anchor': text,
                'basis': 'Visible green light and instrument', 'text_quality': 'UNVERIFIED'}
        bad = dict(good, anchor='This is not the source quotation.')
        result, rejected = runner.validate_edges_individually(
            {'visual_label': 'V1', 'edges': [bad, good, None]}, 'V1', {'T1': {'text': text}})
        self.assertEqual(len(result['edges']), 1)
        self.assertEqual([r['edge_index'] for r in rejected], [0, 2])
        self.assertEqual(bad['anchor'], 'This is not the source quotation.')

    def test_caption_attachment_required_and_conflicts_rejected(self):
        text = 'Figure showing the measured signal.'
        edge = {'text_unit_id': 'T1', 'relation': 'CAPTION_FOR', 'anchor': text,
                'basis': 'Visible signal', 'text_quality': 'UNVERIFIED'}
        candidates = {uid: {'text': text, 'caption_layout_required': True} for uid in ('T1', 'T2')}
        result, rejected = runner.validate_edges_individually({'visual_label': 'V', 'edges': [edge]}, 'V', candidates)
        self.assertFalse(result['edges'])
        self.assertEqual(len(rejected), 1)
        edge.update(caption_attachment='standalone_target', caption_layout_basis='Standalone caption directly below the target plot.')
        result, rejected = runner.validate_edges_individually({'visual_label': 'V', 'edges': [edge]}, 'V', candidates)
        self.assertEqual(len(result['edges']), 1)
        self.assertFalse(rejected)
        result, rejected = runner.validate_edges_individually(
            {'visual_label': 'V', 'edges': [edge, dict(edge, text_unit_id='T2')]}, 'V', candidates)
        self.assertFalse(result['edges'])
        self.assertEqual(len(rejected), 2)

    def test_cross_item_candidates_are_bounded_and_keep_ownership(self):
        units = [{'text_unit_id': uid, 'content_item_id': owner, 'caption_candidate': False}
                 for uid, owner in [('near', 'other'), ('far', 'other'), ('own', 'article')]]
        ranked = [{'unit_id': uid, 'text': 'A source paragraph', 'caption_candidate': False,
                   'geometry': {'gap': gap, 'score': gap}}
                  for uid, gap in [('near', .01), ('own', .03), ('far', .8)]]
        with patch.object(runner, 'candidates_for', return_value=([], ranked)):
            selected, _ = runner.relation_candidates({}, units, 'article', {}, {}, (100, 100))
        self.assertEqual({r['unit_id'] for r in selected}, {'near', 'own'})
        self.assertEqual(selected[0]['candidate_scope'], 'cross_item')
        self.assertEqual(units[0]['content_item_id'], 'other')

    def test_caption_role_guard_and_structural_layout_review(self):
        text = 'A ship carries the receiver under test.'
        edge = {'text_unit_id': 'T1', 'relation': 'CAPTION_FOR', 'anchor': text,
                'basis': 'Visible receiver on the ship', 'text_quality': 'SUSPECT'}
        def check(policy):
            runner.validate_edges({'visual_label': 'V1', 'edges': [dict(edge)]}, 'V1',
                                  {'T1': {'text': text, 'caption_policy': policy}})
        with self.assertRaisesRegex(ValueError, 'body text'):
            check('body_only')
        with self.assertRaisesRegex(ValueError, 'caption_layout_basis'):
            check('layout_review_required')
        edge['caption_layout_basis'] = 'Small standalone text over the lower edge of the photograph.'
        check('layout_review_required')
        check('allowed')
        edge['relation'] = 'ILLUSTRATES'
        check('body_only')

    def test_cpu_configuration_is_explicit_and_cuda_default_preserved(self):
        args = argparse.Namespace(model='test', device='cpu', dtype=None)
        config = runner.inference_config(args)
        self.assertEqual(config['device_map'], 'cpu')
        self.assertFalse(config['require_cuda'])
        self.assertEqual(config['dtype'], 'float32')
        args.device = 'cuda'
        self.assertTrue(runner.inference_config(args)['require_cuda'])
        self.assertEqual(runner.inference_config(args)['dtype'], 'bfloat16')

    def test_full_run_and_failed_reviews(self):
        for bad_edges, structural_caption in ((False, False), (True, False), (False, True)):
            with self.subTest(bad_edges=bad_edges, structural_caption=structural_caption), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                image = root / 'page.png'; Image.new('RGB', (200, 200), 'white').save(image)
                work = root / 'work'; (work / 'output_json').mkdir(parents=True)
                text = 'This figure shows the measured signal and its uncertainty.'
                runner.write(work / 'output_json/page.json', [
                    {'label': 'sec', 'text': 'A title', 'bbox': [0, 0, 190, 20]},
                    {'label': 'cap', 'text': text, 'bbox': [0, 130, 190, 170]},
                    {'label': 'fig', 'text': '', 'bbox': [0, 25, 90, 120]},
                    {'label': 'fig', 'text': '', 'bbox': [100, 25, 195, 120]},
                ])
                runner.write(work / 'run_summary.json', {'image_size': [200, 200]})
                manifest = root / 'manifest.json'
                runner.write(manifest, {'sources': [{'document_id': 'test', 'page': page, 'mode': 'case',
                                                    'work': str(work), 'image': str(image)} for page in ('page_0001', 'page_0002')]})
                args = argparse.Namespace(sources=manifest, output=root / 'out', fresh_root=root,
                    staged_sources=root, pptx_audit=root, model='fake', local_check=False, resume=False,
                    shard_index=0, shard_count=1)

                caption_id = {}
                class Model:
                    def generate_raw_with_images(self, system, prompt, images, tokens):
                        if 'reading-flow' in system:
                            rep = runner.base.read(root / 'out/test/page_0001/input_representation.json')
                            flow = runner.local_flow(rep)
                            if structural_caption:
                                item = flow['content_items'][0]
                                fid = item['flows'][0]['fragment_ids'][0]
                                item['structural_fragments'].append({'fragment_id': fid, 'role': 'page_furniture'})
                                item['flows'] = []
                                caption_id['id'] = 'S_' + fid
                            return SimpleNamespace(raw=json.dumps(flow))
                        if bad_edges:
                            return SimpleNamespace(raw='{}')
                        label = 'VISUAL_01' if 'VISUAL_01' in prompt else 'VISUAL_02'
                        return SimpleNamespace(raw=json.dumps({'visual_label': label, 'edges': [
                            {'text_unit_id': caption_id.get('id', 'T_001'), 'relation': 'CAPTION_FOR', 'anchor': text,
                             'caption_layout_basis': 'Standalone small text directly beneath the two figure panels.',
                             'caption_attachment': 'explicit_shared_panel',
                             'basis': 'Test fixture visible measured signal', 'text_quality': 'UNVERIFIED'}]}))

                with patch.object(runner.base, 'create_llm', return_value=Model()):
                    runner.run(args)
                target = root / 'out/test/page_0001'
                summary = runner.base.read(target / 'summary.json')
                self.assertEqual(summary['status'], 'partial' if bad_edges else 'complete')
                self.assertEqual(summary['relations'], 0 if bad_edges else 2)
                self.assertEqual(summary['model_calls'], 2)
                overall = runner.base.read(root / 'out/summary.json')
                self.assertEqual(overall['processed_pages'], 2)
                self.assertEqual(overall['validation_failed_pages'], 2 if bad_edges else 0)
                nodes = runner.base.read(target / 'components.json')
                self.assertEqual(len(nodes), 4)
                self.assertEqual(sum(n['node_type'] == 'structural_component' for n in nodes), 1 + int(structural_caption))
                if bad_edges:
                    args.resume = True
                    with patch.object(runner.base, 'create_llm', return_value=Model()), patch.object(
                            Model, 'generate_raw_with_images', side_effect=AssertionError('Failure was already recorded')):
                        self.assertTrue(runner.run(args))
                if not bad_edges:
                    views = runner.base.read(target / 'composite_views.json')
                    self.assertEqual(len(views), 1)
                    self.assertEqual(len(views[0]['component_node_ids']), 3)
                    edge = runner.base.read(target / 'relations.json')[0]
                    self.assertTrue(edge['source_node_id'].endswith(caption_id.get('id', 'T_001')))
                    if structural_caption:
                        self.assertEqual(edge['original_structural_role'], 'page_furniture')
                        self.assertTrue(edge['supporting_spans'][0]['caption_layout_basis'])
                    self.assertEqual(edge['source_spans'][0]['source_atom_char_start'], 0)
                    # Simulate a stop after decision checkpoints but before the page summary.
                    (target / 'summary.json').unlink()
                    args.resume = True
                    with patch.object(runner.base, 'create_llm', return_value=Model()), patch.object(
                            Model, 'generate_raw_with_images', side_effect=AssertionError('Cached decisions must not rerun')):
                        self.assertTrue(runner.run(args))
                    self.assertEqual(runner.base.read(target / 'summary.json')['model_calls'], 0)
                self.assertNotIn('file://', (target / 'evidence_gallery.html').read_text())

    def test_same_sentence_grouping(self):
        atoms = [{'atom_id': str(i), 'text_fragments': runner.one_fragment(str(i), t)}
                 for i, t in enumerate(('A sentence', 'continued here.'))]
        rep = {'atoms': atoms, 'visual_bundles': []}
        flow = {'content_items': [{'content_item_id': 'CI', 'structural_fragments': [], 'visual_panel_ids': [],
                 'flows': [{'flow_id': 'F', 'flow_kind': 'main', 'fragment_ids': ['0::F001', '1::F001'],
                            'continuations': [{'kind': 'same_sentence', 'from_fragment_id': '0::F001', 'to_fragment_id': '1::F001'}]}]}]}
        units = runner.text_units(flow, rep)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['text'], 'A sentence\ncontinued here.')
        duplicate = json.loads(json.dumps(flow)); duplicate['content_items'] *= 2
        self.assertFalse(runner.validate_flow(duplicate, rep)['valid'])

    def test_bad_flow_retries_without_example_ids(self):
        class Model:
            calls = 0
            def generate_raw_with_images(self, system, prompt, images, tokens):
                self.calls += 1
                assert 'P_0009_A01' not in prompt
                assert 'NO_VISUAL_AVAILABLE' not in prompt
                return SimpleNamespace(raw='{"content_items": []}')
        model = Model()
        rep = {'atoms': [{'atom_id': 'A', 'text_fragments': runner.one_fragment('A', 'Retain this title')}], 'visual_bundles': []}
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            runner.make_flow(rep, Path('test.png'), model, Path(tmp), False)
        self.assertEqual(model.calls, 1)

    def test_short_source_and_rejected_invented_anchor(self):
        candidate = {'T': {'text': 'Ice'}}
        result = {'visual_label': 'V', 'edges': [{'text_unit_id': 'T', 'relation': 'CAPTION_FOR',
                    'anchor': 'Ice', 'basis': 'Visible ice', 'text_quality': 'UNVERIFIED'}]}
        runner.validate_edges(result, 'V', candidate)
        self.assertEqual(result['edges'][0]['source_char_end'], 3)
        result['edges'][0]['anchor'] = 'Snow'
        with self.assertRaises(ValueError):
            runner.validate_edges(result, 'V', candidate)

    def test_real_failure_shapes_and_repair_context(self):
        rep = {'atoms': [{'atom_id': 'A', 'atom_type': 'heading',
                          'text_fragments': runner.one_fragment('A', 'Measured signal'),
                          'geometry_members': [{'member_id': 'A::G001', 'bbox': [0, 0, 10, 10]}]}],
               'visual_bundles': [{'visual_bundle_id': 'V_001', 'geometry_members': [
                   {'member_id': 'V_001::M001', 'bbox': [0, 10, 10, 20]}]}]}
        valid = runner.local_flow(rep)
        invalid = json.loads(json.dumps(valid))
        invalid['page_furniture'] = invalid['content_items'][0].pop('structural_fragments')
        invalid['content_items'][0]['visual_panel_ids'] = ['V_001::M001']
        prompt = runner.reading_flow_prompt(rep)
        self.assertNotIn('V_001::M001', prompt)
        self.assertNotIn('A::G001', prompt)
        self.assertFalse(runner.validate_flow(invalid, rep)['valid'])
        duplicate = json.loads(json.dumps(valid))
        duplicate['content_items'][0]['flows'] = [{'flow_id': 'F', 'flow_kind': 'main',
                                                  'fragment_ids': ['A::F001'], 'continuations': []}]
        self.assertFalse(runner.validate_flow(duplicate, rep)['valid'])
        outer = self

        class Model:
            calls = 0
            def generate_raw_with_images(self, system, prompt, images, tokens):
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(raw=json.dumps(invalid))
                outer.assertIn('PREVIOUS_RESPONSE:', prompt)
                outer.assertIn(json.dumps(invalid), prompt)
                outer.assertIn('invalid_root_schema', prompt)
                return SimpleNamespace(raw=json.dumps(valid))

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(runner.make_flow(rep, Path('page.png'), Model(), Path(tmp), False, max_attempts=2), valid)

    def test_same_caption_multiple_spans_form_one_relation(self):
        text = 'The detector measures gravitational strain. The bottom panel shows residuals.'
        result = {'visual_label': 'V', 'edges': [
            {'text_unit_id': 'T', 'relation': 'CAPTION_FOR', 'anchor': 'The detector measures gravitational strain.',
             'basis': 'Figure caption', 'text_quality': 'UNVERIFIED'},
            {'text_unit_id': 'T', 'relation': 'ILLUSTRATES', 'anchor': 'The bottom panel shows residuals.',
             'basis': 'Visible residual panel', 'text_quality': 'SUSPECT'}]}
        runner.validate_edges(result, 'V', {'T': {'text': text}})
        self.assertEqual(len(result['edges']), 1)
        edge = result['edges'][0]
        self.assertEqual(edge['relation'], 'CAPTION_FOR')
        self.assertEqual(edge['text_quality'], 'SUSPECT')
        self.assertEqual(len(edge['supporting_spans']), 2)
        for span in edge['supporting_spans']:
            self.assertEqual(text[span['source_char_start']:span['source_char_end']], span['anchor'])

    def test_failed_flow_continues_to_next_page_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'image.png'
            Image.new('RGB', (20, 20)).save(image)
            rep = {'atoms': [{'atom_id': 'A', 'atom_type': 'text', 'text_fragments': runner.one_fragment('A', 'Source paragraph')}],
                   'visual_bundles': []}
            manifest = root / 'manifest.json'
            runner.write(manifest, {'sources': [{'document_id': 'test', 'mode': 'case', 'page': page}
                                                for page in ('page_0001', 'page_0002')]})
            args = argparse.Namespace(sources=manifest, output=root / 'out', fresh_root=root,
                staged_sources=root, pptx_audit=root, model='fake', local_check=False, resume=False,
                shard_index=0, shard_count=1)
            model = SimpleNamespace(generate_raw_with_images=None)
            answers = [SimpleNamespace(raw='{}'), SimpleNamespace(raw=json.dumps(runner.local_flow(rep)))]
            with patch.object(runner.base, 'create_llm', return_value=model), patch.object(
                    runner, 'dolphin_representation', return_value=(rep['atoms'], [], image)), patch.object(
                    model, 'generate_raw_with_images', side_effect=answers) as generate:
                self.assertTrue(runner.run(args))
                self.assertEqual(generate.call_count, 2)
            summary = runner.base.read(root / 'out/summary.json')
            self.assertEqual(summary['status'], 'completed_with_failures')
            self.assertEqual([p['status'] for p in summary['pages']], ['flow_failed', 'complete'])

    def test_bad_shape_rejected_without_crashing(self):
        for value in (None, [], {'content_items': [None]}, {'content_items': [{}]}):
            self.assertFalse(runner.validate_flow(value, {'atoms': [], 'visual_bundles': []})['valid'])

    def test_budget_stops_before_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = SimpleNamespace(generate_raw_with_images=lambda *a: self.fail('Must not call model'))
            bounded = runner.BudgetedLLM(model, 0, Path(tmp))
            with self.assertRaises(runner.InferenceBudgetExhausted):
                bounded.generate_raw_with_images('system', 'prompt', [], 10)
            self.assertTrue(runner.base.read(Path(tmp) / 'budget_stop.json')['resume_required'])


if __name__ == '__main__':
    unittest.main()
