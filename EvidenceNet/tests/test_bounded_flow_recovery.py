import copy
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
import flow_recovery as recovery
import run_relation_first_corpus_shadow as runner


class BoundedRecoveryTests(unittest.TestCase):
    def fixture(self):
        rep = {'atoms': [{'atom_id': 'A', 'atom_type': 'heading',
                         'text_fragments': runner.one_fragment('A', 'A measured signal'),
                         'geometry_members': []}], 'visual_bundles': []}
        valid = runner.local_flow(rep)
        bad = copy.deepcopy(valid)
        bad['content_items'][0]['flows'].append({'flow_id': 'F', 'flow_kind': 'main',
                                               'fragment_ids': ['A::F001'], 'continuations': []})
        return rep, valid, bad

    def test_bounded_call_and_preserved_source(self):
        rep, valid, bad = self.fixture()
        replies = iter([json.dumps(bad), '{"A::F001": 2}'])
        class LLM:
            calls = 0
            def generate_raw_with_images(self, *args):
                self.calls += 1
                return SimpleNamespace(raw=next(replies))
        model = LLM()
        with tempfile.TemporaryDirectory() as tmp:
            out = runner.make_flow(rep, Path('image.png'), model, Path(tmp), False, recovery_policy='bounded-v1')
            self.assertTrue(runner.validate_flow(out, rep)['valid'])
            self.assertEqual(out['content_items'][0]['structural_fragments'], valid['content_items'][0]['structural_fragments'])
            self.assertEqual(model.calls, 2)
            audit = runner.base.read(Path(tmp) / 'flow_recovery.json')
            self.assertTrue(audit['needs_review'])
            self.assertFalse(audit['semantic_validated'])

    def test_unparsed_flow_records_failed_audit(self):
        rep, _, _ = self.fixture()
        model = SimpleNamespace(generate_raw_with_images=lambda *args: SimpleNamespace(raw='not JSON'))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                runner.make_flow(rep, Path('image.png'), model, Path(tmp), False, recovery_policy='bounded-v1')
            audit = runner.base.read(Path(tmp) / 'flow_recovery.json')
            self.assertEqual(audit['status'], 'failed')
            self.assertTrue(audit['needs_review'])

    def test_abstention_and_unknown_choices_rejected(self):
        rep, _, bad = self.fixture()
        options = recovery.duplicate_options(bad, rep)
        for answer in ({'choices': {'A::F001': 'UNRESOLVED'}}, {'A::F001': True}, {'FAKE': 1},
                       {'choices': {'A::F001': 1}, 'extra': 'not allowed'}):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                recovery.apply_choices(bad, options, answer)
        self.assertEqual(len(bad['content_items'][0]['flows'][0]['fragment_ids']), 1)

    def test_missing_fragment_never_fabricated(self):
        rep, _, bad = self.fixture()
        rep['atoms'].append({'atom_id': 'B', 'atom_type': 'text',
                             'text_fragments': runner.one_fragment('B', 'Missing actual source text')})
        repaired, _ = recovery.apply_choices(bad, recovery.duplicate_options(bad, rep), {'A::F001': 2})
        check = runner.validate_flow(repaired, rep)
        self.assertFalse(check['valid'])
        self.assertIn('B::F001', check['errors'][0]['missing'])

    def test_duplicate_visual_within_same_item_uses_occurrence(self):
        rep, flow, _ = self.fixture()
        rep['visual_bundles'] = [{'visual_bundle_id': 'V'}]
        flow['content_items'][0]['visual_panel_ids'] = ['V', 'V']
        fixed, _ = recovery.apply_choices(flow, recovery.duplicate_options(flow, rep), {'V': 2})
        self.assertEqual(fixed['content_items'][0]['visual_panel_ids'], ['V'])
        self.assertTrue(runner.validate_flow(fixed, rep)['valid'])

    def test_visual_only_skips_llm_and_records_limitation(self):
        class NoCalls:
            def generate_raw_with_images(self, *args):
                raise AssertionError('visual-only branch must not call LLM')
        rep = {'atoms': [], 'visual_bundles': [{'visual_bundle_id': 'V'}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = runner.make_flow(rep, Path('image.png'), NoCalls(), Path(tmp), False, recovery_policy='bounded-v1')
            self.assertTrue(runner.validate_flow(out, rep)['valid'])
            self.assertEqual(out['content_items'][0]['kind'], 'page_context')
            self.assertTrue(runner.base.read(Path(tmp) / 'flow_recovery.json')['text_recovery_required'])

    def test_visual_only_full_run_remains_partial_on_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / 'page.png'
            Image.new('RGB', (100, 100), 'white').save(image)
            work = root / 'work'
            runner.write(work / 'output_json/page.json', [{'label': 'fig', 'text': '', 'bbox': [0,0,100,100]}])
            runner.write(work / 'run_summary.json', {'image_size': [100,100]})
            manifest = root / 'manifest.json'
            runner.write(manifest, {'sources': [{'document_id':'test', 'page':'page_0001',
                'mode':'case', 'work':str(work), 'image':str(image)}]})
            args = argparse.Namespace(sources=manifest, output=root/'out', fresh_root=root,
                staged_sources=root, pptx_audit=root, model='fake', local_check=False,
                resume=False, shard_index=0, shard_count=1, recovery_policy='bounded-v1')
            with patch.object(runner.base, 'create_llm', return_value=object()):
                runner.run(args)
            page = root/'out/test/page_0001'
            summary = runner.base.read(page/'summary.json')
            self.assertEqual(summary['status'], 'partial')
            self.assertTrue(summary['flow_review_required'])
            self.assertEqual(summary['components'],1)
            (page/'summary.json').unlink()
            args.resume = True
            with patch.object(runner.base, 'create_llm', return_value=object()):
                runner.run(args)
            self.assertEqual(runner.base.read(page/'summary.json')['status'], 'partial')
            self.assertTrue(runner.base.read(page/'summary.json')['flow_review_required'])

    def test_bad_support_does_not_mask_primary_or_caption_rules(self):
        text = 'The source shows a measured gravitational wave.'
        edge = {'text_unit_id': 'T', 'relation': 'ILLUSTRATES', 'anchor': text,
                'basis': 'Visible signal', 'text_quality': 'UNVERIFIED',
                'supporting_anchors': ['A completely invented supporting quote.', 'measured gravitational wave.']}
        payload = {'visual_label': 'V', 'edges': [edge]}
        result, rejected = runner.validate_edges_individually(payload, 'V', {'T': {'text': text}}, True)
        self.assertEqual(len(result['edges']), 1)
        self.assertEqual(len(result['edges'][0]['supporting_spans']), 2)
        self.assertTrue(rejected[0]['edge_retained'])
        self.assertEqual(len(edge['supporting_anchors']), 2)
        edge['anchor'] = 'A fabricated primary source quote.'
        result, _ = runner.validate_edges_individually(payload, 'V', {'T': {'text': text}}, True)
        self.assertFalse(result['edges'])
        edge.update(anchor=text, relation='CAPTION_FOR')
        result, _ = runner.validate_edges_individually(payload, 'V', {'T': {'text': text, 'caption_policy': 'body_only'}}, True)
        self.assertFalse(result['edges'])


if __name__ == '__main__':
    unittest.main()
