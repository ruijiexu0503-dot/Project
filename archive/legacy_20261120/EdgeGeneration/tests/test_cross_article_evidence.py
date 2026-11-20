import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_cross_article_evidence import diversify, canonical_pairs


class EvidenceCandidatesTests(unittest.TestCase):
    def test_article_crowding_does_not_consume_budget(self):
        hits = [(i, 1-i*.01) for i in range(7)]
        result = diversify(hits, ['a']*5+['b','c'], 4, 2)
        self.assertEqual([i for i, _ in result], [0, 1, 5, 6])

    def test_short_pool_is_not_padded(self):
        self.assertEqual(diversify([(0,.9)], ['a'], 10), [(0,.9)])

    def test_reverse_candidate_dedup_and_no_self_links(self):
        self.assertEqual(canonical_pairs({(1,2),(2,1),(1,1)}), {(1,2)})


if __name__ == '__main__':
    unittest.main()
