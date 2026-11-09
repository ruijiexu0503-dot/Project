import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mine_query_edge_positive_opportunities.py"
spec = importlib.util.spec_from_file_location("positive_mining", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def edge(edge_id, source, target, eligibility="allowed", source_kind="qwen_original"):
    return {
        "edge_id": edge_id, "oriented_source_id": source, "oriented_target_id": target,
        "eligibility": eligibility, "relation_type": "RELATED", "relation_text": "shared facts",
        "provenance": [{"source": source_kind}],
        "source_anchors": [{"node_id": source, "member_id": "m", "quote": "source",
                            "kind": "ORIGINAL_TEXT", "localizable": True}],
        "target_anchors": [{"node_id": target, "member_id": "m", "quote": "target",
                            "kind": "ORIGINAL_TEXT", "localizable": True}],
    }


class PositiveMiningTests(unittest.TestCase):
    def test_directional_two_hop_and_status(self):
        routes = [edge("e1", "s", "m"), edge("e2", "m", "t")]
        paths = mod.find_paths(mod.adjacency(routes), ["s"], "t")
        self.assertEqual(len(paths), 1)
        self.assertEqual(mod.path_status(paths[0]), "allowed_path")

    def test_denied_edge_never_becomes_positive(self):
        route = edge("e", "s", "t", eligibility="denied")
        paths = mod.find_paths(mod.adjacency([route]), ["s"], "t")
        self.assertEqual(mod.classify_path(paths[0], "t", {"s"}, {}), "reachable_but_relation_invalid")

    def test_unknown_is_inspection_only(self):
        route = edge("e", "s", "t", eligibility="unknown")
        paths = mod.find_paths(mod.adjacency([route]), ["s"], "t")
        self.assertEqual(mod.path_status(paths[0]), "inspection_only_path")

    def test_no_relation_and_unreachable_are_distinct(self):
        routes = [edge("e", "x", "t")]
        self.assertTrue(mod.target_has_any_relation(routes, "t"))
        self.assertFalse(mod.target_has_any_relation(routes, "z"))

    def test_edge_first_is_constructed_and_unlabeled(self):
        nodes = {
            "s": {"members": [{"text": "method measures accuracy on images"}]},
            "t": {"members": [{"text": "method reports accuracy under noisy images"}]},
        }
        candidate = mod.edge_first_candidates([edge("e", "s", "t")], nodes, limit=1)
        self.assertEqual(len(candidate), 1)
        self.assertTrue(candidate[0]["constructed_evaluation"])
        self.assertEqual(candidate[0]["manual_checks"]["label"], "uncertain")

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "existing"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                mod.run(out)


if __name__ == "__main__":
    unittest.main()
