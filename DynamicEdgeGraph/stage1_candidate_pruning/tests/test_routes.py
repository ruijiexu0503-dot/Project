import unittest
from DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates import bm25, structural


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {"node_id": "a", "document_id": "d", "page_number": 1, "text": "watermelon pollination"},
            {"node_id": "b", "document_id": "d", "page_number": 2, "text": "bee pollination"},
            {"node_id": "c", "document_id": "e", "page_number": 9, "text": "unrelated topic"},
        ]

    def test_bm25_is_bounded_and_excludes_self(self):
        rows = bm25(self.nodes, 1, "bm25", "test")
        self.assertTrue(rows)
        self.assertTrue(all(r["source_id"] != r["target_id"] for r in rows))
        self.assertLessEqual(len(rows), len(self.nodes))

    def test_structural_is_document_page_bounded(self):
        rows = structural(self.nodes, 1, "structural", "test")
        self.assertTrue(any(r["source_id"] == "a" and r["target_id"] == "b" for r in rows))
        self.assertFalse(any(r["source_id"] == "a" and r["target_id"] == "c" for r in rows))


if __name__ == "__main__":
    unittest.main()
