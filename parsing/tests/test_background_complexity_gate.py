"""Unit checks for the shadow background-complexity gate."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from audit_background_complexity_gate import assess, normalized_split_boundaries


CFG = {
    'irregular_support_min_missing_fraction': .02,
    'dense_text_min_lines': 8,
    'dense_text_min_area_fraction': .08,
}


def features(**updates):
    base = {
        'nonrect_clip': False,
        'source_soft_mask': False,
        'support_missing_fraction': 0,
        'crosses_known_boundary': [],
        'confirmed_image_overlaps': [],
        'supported_text_lines': 0,
        'supported_text_area_fraction': 0,
    }
    base.update(updates)
    return base


class ComplexityGate(unittest.TestCase):
    def test_split_boundary_is_normalized_in_manifest_coordinates(self):
        split = {'pages': [
            {'source_page': 'page_000009', 'bbox': [0, 0, 893, 1263]},
            {'source_page': 'page_000009', 'bbox': [893, 0, 1786, 1263]},
        ]}
        self.assertEqual(normalized_split_boundaries(split, 'page_000009'), [.5])

    def test_full_page_has_no_internal_boundary(self):
        split = {'pages': [
            {'source_page': 'page_000001', 'bbox': [0, 0, 893, 1263]},
        ]}
        self.assertEqual(normalized_split_boundaries(split, 'page_000001'), [])

    def test_simple_image_with_small_text_overlay_stays_fast(self):
        result = assess(features(supported_text_lines=2,
                                 supported_text_area_fraction=.01), CFG)
        self.assertEqual(result['decision'], 'FAST_BBOX')

    def test_each_complexity_signal_requests_dual_masks(self):
        cases = [
            {'nonrect_clip': True},
            {'source_soft_mask': True},
            {'support_missing_fraction': .03},
            {'crosses_known_boundary': [.5]},
            {'confirmed_image_overlaps': [{'asset_id': 'other'}]},
            {'supported_text_lines': 8},
            {'supported_text_area_fraction': .08},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(assess(features(**case), CFG)['decision'], 'DUAL_MASK')


if __name__ == '__main__':
    unittest.main()
