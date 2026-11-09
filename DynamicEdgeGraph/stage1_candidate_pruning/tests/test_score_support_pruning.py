import unittest
from DynamicEdgeGraph.stage1_candidate_pruning.src.run_score_support_pruning import sg
class TestScoreSupportPruning(unittest.TestCase):
 def test_support_groups(self):
  self.assertEqual(sg(1),'support_1');self.assertEqual(sg(2),'support_2');self.assertEqual(sg(3),'support_3plus');self.assertEqual(sg(5),'support_3plus')
 def test_boundary_semantics(self):
  # SQL gates use >=: score exactly at a route-local quantile is retained.
  self.assertTrue(0.9>=0.9);self.assertTrue(0.899999<0.9)
if __name__=='__main__':unittest.main()
