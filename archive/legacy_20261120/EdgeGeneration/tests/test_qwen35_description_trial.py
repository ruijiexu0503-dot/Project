import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_qwen35_description_trial import matched, FIELDS


class DescriptionJoinTests(unittest.TestCase):
    def setUp(self):
        self.node = dict(document_order=2, evidence_type='text', base_summary='Old description',
                         key_points=['a'], entities=['x'], keywords=['y'], discourse_role='result')
        self.row = dict(document_order=2, evidence_type='text', qwen2_5_baseline={k:self.node[k] for k in FIELDS})

    def test_matching_baseline(self):
        self.assertTrue(matched(self.node, self.row))

    def test_reused_id_with_different_content_metadata_is_rejected(self):
        self.node['key_points'] = ['different']
        self.assertFalse(matched(self.node, self.row))

    def test_missing_or_reordered_node_is_rejected(self):
        self.assertFalse(matched(None, self.row))
        self.node['document_order'] = 3
        self.assertFalse(matched(self.node, self.row))
