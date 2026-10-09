import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evidence_boundary_v3 import anchors, validate


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.pair = {'pair_id':'P1','left_tail':'Earlier sentence. At the left we have three',
                     'right_head':'possibilities to consider.', 'guard_reason':None}
        left,right = anchors(self.pair)
        self.row = {'pair_id':'P1','left_quote':left,'right_quote':right,
                    'same_sentence':True,'decision':'CONTINUATION','reason':'Completes the noun phrase.'}

    def check(self): return validate({'pairs':[self.row]}, {'pairs':[self.pair]})

    def test_valid(self): self.assertEqual(self.check(), [])

    def test_invented_boundary(self):
        self.row['left_quote'] = 'weigh'
        self.assertIn('P1:boundary_quote_mismatch', self.check())

    def test_contradictory_label(self):
        self.row['decision'] = 'SEPARATE'
        self.assertIn('P1:decision_predicate_contradiction', self.check())

    def test_guard(self):
        self.pair['guard_reason'] = 'closed_sentence'
        self.assertIn('P1:guard_violation', self.check())

    def test_string_boolean_rejected(self):
        self.row['same_sentence'] = 'true'
        self.assertIn('P1:same_sentence_not_boolean', self.check())

    def test_unbounded_reason(self):
        self.row['reason'] = 'x'*181
        self.assertIn('P1:reason_too_long_or_missing', self.check())


if __name__ == '__main__': unittest.main()
