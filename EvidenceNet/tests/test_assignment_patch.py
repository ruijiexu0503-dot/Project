import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_relation_first_corpus_shadow as r
import flow_recovery as f


class PatchTests(unittest.TestCase):
    def fixture(self):
        rep = {'atoms': [{'atom_id': a, 'atom_type': 'text',
                         'text_fragments': r.one_fragment(a, a + ' content')}
                        for a in ['A', 'B']], 'visual_bundles': [{'visual_bundle_id': 'V'}]}
        flow = r.local_flow(rep)
        item = flow['content_items'][0]
        item['flows'] = [{'flow_id': 'F', 'flow_kind': 'main',
                          'fragment_ids': ['A::F001'], 'continuations': []}]
        item['visual_panel_ids'] = []
        return rep, flow

    def answer(self, flow):
        common = {'content_item_id': flow['content_items'][0]['content_item_id'], 'basis': 'Visible on page'}
        return {'duplicate_choices': {}, 'placements': [
            {**common, 'source_id': 'B::F001', 'destination': 'flow', 'flow_id': 'F', 'after_fragment_id': 'A::F001'},
            {**common, 'source_id': 'V', 'destination': 'visual'}]}

    def test_patch_exact_coverage_and_immutability(self):
        rep, flow = self.fixture(); original = copy.deepcopy((rep, flow))
        fixed, plan = f.prepare_patch(flow, rep)
        out, audit = f.apply_patch_choices(fixed, plan, self.answer(flow))
        self.assertTrue(r.validate_flow(out, rep)['valid'])
        self.assertEqual((rep, flow), original)
        self.assertEqual(out['content_items'][0]['flows'][0]['fragment_ids'], ['A::F001', 'B::F001'])

    def test_invalid_claims_do_not_discard_real_sources(self):
        rep, flow = self.fixture(); item = flow['content_items'][0]
        item['flows'][0]['fragment_ids'] += ['FAKE', 'V']
        item['structural_fragments'] = [{'fragment_id': 'B::F001', 'role': 'table'}]
        item['flows'][0]['continuations'] = [{'from_fragment_id': 'A::F001', 'to_fragment_id': 'A::F001', 'kind': 'same_sentence'}]
        fixed, plan = f.prepare_patch(flow, rep)
        self.assertEqual(plan['missing'], {'B::F001': 'fragment', 'V': 'visual'})
        self.assertEqual(len(plan['removed_invalid_claims']), 4)
        answer = self.answer(flow)
        answer['placements'][0] = {k:v for k,v in answer['placements'][0].items() if k not in {'flow_id','after_fragment_id'}}
        answer['placements'][0].update(destination='new_flow', flow_kind='main')
        out, _ = f.apply_patch_choices(fixed, plan, answer)
        self.assertTrue(r.validate_flow(out, rep)['valid'])
        self.assertFalse(out['content_items'][0]['structural_fragments'])

    def test_reject_invented_incomplete_mistyped_or_unresolved_placements(self):
        rep, flow = self.fixture(); fixed, plan = f.prepare_patch(flow, rep)
        changes = [{'source_id':'FAKE'}, {'destination':'UNRESOLVED'},
                   {'content_item_id':'NEW_ITEM'}, {'after_fragment_id':'FAKE'},
                   {'destination':'visual'}, {'basis':''}]
        for change in changes:
            answer = self.answer(flow); answer['placements'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                f.apply_patch_choices(fixed, plan, answer)
        answer = self.answer(flow); answer['placements'].pop()
        with self.assertRaises(ValueError): f.apply_patch_choices(fixed, plan, answer)

    def test_deterministic_cleanup_requires_no_model_call(self):
        rep, flow = self.fixture(); fixed, plan = f.prepare_patch(flow, rep)
        flow, _ = f.apply_patch_choices(fixed, plan, self.answer(flow))
        flow['content_items'][0]['flows'][0]['fragment_ids'].append('HALLUCINATED')
        with tempfile.TemporaryDirectory() as tmp:
            out = r.repair_flow_patch(flow, rep, Path('unused.png'), None, Path(tmp))
            self.assertTrue(r.validate_flow(out, rep)['valid'])
            audit = r.base.read(Path(tmp)/'flow_recovery.json')
            self.assertEqual(audit['additional_model_calls'], 0)
            self.assertTrue(audit['needs_review'])

    def test_make_flow_v2_has_one_bounded_additional_call(self):
        import json
        rep, flow = self.fixture(); replies = iter([json.dumps(flow), json.dumps(self.answer(flow))])
        calls=[]
        def generate(*args):
            calls.append(args); return SimpleNamespace(raw=next(replies))
        with tempfile.TemporaryDirectory() as tmp:
            out=r.make_flow(rep, Path('unused.png'), SimpleNamespace(generate_raw_with_images=generate), Path(tmp), False, recovery_policy='bounded-v2')
            self.assertTrue(r.validate_flow(out,rep)['valid'])
            self.assertEqual(len(calls),2)
            self.assertFalse(r.base.read(Path(tmp)/'flow_recovery.json')['semantic_validated'])


if __name__ == '__main__': unittest.main()
