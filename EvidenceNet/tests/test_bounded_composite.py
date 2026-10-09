import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_bounded_composite_pilot as pilot
from bounded_geometry import source_anchor, pair_hint, candidates_for


class BoundedCompositeTests(unittest.TestCase):
    def test_whitespace_only_matching_preserves_source_offsets(self):
        text = 'Prefix: receiver and the\nrespective array antenna on a ship.'
        resolved = source_anchor(text, 'receiver and the respective array antenna on a ship.')
        self.assertEqual(text[resolved['source_char_start']:resolved['source_char_end']], resolved['anchor'])
        self.assertIn('\n', resolved['anchor'])
        with self.assertRaises(ValueError):
            source_anchor(text, 'receiver and a respective array antenna on a ship.')

    def test_geometry_penalizes_intervening_content_and_cross_column(self):
        image = [100, 100, 300, 300]
        caption = [100, 340, 300, 370]
        clear = pair_hint(image, caption, [], (1000, 1000))
        blocked = pair_hint(image, caption, [[100, 310, 300, 330]], (1000, 1000))
        cross_column = pair_hint(image, [600, 340, 800, 370], [], (1000, 1000))
        self.assertLess(clear['score'], blocked['score'])
        self.assertLess(clear['score'], cross_column['score'])

    def test_no_geometry_still_retains_semantic_candidate(self):
        unit = {'evidence_unit_id': 'EU_001', 'caption_candidate': True, 'fragment_ids': ['F1']}
        atom = {'atom_id': 'A1'}
        selected, _ = candidates_for({'visual_bundle_id': 'V1'}, [unit],
            {'atoms': [atom], 'visual_bundles': []}, {'F1': {'atom': atom, 'text': 'A sufficiently detailed caption without recorded geometry.'}}, (1000, 1000))
        self.assertEqual(selected[0]['unit_id'], 'EU_001')
        self.assertTrue(selected[0]['geometry']['unavailable'])

    def test_shared_caption_preserves_text_once(self):
        text = 'The aerial view of the centre. Bottom image: team examining a map.'
        links = [{'visual_id': 'V1', 'anchor': 'The aerial view of the centre.', 'relation': 'CAPTION'},
                 {'visual_id': 'V2', 'anchor': 'Bottom image: team examining a map.', 'relation': 'CAPTION'}]
        review = {'accepted': links, 'text_quality': 'UNVERIFIED', 'basis': 'Two explicit referents'}
        pilot.validate_review(review, ['V1', 'V2', 'V3'], text)
        units = [{'evidence_unit_id': 'EU_001', 'fragment_ids': ['F1'], 'visual_panel_ids': [],
                  'unit_type': 'TEXT', 'completeness': 'POSSIBLE_CONTINUATION'}]
        flow = {'content_items': [{'content_item_id': 'C1', 'visual_panel_ids': ['V1', 'V2', 'V3']}]}
        decisions = [{'visual_id': v, 'caption_unit_id': 'EU_001', 'decision': 'MATCH'} for v in ['V1', 'V2', 'V3']]
        result = pilot.assemble(units, flow, decisions, {'EU_001': review})['evidence_units']
        self.assertEqual(result[0]['visual_panel_ids'], ['V1', 'V2'])
        self.assertEqual(result[1]['visual_panel_ids'], ['V3'])
        self.assertEqual([f for u in result for f in u['fragment_ids']], ['F1'])
        self.assertEqual(units[0]['visual_panel_ids'], [])

    def test_reject_invented_duplicate_and_generic_anchors(self):
        text = 'This picture shows the eye examination.'
        for links in [
            [{'visual_id': 'V1', 'anchor': 'Invented source phrase', 'relation': 'CAPTION'}],
            [{'visual_id': v, 'anchor': text, 'relation': 'CAPTION'} for v in ['V1', 'V1']],
            [{'visual_id': v, 'anchor': text, 'relation': 'CAPTION'} for v in ['V1', 'V2']],
            [{'visual_id': 'V9', 'anchor': text, 'relation': 'CAPTION'}],
        ]:
            with self.assertRaises(ValueError):
                pilot.validate_review({'accepted': links, 'text_quality': 'UNVERIFIED', 'basis': 'test'}, ['V1', 'V2'], text)

    def test_direct_explanation_with_suspect_text_stays_pending(self):
        text = 'This picture shows the eye examination.'
        review = {'accepted': [{'visual_id': 'V1', 'anchor': text, 'relation': 'DIRECT_EXPLANATION'}],
                  'text_quality': 'SUSPECT', 'basis': 'Possible transcription anomaly'}
        pilot.validate_review(review, ['V1'], text)
        result = pilot.assemble([{'evidence_unit_id': 'EU_001', 'visual_panel_ids': [], 'completeness': 'COMPLETE'}],
            {'content_items': [{'content_item_id': 'C1', 'visual_panel_ids': ['V1']}]},
            [{'visual_id': 'V1'}], {'EU_001': review})
        self.assertEqual(result['evidence_units'][0]['completeness'], 'UNRESOLVED')

    def test_review_ids_hide_parser_words_but_restore_source_ids(self):
        forward, reverse = pilot.opaque_review_ids(['dolphin_visual_p0002_e0007', 'P_0009_A02'])
        self.assertEqual(forward['dolphin_visual_p0002_e0007'], 'VISUAL_01')
        self.assertNotIn('dolphin', forward['dolphin_visual_p0002_e0007'])
        review = pilot.restore_review_ids({'accepted': [{'visual_id': 'VISUAL_01'}]}, reverse)
        self.assertEqual(review['accepted'][0]['visual_id'], 'dolphin_visual_p0002_e0007')


if __name__ == '__main__':
    unittest.main()
