import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import encode_directional_relation_views as enc
import prepare_directional_relation_views as prep
import run_directional_relation_retrieval as run


def _record():
    return {"edge_id": "e", "endpoints": {
        "A": {"node_id": "a", "document_id": "d1", "page_number": "1",
              "spans": [{"span_id": "a1", "text": "measurement in 2004"}]},
        "B": {"node_id": "b", "document_id": "d2", "page_number": "2",
              "spans": [{"span_id": "b1", "text": "different result in 2005"}]}}}


def _legacy():
    return {"task_id": "e", "status": "MODEL_PROPOSED_NOT_HUMAN_VERIFIED",
            "model_result": {"basis": "CLAIM_CORRESPONDENCE",
                             "matched_claim": "The passages concern results in different years.",
                             "limitation": "Do not merge 2004 with 2005."}}


def test_reverse_direction_swaps_contributions_and_keeps_year_qualifier():
    forward = prep.build_direction(_record(), _legacy(), "A")
    reverse = prep.build_direction(_record(), _legacy(), "B")
    assert forward["known_source_contribution"] == "measurement in 2004"
    assert forward["target_contribution"] == "different result in 2005"
    assert reverse["known_source_contribution"] == "different result in 2005"
    assert reverse["target_contribution"] == "measurement in 2004"
    assert "Do not merge 2004 with 2005" in reverse["directional_retrieval_text"]
    assert forward["verifier_status"] != "verified"


def test_route_enumeration_includes_rank10_and_only_real_outgoing_adjacency():
    views = [
        {"view_id": "e:A_to_B", "edge_id": "e", "source_node_id": "s10", "target_node_id": "t",
         "source_page": ["d", "1"], "target_page": ["d", "2"], "status": "proposal"},
        {"view_id": "x:A_to_B", "edge_id": "x", "source_node_id": "not-seed", "target_node_id": "z",
         "source_page": ["d", "3"], "target_page": ["d", "4"], "status": "proposal"},
    ]
    routes = run.enumerate_routes([f"s{i}" for i in range(1, 11)], views, np.array([0.2, 0.9]))
    assert len(routes) == 1 and routes[0]["seed_rank"] == 10
    assert routes[0]["target_node_id"] == "t"


def test_zero_adjacency_and_duplicate_targets_are_deterministic():
    assert run.enumerate_routes(["s"], [], np.array([])) == []
    routes = [
        {"target_node_id": "t", "score": 0.8, "seed_rank": 1, "edge_id": "a", "status": "proposal"},
        {"target_node_id": "t", "score": 0.7, "seed_rank": 2, "edge_id": "b", "status": "proposal"},
    ]
    selected, decisions = run.select_targets(routes, ["s"], 5)
    assert selected == ["t"]
    assert [row["decision"] for row in decisions] == ["selected", "seed_or_duplicate_target"]


class _Tokenizer:
    def encode(self, text, **kwargs): return list(range(len(text.split())))
    def decode(self, ids, **kwargs): return " ".join("x" for _ in ids)


def test_matched_rendering_never_exceeds_budget():
    view = prep.build_direction(_record(), _legacy(), "A")
    view["known_source_contribution"] = "s " * 800
    view["target_contribution"] = "t " * 800
    for arm in enc.ARMS:
        text, meta = enc.render(view, arm, _Tokenizer())
        assert len(text.split()) <= 512
        assert meta
