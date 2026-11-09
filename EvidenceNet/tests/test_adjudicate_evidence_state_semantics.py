import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "adjudicate_evidence_state_semantics.py"
spec = importlib.util.spec_from_file_location("semantic_adjudication", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SemanticAdjudicationTests(unittest.TestCase):
    def test_supporting_span_is_original_text(self):
        nodes = [{"node_id": "n1", "rank": 1, "document": "d", "page": 1,
                  "text": "Federer won Wimbledon in 2005."}]
        req = {"id": "r", "label": "2005 Wimbledon", "groups": [["2005"], ["Wimbledon"]]}
        result = mod.adjudicate_requirement(req, nodes, [], ["n1"])
        self.assertEqual(result["state"], "supported")
        self.assertIn("Federer won Wimbledon", result["supporting_spans"][0]["spans"][0]["text"])

    def test_cross_relation_remains_uncertain(self):
        req = {"id": "r", "label": "comparison", "groups": [], "kind": "cross_evidence_relation"}
        result = mod.adjudicate_requirement(req, [], [], [])
        self.assertEqual(result["state"], "uncertain")

    def test_unknown_edge_is_not_navigation(self):
        nodes = {
            "s": {"node_id": "s", "rank": 1, "document": "d", "page": 1,
                  "text": "source fact"},
            "t": {"node_id": "t", "rank": 2, "document": "d", "page": 2,
                  "text": "target fact"},
        }
        route = {"edge_id": "e", "oriented_source_id": "s", "oriented_target_id": "t",
                 "eligibility": "unknown", "relation_type": "RELATED",
                 "relation_text": "fact", "provenance": [{"source": "qwen_original"}]}
        req = {"id": "r", "label": "target", "groups": [["target"]]}
        result = mod.adjudicate_requirement(req, [nodes["s"]], [route], ["s"])
        self.assertEqual(result["potential_retrieval_actions"], [])

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "existing"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                mod.run(out)


if __name__ == "__main__":
    unittest.main()
