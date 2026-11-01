import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bounded_edge_descriptions as bounded


class CharacterTokenizer:
    def encode(self, text, *, add_special_tokens, truncation):
        assert add_special_tokens is False
        assert truncation is False
        return list(text)


@pytest.fixture
def record():
    return {
        "edge_id": "e1",
        "endpoints": {
            "A": {"document_id": "paper-a", "page_number": "3", "node_type": "TEXT",
                  "spans": [{"span_id": "e1:A:S000", "text": "A uses RMSE in metres.",
                             "source_kind": "ORIGINAL_TEXT"}]},
            "B": {"document_id": "paper-b", "page_number": "7", "node_type": "TEXT",
                  "spans": [{"span_id": "e1:B:S000", "text": "B uses MAPE in percent.",
                             "source_kind": "ORIGINAL_TEXT"}]},
        },
    }


@pytest.fixture
def description():
    return {
        "description": "A: Reports RMSE in metres.\nB: Reports MAPE in percent.\n"
                       "Connection: Both measure error with different definitions.",
        "cited_span_ids": ["e1:A:S000", "e1:B:S000"],
        "limitations": "The units differ; these are not interchangeable metrics.",
        "status": "DESCRIBED",
    }


def test_input_preserves_source_sides_and_provenance(record):
    before = copy.deepcopy(record)
    value = bounded.description_input(record)
    assert value["A"]["document_id"] == "paper-a"
    assert value["B"]["document_id"] == "paper-b"
    assert value["A"]["page_number"] == "3"
    assert value["B"]["source_side"] == "B"
    assert value["A"]["spans"][0]["text"] == "A uses RMSE in metres."
    assert record == before
    prompt = bounded.make_description_prompt(record, "actual length exceeds budget")
    assert "actual length exceeds budget" in prompt
    assert "paper-a" in prompt and "paper-b" in prompt


def test_valid_description_keeps_every_limit_without_modification(record, description):
    expected = description["description"] + "\nLimitations: " + description["limitations"]
    pair = "A original\nB original"
    full = pair + bounded.RELATION_PREFIX + expected
    validated = bounded.validate_encoding_budget(
        description, record, CharacterTokenizer(), [pair, pair[::-1]], max_length=len(full))
    assert validated == description
    assert validated is not description
    assert bounded.render_relation(validated) == expected
    assert "not interchangeable" in bounded.render_relation(validated)


def test_overflow_rejects_instead_of_clipping_limitations(record, description):
    before = copy.deepcopy(description)
    pair = "A original\nB original"
    full = pair + bounded.RELATION_PREFIX + bounded.render_relation(description)
    with pytest.raises(ValueError, match=f"has {len(full)} tokens, limit {len(full) - 1}"):
        bounded.validate_encoding_budget(
            description, record, CharacterTokenizer(), [pair], max_length=len(full) - 1)
    assert description == before
    assert bounded.render_relation(description).endswith(description["limitations"])


def test_both_pair_orders_must_fit(record, description):
    small = "A B"
    larger = "B A with longer metadata"
    limit = len(small + bounded.RELATION_PREFIX + bounded.render_relation(description))
    with pytest.raises(ValueError, match="pair order 1"):
        bounded.validate_encoding_budget(
            description, record, CharacterTokenizer(), [small, larger], max_length=limit)


@pytest.mark.parametrize("value", [None, {"status": "FALLBACK_PAIR", "limitations": "failure"},
                                   {"status": "PENDING"}])
def test_fallback_render_is_exactly_empty(value):
    assert bounded.render_relation(value) == ""


def test_insufficient_render_does_not_encode_missing_evidence_claim(record):
    value = {"description": "", "cited_span_ids": [], "status": "INSUFFICIENT",
             "limitations": "The sources do not establish shared identity."}
    assert bounded.render_relation(value) == ""
    assert bounded.validate_encoding_budget(
        value, record, CharacterTokenizer(), ["AB", "BA"], max_length=2) == value
    with pytest.raises(ValueError, match="alone has 3 tokens, limit 2"):
        bounded.validate_encoding_budget(
            value, record, CharacterTokenizer(), ["ABC"], max_length=2)


def test_unknown_ids_and_missing_side_are_rejected(record, description):
    description["cited_span_ids"] = ["e1:A:S000", "other:B:S000"]
    with pytest.raises(ValueError, match="unknown cited span ID"):
        bounded.validate_description(description, record)
    description["cited_span_ids"] = ["e1:A:S000"]
    with pytest.raises(ValueError, match="both endpoints"):
        bounded.validate_description(description, record)


def test_described_requires_nonempty_limitations(record, description):
    description["limitations"] = "  "
    with pytest.raises(ValueError, match="nonempty limitations"):
        bounded.validate_description(description, record)


@pytest.mark.parametrize("text", [
    "Both nodes discuss metrics.",
    "B: First.\nA: Second.\nConnection: Third.",
    "A: First\nB: Second.\nConnection: Third.",
    "A: .\nB: Second.\nConnection: Third.",
    "A: First.\nB: Second.\nConnection:",
])
def test_source_sections_are_nonempty_complete_statements(record, description, text):
    description["description"] = text
    with pytest.raises(ValueError):
        bounded.validate_description(description, record)
