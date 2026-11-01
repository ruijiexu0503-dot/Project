import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import query_semantic_edge_core as core
import query_semantic_edge_policy as policy
import run_query_semantic_edge_v1 as runner
import run_span_evidence_selection as spans
from build_reader_anchor_ablation import sha


class Shape:
    def __init__(self, *shape): self.shape = shape


class Batch(dict):
    pass


def plan():
    return {"requirements": [{"id": "R1", "request": "2019 rate", "kind": "scalar",
                               "constraints": ["2019"]}]}


def test_token_count_uses_input_ids_for_mapping_tensor_list_and_batch():
    assert core.token_count([1, 2, 3]) == 3
    assert core.token_count([[1, 2, 3], [4, 5, 6]]) == 3
    assert core.token_count(Batch(input_ids=Shape(1, 17), attention_mask=Shape(1, 17))) == 17
    with pytest.raises(ValueError, match="ragged"):
        core.token_count([[1], [1, 2]])
    with pytest.raises(ValueError, match="input_ids"):
        core.token_count({"attention_mask": [1, 1]})


def test_chat_count_matches_render_then_tokenize_not_mapping_length():
    class Tok:
        def apply_chat_template(self, messages, tokenize=False, **kwargs):
            assert not tokenize
            return "one two three four"
        def __call__(self, texts, **kwargs):
            return {"input_ids": [[1, 2, 3, 4]], "attention_mask": [[1, 1, 1, 1]]}
    assert core.chat_prompt_token_count(Tok(), [{"role": "user", "content": "x"}]) == 4


def test_missing_may_have_observations_but_no_support_gain():
    source = spans.spans("P0", "The study covers the period, but gives no annual rate.")
    observation = {"meaning": "period background only", "span_ids": [next(iter(source))]}
    raw = {"requirements": [{"id": "R1", "status": "missing", "validation_state": "valid",
        "exhaustive": False, "support_facts": [], "observations": [observation],
        "missing": ["2019 value"]}]}
    assert policy.validate_assessment(raw, plan(), "P0", source) == raw
    packet = {"P0": {"text": "background", "page": ["d", "1"], "member_sha256": "x",
                       "base_score": 1}}
    class Tok:
        def encode(self, text, add_special_tokens=False): return text.split()
    packed = policy.pack(packet, {"P0": raw}, 20, Tok(), lambda values: " ".join(x["text"] for x in values))
    assert packed["selected_ids"] == []
    bad = copy.deepcopy(raw); bad["requirements"][0]["support_facts"] = [observation]
    with pytest.raises(ValueError, match="missing"):
        policy.validate_assessment(bad, plan(), "P0", source)


def test_partial_without_support_is_conservatively_missing_not_protocol_failure():
    source = spans.spans("P0", "Federer won three of four Grand Slams in 2004.")
    raw = {"requirements": [{"id": "R1", "status": "partial", "validation_state": "valid",
        "exhaustive": False, "support_facts": [], "observations": [{"meaning": "count but no names",
        "span_ids": [next(iter(source))]}], "missing": ["tournament names"]}]}
    result = policy.partition_requirements(raw, plan(),
        lambda value, subplan: policy.validate_assessment(value, subplan, "P0", source))
    assert not result["validation_issues"]
    assert result["requirements"][0]["status"] == "missing"
    assert result["requirements"][0]["observations"] == raw["requirements"][0]["observations"]
    assert "partial without positive support" in result["normalizations"][0]["reason"]
    assert raw["requirements"][0]["status"] == "partial"  # raw output remains immutable


def test_string_absence_observation_is_normalized_without_support():
    raw = {"requirements": [{"id": "R1", "status": "missing", "validation_state": "valid",
        "exhaustive": False, "support_facts": [],
        "observations": ["No 2019 result is present."], "missing": ["2019 result"]}]}
    result = policy.partition_requirements(raw, plan(),
        lambda value, subplan: policy.validate_verdict(value, subplan, {}), True)
    assert not result["validation_issues"]
    assert result["requirements"][0]["observations"] == [
        {"meaning": "No 2019 result is present.", "span_ids": []}]
    assert "string observations normalized" in result["normalizations"][0]["reason"]


