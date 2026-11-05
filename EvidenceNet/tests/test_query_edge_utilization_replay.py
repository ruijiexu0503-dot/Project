import pytest

from EvidenceNet.scripts.prepare_query_edge_utilization_replay import (
    feature_record, order_key, route_record, select_arm, state_conditioned_action,
    validate_evidence_state,
)


def route(eligibility="unknown", source="a", target="b", source_quote="director election withheld",
          target_quote="nominee authority", direction="A_TO_B"):
    anchor = lambda side, node, quote: {"anchor_id": side, "node_id": node, "quote": quote,
        "localizable": True, "member_id": side, "char_start": 0, "char_end": len(quote),
        "member_sha256": "x", "boxes": [], "kind": "ORIGINAL_TEXT", "granularity": "span_window",
        "localization_reasons": [], "side": side}
    return route_record("e", "g", source, target, direction, "RELATED",
                        [anchor("A", source, source_quote)], [anchor("B", target, target_quote)],
                        eligibility, "test", [{"source": "test"}], "director nominee relation")


def item(value, query="director election withheld authority"):
    return {"question_id": "q", "question": query, "route": value, "source_dense_rank": 1,
            "target_dense_rank": 30, "target_page": ["d", 1],
            "features": feature_record(query, value, .5)}


def test_direction_specific_anchors_switch_and_directed_route_does_not_imply_reverse():
    forward = route(source="a", target="b")
    reverse = route(source="b", target="a", direction="B_TO_A")
    assert forward["source_anchors"][0]["node_id"] == "a"
    assert reverse["source_anchors"][0]["node_id"] == "b"
    assert forward["direction"] == "A_TO_B" and reverse["direction"] == "B_TO_A"


def test_denied_route_rejects_even_if_anchor_matches():
    value = item(route("denied"))
    selected, decisions, _ = select_arm("R2_anchor_proxy", [value], set())
    assert not selected and decisions[0]["reason"] == "eligibility_denied"


def test_mixed_topic_anchor_does_not_activate_from_whole_node_topic():
    value = route(source_quote="ratification independent accounting firm abstentions",
                  target_quote="KPMG auditor ratification")
    features = feature_record("director election authority withheld nominees", value, .8)
    assert not features["anchor_proxy_applicable"]


def test_coarse_table_window_cannot_pass_as_precise_row_anchor():
    value = route(source_quote="director election withheld auditor ratification",
                  target_quote="director nominee authority")
    value["source_anchors"][0]["granularity"] = "coarse_or_unknown"
    features = feature_record("director election authority withheld nominees", value, .8)
    assert features["query_source_anchor_terms"]
    assert not features["source_anchor_precision_ok"]
    assert not features["anchor_proxy_applicable"]


def test_target_in_dense20_is_link_existing_not_new_recall():
    value = item(route())
    selected, decisions, ledger = select_arm("R2_anchor_proxy", [value], {"b"})
    assert selected and decisions[0]["action"] == "link_existing"
    assert ledger["new_targets_outside_dense20"] == 0


def test_no_route_abstains_as_no_usable_route_not_sufficient():
    _, _, ledger = select_arm("R1_static", [], set())
    assert ledger["stop_reason"] == "no_usable_route"


def test_equal_features_do_not_receive_numeric_id_bonus():
    left, right = item(route(source="a", target="b")), item(route(source="a", target="c"))
    left["features"] = right["features"] = {**left["features"], "query_target_score": .5}
    assert order_key("R2_target_only", left)[0] == order_key("R2_target_only", right)[0]


def test_state_counterfactual_changes_action_and_consistency_is_enforced():
    assert state_conditioned_action("missing", True) == "inspect"
    assert state_conditioned_action("sufficient", True) == "reject_redundant"
    validate_evidence_state({"requirements": [{"status": "sufficient", "support_span_ids": ["s"],
        "missing_slots": [], "unresolved_constraints": []}]})
    with pytest.raises(ValueError):
        validate_evidence_state({"requirements": [{"status": "sufficient", "support_span_ids": ["s"],
            "missing_slots": ["condition"], "unresolved_constraints": []}]})


def test_unknown_never_becomes_admitted():
    value = item(route("unknown"))
    _, decisions, _ = select_arm("R2_anchor_proxy", [value], set())
    assert decisions[0]["action"] == "inspect" and decisions[0]["admitted"] is False
