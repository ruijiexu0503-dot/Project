import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_ann_candidate_pilot import aggregate, index_for, normalize, overlap, search_filtered
import numpy as np
import faiss


class CandidateTests(unittest.TestCase):
    def test_overfetch_past_large_same_article(self):
        v = normalize(np.array([[1, .001 * i] for i in range(40)] + [[.1, 1], [0, 1]], dtype=np.float32))
        ix, _ = index_for(v, False)
        hits = search_filtered(ix, v[:1], ["a"], ["a"] * 40 + ["b", "c"], 2)
        self.assertEqual([i for i, _ in hits[0]], [40, 41])

    def test_no_eligible_neighbor(self):
        v = normalize(np.array([[1, 0], [0, 1]], dtype=np.float32))
        ix, _ = index_for(v, True)
        self.assertEqual(search_filtered(ix, v, ["a", "a"], ["a", "a"], 10), [[], []])

    def test_multiple_evidence_hits_do_not_duplicate_article(self):
        result = aggregate([[(2, .9), (3, .8)], [(2, .7)], [], []],
                           [[(1, .8)], [(0, .8)]], {"a": [], "b": []},
                           ["a", "a", "b", "b"], ["a", "b"], 5, 5)
        self.assertEqual(len(result["a"]), 1)
        self.assertEqual(len(result["a"][0]["evidence"]), 3)
        self.assertEqual(result["a"][0]["edge_status"], "UNVERIFIED_RETRIEVAL_CANDIDATE")

    def test_reject_invalid_vectors(self):
        for v in ([[0, 0]], [[1, float("nan")]]):
            with self.assertRaises(ValueError):
                normalize(v)

    def test_fixed_route_depth_gives_nested_budgets(self):
        args = ([[(1, .9), (2, .8)] , [], []],
                [[(2, .9), (1, .8)], [(0, .9)], [(0, .9)]],
                {"a": [("b", 1)], "b": [], "c": []},
                ["a", "b", "c"], ["a", "b", "c"])
        small = aggregate(*args, budget=1, per_route=20)
        large = aggregate(*args, budget=2, per_route=20)
        self.assertEqual(small["a"], large["a"][:1])

    def test_append_returns_new_neighbor(self):
        ix, _ = index_for(normalize([[0, 1]]), True)
        ix.add(normalize([[1, 0]]))
        hits = search_filtered(ix, normalize([[1, 0]]), ["query"], ["old", "new"], 1)
        self.assertEqual(hits[0][0][0], 1)


if __name__ == "__main__":
    faiss.omp_set_num_threads(1)
    unittest.main()