def test_partial_support_is_preserved_when_missing_detail_is_in_observation():
    source = spans.spans("P0", "Federer won Wimbledon and the US Open in 2005.")
    sid = next(iter(source))
    raw = {"requirements": [{"id": "R1", "status": "partial", "validation_state": "valid",
        "exhaustive": False, "support_facts": [{"meaning": "two named wins", "span_ids": [sid]}],
        "observations": [{"meaning": "Completeness of the set is not established.", "span_ids": [sid]}],
        "missing": []}]}
    result = policy.partition_requirements(raw, plan(),
        lambda value, subplan: policy.validate_assessment(value, subplan, "P0", source))
    row = result["requirements"][0]
    assert not result["validation_issues"]
    assert row["status"] == "partial" and row["support_facts"] == raw["requirements"][0]["support_facts"]
    assert row["missing"] == ["Completeness of the set is not established."]
    assert "grounded support preserved" in result["normalizations"][0]["reason"]


def test_validation_failure_is_unknown_not_missing():
    result = policy.partition_requirements({"requirements": [{"id": "R1", "bad": True}]}, plan(),
        lambda value, subplan: policy.validate_assessment(value, subplan, "P0", spans.spans("P0", "source")))
    row = result["requirements"][0]
    assert row["status"] == "unknown" and row["validation_state"] == "unknown"
    assert row["support_facts"] == [] and result["validation_issues"]


def test_route_requires_grounded_edge_anchor_and_explicit_gain():
    route = {"id": "H1:e:a", "edge": {"anchors": [{"span_id": "e:A:S000"}]}}
    missing = [{"id": "R1", "status": "missing"}]
    valid = {"routes": [{"id": route["id"], "follow": True, "requirements": ["R1"],
        "expected_gain": "bridge", "source_anchor_ids": ["e:A:S000"],
        "constraint_checks": ["same subject; year still unknown"], "reason": "bounded bridge",
        "uncertainty": "target may still lack the value"}]}
    assert policy.validate_routes(valid, [route], missing) == valid
    bad = copy.deepcopy(valid); bad["routes"][0]["source_anchor_ids"] = ["invented"]
    with pytest.raises(ValueError, match=r"allowed=.*e:A:S000"):
        policy.validate_routes(bad, [route], missing)


def test_endpoint_ablation_hides_description_without_changing_graph_or_anchors():
    edge = {"edge_id": "e", "source_node_id": "a", "target_node_id": "b",
            "relation_description": {"status": "DESCRIBED", "text": "semantic relation",
                                     "limitations": "", "provenance": "offline"},
            "description_metadata": {"profile": "p"}, "anchors": [{"span_id": "e:A:S0"}]}
    semantic = policy.configure_edges([edge], "navigation_semantic")[0]
    endpoint = policy.configure_edges([edge], "navigation_endpoint")[0]
    assert semantic["relation_description"]["text"] == "semantic relation"
    assert endpoint["relation_description"]["text"] == ""
    assert endpoint["relation_description"]["status"] == "ENDPOINT_ONLY_CONTROL"
    assert "anchors remain available" in endpoint["relation_description"]["limitations"]
    assert endpoint["anchors"] == semantic["anchors"]
    assert (endpoint["source_node_id"], endpoint["target_node_id"]) == ("a", "b")
    assert edge["relation_description"]["text"] == "semantic relation"  # input stays immutable


def test_real_legacy_descriptions_are_attached_and_covered():
    root = Path(__file__).resolve().parents[2] / "migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics"
    edges, coverage = core.load_described_edges(root / "edge_records.jsonl", root / "description_predictions.jsonl")
    assert coverage["total"] == 187 and coverage["described"] == 186
    assert coverage["insufficient"] == 1 and coverage["fallback_pair"] == 0
    assert all(e["relation_description"]["status"] != "PENDING" for e in edges)
    described = next(e for e in edges if e["relation_description"]["status"] == "DESCRIBED")
    card = core.edge_card(described)
    assert card["relation_description"]["text"] and card["anchors"][0]["span_id"]


