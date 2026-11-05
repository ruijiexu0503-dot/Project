import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_query_edge_utility.py"
spec = importlib.util.spec_from_file_location("query_edge_review", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def route(edge_id="e1", source="s", target="t", eligibility="unknown", kind="qwen_original"):
    return {
        "edge_id": edge_id, "route_id": f"{edge_id}:{source}:{target}",
        "oriented_source_id": source, "oriented_target_id": target,
        "eligibility": eligibility, "relation_type": "RELATED",
        "relation_text": "auditor ratification",
        "source_anchors": [{"member_id": "ms", "quote": "auditor", "localizable": True,
                            "granularity": "span_window"}],
        "target_anchors": [{"member_id": "mt", "quote": "KPMG", "localizable": True,
                            "granularity": "span_window"}],
        "provenance": [{"source": kind}],
    }


def setup():
    ids = ["s"] + [f"d{i}" for i in range(1, 24)] + ["t"]
    nodes = {key: {"id": key, "document": "doc-b" if key == "t" else "doc-a",
                   "page": 1, "node_type": "text",
                   "members": [{"id": "ms" if key == "s" else "mt",
                                "text": "KPMG independent auditor vote"}]}
             for key in ids}
    nav = [{"question_id": "q1", "node_ranking": ids}]
    decisions = []
    for arm in mod.ARMS:
        decisions.append({"question_id": "q1", "question": "director election?",
                          "route": route(), "source_dense_rank": 1,
                          "target_dense_rank": 25, "target_page": ["doc-b", 1],
                          "arm": arm, "action": "inspect" if arm != mod.ARMS[-1] else "reject"})
    return nodes, nav, decisions


class ReviewTests(unittest.TestCase):
    def test_consolidation_and_blinding(self):
        nodes, nav, decisions = setup()
        rows = mod.consolidate(decisions, nav, nodes, set(nodes))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stratum"], "qwen_new_page")
        self.assertEqual(rows[0]["arm_actions"]["R2_anchor_proxy"], "reject")
        card = mod.review_card(rows[0], nodes)
        self.assertNotIn("eligibility", json.dumps(card))
        self.assertNotIn("source_kind", json.dumps(card))
        self.assertNotIn("gold_evidence", json.dumps(card).lower())
        self.assertEqual(card["source"]["anchors"][0]["anchor_quote"], "auditor")

    def test_deterministic_sample_without_scores(self):
        nodes, nav, decisions = setup()
        rows = mod.consolidate(decisions, nav, nodes, set(nodes))
        self.assertEqual(mod.sample_routes(rows, 12)[0]["sample_id"],
                         mod.sample_routes(rows[::-1], 12)[0]["sample_id"])

    def test_unknown_label_is_not_negative(self):
        self.assertEqual(mod.utility_label({"relation_validity": "uncertain",
                                            "query_applicability": "yes",
                                            "marginal_utility": "yes"}), "unknown")
        self.assertEqual(mod.utility_label({"relation_validity": "invalid",
                                            "query_applicability": "uncertain",
                                            "marginal_utility": "yes"}), "negative")

    def test_evaluation_is_subset_only_and_no_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            idx = p / "index.jsonl"
            lab = p / "labels.jsonl"
            index = {"sample_id": "id", "source_kind": "qwen_original",
                     "outside_dense20": True,
                     "arm_actions": {"R1_static": "inspect", "R2_target_only": "reject",
                                     "R2_anchor_proxy": "reject"}}
            label = {"sample_id": "id", "relation_validity": "valid",
                     "query_applicability": "yes", "marginal_utility": "yes",
                     "opportunity_cost": "prefer_target"}
            idx.write_text(json.dumps(index) + "\n")
            lab.write_text(json.dumps(label) + "\n")
            summary = mod.evaluate(idx, lab, p / "evaluation")
            self.assertEqual(summary["metrics"]["R1_static"]["tp"], 1)
            self.assertEqual(summary["metrics"]["R2_target_only"]["fn"], 1)
            self.assertEqual(summary["metrics"]["R2_anchor_proxy"]["recall_reviewed"], 0)
            self.assertNotIn("allowed_for_navigation", json.dumps(summary))

    def test_incomplete_labels_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            idx = p / "index.jsonl"
            lab = p / "labels.jsonl"
            idx.write_text(json.dumps({"sample_id": "id"}) + "\n")
            lab.write_text(json.dumps({"sample_id": "id", "relation_validity": "valid"}) + "\n")
            with self.assertRaises(ValueError):
                mod.evaluate(idx, lab, p / "evaluation")

    def test_missing_arm_rejected(self):
        nodes, nav, decisions = setup()
        with self.assertRaises(ValueError):
            mod.consolidate(decisions[:-1], nav, nodes, set(nodes))


if __name__ == "__main__":
    unittest.main()
