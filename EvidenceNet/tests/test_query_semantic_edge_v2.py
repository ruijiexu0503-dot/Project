import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import query_semantic_edge_policy_v2 as policy
import run_query_semantic_edge_v2 as runner


class Tok:
    def encode(self, text, add_special_tokens=False):
        return text.split()


def render(values):
    return " ".join(value["text"] for value in values)


def packet(text, score=0, page="1"):
    return {"text": text, "page": ["d", page], "member_sha256": text,
            "base_score": score}


def assessment(rid="R1", status="missing", span=""):
    facts = [{"meaning": span, "span_ids": [span]}] if span else []
    return {"requirements": [{"id": rid, "status": status,
        "validation_state": "valid", "exhaustive": False, "support_facts": facts,
        "observations": [], "missing": [] if facts else ["needed"]}]}


def group(route, packet_ids, rid="R1", status="sufficient", spans=None):
    spans = spans or [pid + ":S0" for pid in packet_ids]
    return {"route_id": route, "source_node": "a", "target_node": "b",
            "packet_ids": packet_ids, "facts": [{"requirement_id": rid,
                "status": status, "span_ids": spans, "packet_ids": packet_ids,
                "meaning": "joint support"}]}


def test_joint_and_independent_direct_support_compete_without_type_error():
    packets = {"A": packet("identity"), "B": packet("value"),
               "C": packet("other requirement", 5, "2")}
    assessments = {"A": assessment(), "B": assessment(),
                   "C": assessment("R2", "sufficient", "C:S0")}
    packed = policy.pack_with_joint(packets, assessments,
        [group("ab", ["A", "B"])], 100, Tok(), render)
    assert set(packed["selected_ids"]) == {"A", "B", "C"}


def test_oversize_joint_group_falls_back_to_short_direct_support():
    packets = {"A": packet("many words in identity source"),
               "B": packet("many words in value source", page="2"),
               "C": packet("short", 1, "3")}
    assessments = {"A": assessment(), "B": assessment(),
                   "C": assessment("R1", "sufficient", "C:S0")}
    packed = policy.pack_with_joint(packets, assessments,
        [group("ab", ["A", "B"])], 1, Tok(), render)
    assert packed["selected_ids"] == ["C"]
    assert any(row["id"] == "joint:ab" and row["reason"] == "no_new_requirement_support"
               for row in packed["dropped"])


def test_overlapping_joint_groups_add_shared_packet_once_and_keep_both_requirements():
    packets = {pid: packet(pid, page=str(index)) for index, pid in enumerate(("A", "B", "C"), 1)}
    assessments = {pid: assessment() for pid in packets}
    groups = [group("ab", ["A", "B"], "R1"), group("bc", ["B", "C"], "R2")]
    packed = policy.pack_with_joint(packets, assessments, groups, 100, Tok(), render)
    assert set(packed["selected_ids"]) == {"A", "B", "C"}
    assert packed["selected_ids"].count("B") == 1
    assert set(packed["joint_route_ids_selected"]) == {"ab", "bc"}


def test_short_sufficient_packet_beats_redundant_long_joint_group():
    packets = {"A": packet("short", 10),
               "B": packet("long identity context here", page="2"),
               "C": packet("long repeated answer context", page="3")}
    assessments = {"A": assessment("R1", "sufficient", "A:S0"),
                   "B": assessment(), "C": assessment()}
    packed = policy.pack_with_joint(packets, assessments,
        [group("bc", ["B", "C"])], 100, Tok(), render)
    assert packed["selected_ids"] == ["A"]
    assert any(row["id"] == "joint:bc" and row["reason"] == "no_new_requirement_support"
               for row in packed["dropped"])


def test_support_delta_never_calls_a_downgrade_positive_gain():
    before = {"requirements": [{"id": "R1", "status": "sufficient",
        "support_facts": [{"span_ids": ["A:S0"]}]}]}
    after = {"requirements": [{"id": "R1", "status": "partial",
        "support_facts": [{"span_ids": ["B:S0"]}]}]}
    delta = policy.actual_gain(before, after)
    assert not delta["gains"]
    assert delta["regressions"] == [{"requirement_id": "R1",
        "before_status": "sufficient", "after_status": "partial"}]


def test_marginal_validator_skips_repetition_but_cannot_skip_contradiction():
    plan = {"requirements": [{"id": "R1"}]}
    spans = {"P1:S0": {"packet_id": "P1", "text": "new source", "start": 0, "end": 10}}
    repeated = {"requirements": [{"id": "R1", "before_status": "sufficient",
        "after_status": "sufficient", "gain_kind": "repeated_support",
        "necessary_span_ids": [], "reason": "same already sufficient fact"}], "overall": "skip"}
    assert policy.validate_marginal(repeated, plan, spans, ["P1"]) == repeated
    contradiction = {"requirements": [{"id": "R1", "before_status": "sufficient",
        "after_status": "partial", "gain_kind": "contradiction",
        "necessary_span_ids": ["P1:S0"], "reason": "conflicting value"}], "overall": "skip"}
    import pytest
    with pytest.raises(ValueError, match="skip cannot discard"):
        policy.validate_marginal(contradiction, plan, spans, ["P1"])


def test_reachability_and_execution_stats_report_not_exercised_explicitly():
    task = {"question_id": "q", "question": "question", "seed_nodes": ["a"],
            "by_node": {"a": ["P0"], "b": ["P1"]}}
    edges = [{"edge_id": "e", "source_node_id": "a", "target_node_id": "b",
              "relation_description": {"text": "relation"}, "anchors": []}]
    result = {"records": [{"arm": "seed10", "budget": 1024,
        "sufficiency": {"requirements": [{"id": "R1", "status": "sufficient"}],
                        "validation_issues": []}}],
        "trace": [{"hop": 1, "stop": "selected_sources_sufficient"}],
        "validation_issues": []}
    stats = runner.execution_stats(result, task, edges, "navigation_semantic")
    assert stats["navigation_state"] == "not_exercised"
    assert stats["navigation_call_count"] == 0
    assert stats["stop_reason"] == "selected_sources_sufficient"
    diagnostic = runner.reachability(task, edges, stats)
    assert diagnostic["one_hop_new_node_count"] == 1
    assert diagnostic["online_labels"] == ["A_seed_sufficient"]
    assert diagnostic["gold_used"] is False


def test_checkpoint_reachability_is_engine_incomplete_not_key_error():
    task = {"question_id": "q", "question": "question", "seed_nodes": ["a"],
            "by_node": {"a": ["P0"]}}
    diagnostic = runner.reachability(task, [], {"stop_reason": "time_budget", "exception": None})
    assert diagnostic["online_labels"] == ["F_engine_incomplete"]


def test_redundancy_deletion_requires_stable_non_regressing_reaudit():
    full = {"requirements": [{"id": "R1", "status": "sufficient", "exhaustive": True,
        "support_facts": [{"span_ids": ["A:S0"]}], "observations": []}],
        "validation_issues": []}
    same = {"requirements": [{"id": "R1", "status": "sufficient", "exhaustive": True,
        "support_facts": [{"span_ids": ["B:S0"]}], "observations": []}],
        "validation_issues": []}
    assert runner._removal_preserves_support(full, same)[0] is True
    partial = {"requirements": [{**full["requirements"][0], "status": "partial"}],
               "validation_issues": []}
    assert runner._removal_preserves_support(partial, same)[0] is False
    incomplete = {"requirements": [{**same["requirements"][0], "exhaustive": False}],
                  "validation_issues": []}
    assert runner._removal_preserves_support(full, incomplete)[0] is False
