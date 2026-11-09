import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_remaining_query_edge_routes.py"
spec = importlib.util.spec_from_file_location("remaining_audit", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def route(edge_id="e1", source="s", target="t", eligibility="unknown"):
    return {
        "edge_id": edge_id, "route_id": f"{edge_id}:{source}:{target}",
        "oriented_source_id": source, "oriented_target_id": target,
        "eligibility": eligibility, "relation_type": "RELATED",
        "relation_text": "same entity", "conditions": "", "limitations": "",
        "source_anchors": [{"member_id": "ms", "quote": "source", "localizable": True,
                            "granularity": "span_window"}],
        "target_anchors": [{"member_id": "mt", "quote": "target", "localizable": True,
                            "granularity": "span_window"}],
        "provenance": [{"source": "qwen_original"}],
    }


class RemainingAuditTests(unittest.TestCase):
    def setUp(self):
        self.review = mod.load_review_module()
        self.nodes = {
            "s": {"id": "s", "document": "a", "page": 1, "members": [{"id": "ms", "text": "source"}]},
            "t": {"id": "t", "document": "b", "page": 1, "members": [{"id": "mt", "text": "target"}]},
        }
        self.nav = [{"question_id": "q", "node_ranking": ["s", "t"]}]

    def decisions(self, count=2):
        result = []
        for number in range(count):
            edge = route(f"e{number}", target="t")
            for arm in self.review.ARMS:
                result.append({
                    "question_id": "q", "question": "What is the target?",
                    "route": edge, "source_dense_rank": 1, "target_dense_rank": 2,
                    "target_page": ["b", 1], "arm": arm, "action": "reject",
                })
        return result

    def test_set_difference_and_blinding(self):
        all_rows = self.review.consolidate(self.decisions(), self.nav, self.nodes, {"s", "t"})
        first = {all_rows[0]["sample_id"]}
        _, remaining = mod.build_remaining(
            self.decisions(), self.nav, self.nodes, {"s", "t"}, first, self.review,
            expected_total=2, expected_first=1, expected_remaining=1,
        )
        self.assertEqual(len(remaining), 1)
        card = self.review.review_card(remaining[0], self.nodes)
        encoded = json.dumps(card)
        self.assertNotIn("eligibility", encoded)
        self.assertNotIn("arm_actions", encoded)
        self.assertNotIn("source_kind", encoded)
        self.assertNotIn("gold_evidence", encoded.lower())

    def test_duplicate_or_wrong_first_ids_fail(self):
        with self.assertRaises(ValueError):
            mod.build_remaining(self.decisions(), self.nav, self.nodes, {"s", "t"},
                                {"does-not-exist"}, self.review)

    def test_missing_query_context_fails(self):
        with self.assertRaises(ValueError):
            self.review.consolidate(self.decisions(), [], self.nodes, {"s", "t"})

    def test_duplicate_arm_decision_fails(self):
        decisions = self.decisions()
        decisions.append(decisions[0])
        with self.assertRaises(ValueError):
            self.review.consolidate(decisions, self.nav, self.nodes, {"s", "t"})

    def test_direction_is_part_of_route_identity(self):
        forward = route("e", "s", "t")
        reverse = route("e", "t", "s")
        self.assertNotEqual(forward["route_id"], reverse["route_id"])

    def test_empty_path_is_safe(self):
        with self.assertRaises(ValueError):
            mod.build_remaining([], self.nav, self.nodes, {"s", "t"}, set(), self.review)

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "existing"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                mod.audit(Path(tmp) / "missing", Path(tmp) / "missing",
                          Path(tmp) / "missing", Path(tmp) / "missing",
                          Path(tmp) / "missing", out)


if __name__ == "__main__":
    unittest.main()