def test_description_loader_rejects_stale_hash_and_duplicates(tmp_path):
    root = Path(__file__).resolve().parents[2] / "migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics"
    record = json.loads((root / "edge_records.jsonl").read_text().splitlines()[0])
    prediction = next(json.loads(x) for x in (root / "description_predictions.jsonl").read_text().splitlines()
                      if json.loads(x)["edge_id"] == record["edge_id"])
    records = tmp_path / "records.jsonl"; predictions = tmp_path / "predictions.jsonl"
    records.write_text(json.dumps(record) + "\n")
    stale = copy.deepcopy(prediction); stale["input_sha256"] = "0" * 64
    predictions.write_text(json.dumps(stale) + "\n")
    with pytest.raises(ValueError, match="stale"):
        core.load_described_edges(records, predictions)
    predictions.write_text(json.dumps(prediction) + "\n" + json.dumps(prediction) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        core.load_described_edges(records, predictions)
    unavailable = copy.deepcopy(prediction); unavailable["valid"] = False; unavailable["result"] = None
    predictions.write_text(json.dumps(unavailable) + "\n")
    with pytest.raises(ValueError, match="requires at least one"):
        core.load_described_edges(records, predictions)
    damaged = copy.deepcopy(record); damaged["endpoints"]["A"]["spans"][0]["char_end"] += 1
    records.write_text(json.dumps(damaged) + "\n"); predictions.write_text(json.dumps(prediction) + "\n")
    with pytest.raises(ValueError, match="input hash mismatch"):
        core.load_described_edges(records, predictions)


def test_prompt_limit_uses_real_input_ids_and_blocks_generation(tmp_path):
    class Tok:
        def apply_chat_template(self, messages, tokenize=False, **kwargs): return "rendered"
        def __call__(self, texts, **kwargs): return {"input_ids": Shape(1, 24577), "attention_mask": Shape(1, 24577)}
        def encode(self, text, add_special_tokens=False): return []
    class LLM:
        calls = 0
        def generate_raw_with_images(self, *args): self.calls += 1; raise AssertionError("must not generate")
    llm = LLM(); broker = runner.legacy.Broker(tmp_path, "model", 1, Tok(), llm)
    with pytest.raises(runner.legacy.InvalidOutput, match="over limit"):
        broker.call("q", "plan", "instruction", {}, lambda value: value)
    assert llm.calls == 0


def test_joint_support_selects_both_original_packets_atomically():
    packets = {
        "P0": {"text": "The table is for A2063G.", "page": ["d", "1"], "member_sha256": "a", "base_score": 2},
        "P1": {"text": "2019 rate: 75.2%.", "page": ["d", "2"], "member_sha256": "b", "base_score": 1},
    }
    source = {**spans.spans("P0", packets["P0"]["text"]), **spans.spans("P1", packets["P1"]["text"])}
    ids = list(source)
    verdict = {"requirements": [{"id": "R1", "status": "sufficient", "validation_state": "valid",
        "exhaustive": False, "support_facts": [{"meaning": "identity plus value", "span_ids": ids}],
        "observations": [], "missing": []}]}
    group = policy.joint_group(verdict, source,
        {"id": "H1:e:a", "source_node": "a", "target_node": "b"})
    assert group["packet_ids"] == ["P0", "P1"]
    missing = {pid: {"requirements": [{"id": "R1", "status": "missing", "validation_state": "valid",
        "exhaustive": False, "support_facts": [], "observations": [], "missing": ["other source"]}]}
        for pid in packets}
    class Tok:
        def encode(self, text, add_special_tokens=False): return text.split()
    packed = policy.pack_with_joint(packets, missing, [group], 100, Tok(),
                                    lambda values: " ".join(x["text"] for x in values))
    assert packed["selected_ids"] == ["P0", "P1"]
    assert packed["joint_route_ids_selected"] == ["H1:e:a"]
    tight = policy.pack_with_joint(packets, missing, [group], 1, Tok(),
                                   lambda values: " ".join(x["text"] for x in values))
    assert tight["selected_ids"] == [] and tight["dropped"][0]["reason"] == "joint_group_over_budget"


def test_rank10_style_bridge_continues_and_joint_arm_keeps_context():
    def packet(pid, node, text, rank):
        return {"packet_id": pid, "node_id": node, "member_id": pid, "text": text,
                "page": ["doc", str(rank)], "member_sha256": sha(text),
                "base_score": -rank, "initial_node_rank": rank}
    packets = {"P0": packet("P0", "a", "initial background", 10),
               "P1": packet("P1", "b", "A2063G identity context", 20),
               "P2": packet("P2", "c", "2019 rate 75.2 percent", 30)}
    source = {sid: row for pid, value in packets.items() for sid, row in spans.spans(pid, value["text"]).items()}
    task = {"question_id": "q", "question": "What was the A2063G 2019 rate?", "packets": packets,
            "source_spans": source, "documents": {p: "D1" for p in packets},
            "seed_nodes": ["a"], "node_ranking": ["a", "b", "c"],
            "by_node": {"a": ["P0"], "b": ["P1"], "c": ["P2"]}}
    edges = []
    for edge_id, a, b in (("ab", "a", "b"), ("bc", "b", "c")):
        edges.append({"edge_id": edge_id, "source_node_id": a, "target_node_id": b,
            "relation_description": {"status": "DESCRIBED", "text": "bounded bridge", "limitations": ""},
            "anchors": [{"span_id": edge_id + ":A:S000", "node_id": a}]})

    class Tok:
        def encode(self, text, add_special_tokens=False): return text.split()

    class Broker:
        tok = Tok()
        def call(self, qid, phase, instruction, payload, validator, max_tokens=8192):
            if phase == "query_plan": value = plan()
            elif phase == "query_plan_review":
                value = {"decisions": [{"id": "R1", "keep": True, "reason": "explicitly requested"}]}
            elif phase == "assessment":
                pid = payload["packet"]["id"]
                if pid == "P2":
                    value = {"requirements": [{"id": "R1", "status": "partial", "validation_state": "valid",
                        "exhaustive": False, "support_facts": [{"meaning": "rate without identity context",
                        "span_ids": ["P2:S0000"]}], "observations": [], "missing": ["subject identity"]}]}
                else:
                    value = {"requirements": [{"id": "R1", "status": "missing", "validation_state": "valid",
                        "exhaustive": False, "support_facts": [], "observations": [{"meaning": "navigation context",
                        "span_ids": [pid + ":S0000"]}], "missing": ["grounded value"]}]}
            elif phase == "navigation":
                assert all(route["edge"]["relation_description"]["text"] == "bounded bridge"
                           for route in payload["routes"])
                value = {"routes": [{"id": route["id"], "follow": True, "requirements": ["R1"],
                    "expected_gain": "bridge" if route["target_node"] == "b" else "direct_evidence",
                    "source_anchor_ids": [route["edge"]["anchors"][0]["span_id"]],
                    "constraint_checks": ["same A2063G route"], "reason": "seek missing evidence",
                    "uncertainty": "must inspect original target"} for route in payload["routes"]]}
            else:
                ids = {p["id"] for p in payload["packets"]}
                joint = {"P1", "P2"} <= ids
                partial = "P2" in ids
                facts = ([{"meaning": "identity and value jointly supported", "span_ids": ["P1:S0000", "P2:S0000"]}]
                         if joint else ([{"meaning": "value only", "span_ids": ["P2:S0000"]}] if partial else []))
                value = {"requirements": [{"id": "R1", "status": "sufficient" if joint else ("partial" if partial else "missing"),
                    "validation_state": "valid", "exhaustive": False, "support_facts": facts,
                    "observations": [], "missing": [] if joint else ["subject identity" if partial else "value"]}]}
            return validator(value)

    result = runner.run_task(task, edges, "navigation", Broker())
    assert result["trace"][0]["followed"][0]["source_node"] == "a"
    assert result["trace"][1]["followed"][0]["target_node"] == "c"
    assert result["trace"][1]["route_joint_audits"][0]["joint_group"]["packet_ids"] == ["P1", "P2"]
    ordinary = [r for r in result["records"] if r["arm"] == "graph_adaptive" and r["budget"] == 512][0]
    joint = [r for r in result["records"] if r["arm"] == "graph_adaptive_joint" and r["budget"] == 512][0]
    assert ordinary["selected_ids"] == ["P2"]
    assert joint["selected_ids"] == ["P1", "P2"] and joint["joint_route_ids_selected"] == ["H2:bc:b"]
