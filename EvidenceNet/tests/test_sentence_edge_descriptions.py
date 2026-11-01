import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sentence_edge_descriptions as sentence
import edge_embedding_records as records
import run_vldocir_edge_embedding as experiment
from test_edge_embedding_records import fixture
from test_bounded_edge_descriptions import CharacterTokenizer
from test_vldocir_edge_embedding import WordTokenizer


def sample():
    edge, nodes = fixture()
    record = records.build_record(edge, nodes, "semantic")
    value = {"description": "Both use a 0.01 step, but not the same simulation.",
             "limitations": "Different subjects; shared study identity is not established.",
             "cited_span_ids": ["e1:A:S000", "e1:B:S000"], "status": "DESCRIBED"}
    return record, value


def test_normalize_layout_without_changing_science_or_source():
    record, value = sample()
    value["description"] = "Both use\n a 0.01 step, but\t not the same simulation."
    before = copy.deepcopy(value)
    result = sentence.validate_description(value, record)
    assert result["description"] == "Both use a 0.01 step, but not the same simulation."
    assert value == before
    assert result["limitations"] == value["limitations"]


def test_sentence_is_prompt_instruction_not_brittle_punctuation_gate():
    record, value = sample()
    value["description"] = "Both cite J. Smith et al. but refer to different trials."
    assert sentence.validate_description(value, record)["description"] == value["description"]
    prompt = sentence.make_description_prompt(record)
    assert "ONE concise sentence" in prompt
    assert "exactly three" not in prompt
    assert "qrels" not in prompt.lower()


def test_preserve_full_limits_and_both_order_budgets():
    record, value = sample()
    text = "AB" + "\n\n[RELATION]\n" + sentence.render_relation(value)
    assert sentence.validate_encoding_budget(value, record, CharacterTokenizer(), ["AB"], len(text)) == value
    with pytest.raises(ValueError, match="pair order 1"):
        sentence.validate_encoding_budget(value, record, CharacterTokenizer(), ["AB", "B long A"], len(text))


@pytest.mark.parametrize("mutation", ["unknown_id", "one_side", "empty_limits", "insufficient_text"])
def test_reject_bad_provenance_and_scope(mutation):
    record, value = sample()
    if mutation == "unknown_id": value["cited_span_ids"] = ["e1:A:S000", "missing"]
    if mutation == "one_side": value["cited_span_ids"] = ["e1:A:S000"]
    if mutation == "empty_limits": value["limitations"] = " "
    if mutation == "insufficient_text": value.update(status="INSUFFICIENT", cited_span_ids=[])
    with pytest.raises(ValueError): sentence.validate_description(value, record)


@pytest.mark.parametrize("status", ["DESCRIBED", "INSUFFICIENT", "invalid"])
def test_encoding_keeps_matched_endpoints_and_exact_fallback(tmp_path, status):
    record, result = sample()
    if status == "INSUFFICIENT": result.update(status=status, description="", cited_span_ids=[])
    if status == "invalid": result = None
    experiment.write(tmp_path / "protocol.json", {"description": {"policy": sentence.PROFILE}})
    experiment.jsonl(tmp_path / "edge_records.jsonl", [record])
    experiment.jsonl(tmp_path / "description_predictions.jsonl", [{
        "edge_id": record["edge_id"], "input_sha256": record["input_sha256"],
        "description_policy": sentence.PROFILE,
        "prompt_sha256": records.digest(sentence.make_description_prompt(record)),
        "valid": status != "invalid", "result": result, "attempts": []}])
    pair, relation, _ = experiment._encoding_rows(tmp_path, WordTokenizer())
    assert [x["endpoint_text_sha256"] for x in pair] == [x["endpoint_text_sha256"] for x in relation]
    if status == "DESCRIBED":
        assert all(result["limitations"] in x["text"] for x in relation)
        assert all(not x["relation_token_meta"]["truncated"] for x in relation)
    else:
        assert [x["text"] for x in pair] == [x["text"] for x in relation]


def test_prepare_sentence_real_graph_is_same_187_edges_24_queries(tmp_path):
    baseline, new = tmp_path / "baseline", tmp_path / "sentence"
    experiment.prepare(baseline, experiment.MODEL, description_policy="bounded-v2")
    assert experiment.prepare(new, experiment.MODEL, description_policy=sentence.PROFILE) == {
        "prepared": True, "edges": 187, "queries": 24}
    for name in ("edge_records.jsonl", "queries.jsonl"):
        assert (baseline / name).read_bytes() == (new / name).read_bytes()
    experiment.check_prepared(new)
