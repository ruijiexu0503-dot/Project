import copy
import hashlib
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from edge_granularity_views import ARMS, context_for_view, make_views, top_matches
from run_hierarchical_edge_retrieval import clean


def corpus(raw):
    return {"n": {"id": "n", "members": [
        {"id": "m", "kind": "atom", "type": "text", "text": raw},
        {"id": "other", "kind": "atom", "type": "text", "text": "Unselected member."},
    ]}}


def views(raw, arm):
    return make_views(corpus(raw), {("n", "m")}, arm)


def assert_coverage(raw, records):
    covered = set()
    for record in records:
        start, end = record["char_start"], record["char_end"]
        assert record["quote"] == raw[start:end] == raw[start:end].strip()
        assert record["member_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
        assert record["retrieval_text"] == clean(raw[start:end])
        assert record["word_count"] == len(record["retrieval_text"].split())
        covered.update(range(start, end))
    assert all(i in covered or char.isspace() for i, char in enumerate(raw))


@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_source_coverage_short_negation_and_immutable_sources(arm, newline):
    raw = f"  The method did{newline} not{newline}use spatial information.{newline}{newline}Yes.  "
    nodes = corpus(raw)
    original = copy.deepcopy(nodes)
    result = make_views(nodes, {("n", "m")}, arm)
    assert_coverage(raw, result)
    assert nodes == original
    assert {r["member_id"] for r in result} == {"m"}
    if arm == "physical_line":
        assert [r["quote"] for r in result] == ["The method did", "not", "use spatial information.", "Yes."]
        assert result[1]["word_count"] == 1
    if arm == "sentence":
        assert result[0]["quote"] == f"The method did{newline} not{newline}use spatial information."


@pytest.mark.parametrize("arm", ARMS)
def test_empty_source_and_single_word_are_not_minimum_word_filtered(arm):
    assert views("\r\n \t\r\n", arm) == []
    assert [v["quote"] for v in views(" no ", arm)] == ["no"]


def test_window96_stride72_exact_offsets_and_full_tail():
    raw = " \t" + "\r\n".join(f"word{i}" for i in range(215)) + "  "
    result = views(raw, "window96")
    assert [r["quote"].split()[0] for r in result] == ["word0", "word72", "word144"]
    assert [r["quote"].split()[-1] for r in result] == ["word95", "word167", "word214"]
    assert [r["word_count"] for r in result] == [96, 96, 71]
    assert_coverage(raw, result)


def test_sentence_abbreviations_and_whole_multiline_math():
    formula = "$$x = 1.\r\n\r\ny = 2. " + "z + " * 230 + "w$$"
    first = "See Fig. 2 and Dr. Smith for details."
    second = "The formula is " + formula + "."
    raw = first + "\r\n" + second + " A final claim."
    result = views(raw, "sentence")
    assert [v["quote"] for v in result] == [first, second, "A final claim."]
    assert_coverage(raw, result)


def test_all_arms_share_the_renderer_and_raw_hyphen_anchor():
    raw = "The spatio-\ntemporal model works."
    for arm in ("window96", "sentence"):
        result = views(raw, arm)
        assert result[0]["quote"] == raw
        assert result[0]["retrieval_text"] == "The spatiotemporal model works."
    for record in views(raw, "physical_line"):
        assert record["retrieval_text"] == clean(record["quote"])


def test_ids_are_deterministic_include_arm_owner_offsets_and_source_hash():
    raw = "One sentence."
    originals = {arm: views(raw, arm)[0]["view_id"] for arm in ARMS}
    assert len(set(originals.values())) == 3
    assert views(raw, "window96")[0]["view_id"] == originals["window96"]
    assert views("Two sentence.", "window96")[0]["view_id"] != originals["window96"]
    nodes = corpus(raw)
    nodes["n"]["members"][1]["text"] = raw
    both = make_views(nodes, {("n", "other"), ("n", "m")}, "window96")
    assert len({v["view_id"] for v in both}) == 2
    assert [v["member_id"] for v in both] == ["m", "other"]


def test_selected_members_are_checked_not_silently_ignored():
    nodes = corpus("Text.")
    with pytest.raises(ValueError, match="Unknown"):
        make_views(nodes, {("n", "m")}, "paragraph")
    with pytest.raises(ValueError, match="one source member"):
        make_views(nodes, {("n", "missing")}, "sentence")
    nodes["n"]["members"][0]["kind"] = "visual"
    with pytest.raises(ValueError, match="atom/text"):
        make_views(nodes, {("n", "m")}, "sentence")


def test_context_completes_negation_sentence_then_adds_one_neighbor_each_side():
    raw = "Outside start. Previous claim. The method did\r\nnot\r\nuse spatial information. Next claim. Outside end."
    nodes = corpus(raw)
    line = next(v for v in make_views(nodes, {("n", "m")}, "physical_line") if v["quote"] == "not")
    anchor = context_for_view(line, nodes)
    assert anchor["quote"] == "Previous claim. The method did\r\nnot\r\nuse spatial information. Next claim."
    assert anchor["kind"] == "ORIGINAL_TEXT"
    assert anchor["quote"] == raw[anchor["char_start"]:anchor["char_end"]]
    assert "Unselected member" not in anchor["quote"]


def test_context_covers_multiple_touched_sentences_without_cutting_math():
    formula = "$$x = 1.\n\ny = 2. " + "z + " * 230 + "w$$"
    raw = "First claim. The formula is " + formula + ". Last claim."
    nodes = corpus(raw)
    line = next(v for v in make_views(nodes, {("n", "m")}, "physical_line") if v["quote"].startswith("y ="))
    anchor = context_for_view(line, nodes)
    assert anchor["quote"] == raw
    assert len(anchor["quote"]) > 800
    for view in make_views(nodes, {("n", "m")}, "window96"):
        context = context_for_view(view, nodes)
        assert context["char_start"] <= view["char_start"] < view["char_end"] <= context["char_end"]
        assert formula in context["quote"]


def test_context_boundaries_tamper_checks_and_no_mutation():
    raw = "First. Second. Third. Fourth."
    nodes = corpus(raw)
    original = copy.deepcopy(nodes)
    records = make_views(nodes, {("n", "m")}, "sentence")
    assert context_for_view(records[0], nodes)["quote"] == "First. Second."
    assert context_for_view(records[-1], nodes)["quote"] == "Third. Fourth."
    assert nodes == original
    bad = dict(records[0], quote="Wrong.")
    with pytest.raises(ValueError, match="immutable"):
        context_for_view(bad, nodes)
    nodes["n"]["members"][0]["text"] = raw + " Changed."
    with pytest.raises(ValueError, match="immutable"):
        context_for_view(records[0], nodes)


def span(vid, node, lo=0, hi=10, member="m"):
    return {"view_id": vid, "node_id": node, "member_id": member,
            "char_start": lo, "char_end": hi}


def vectors(*records):
    return {r["view_id"]: np.array([1.0, 0.0]) for r in records}


def test_top_matches_rejects_two_sided_overlap_but_preserves_one_to_many():
    a = [span("a0", "a", 0, 10), span("a1", "a", 5, 15)]
    b = [span("b0", "b", 0, 10), span("b1", "b", 5, 15), span("b2", "b", 15, 25)]
    result = top_matches(a, b, vectors(*a, *b), limit=3)
    assert [(r["A_view_id"], r["B_view_id"]) for r in result] == [("a0", "b0"), ("a0", "b2")]
    assert all(r["score"] == 1.0 for r in result)


def test_top_matches_half_shorter_span_threshold_and_owner_scope():
    a = [span("a0", "a", 0, 100), span("a1", "a", 99, 101), span("a2", "a", 99, 101, "different")]
    b = [span("b0", "b")]
    result = top_matches(a, b, vectors(*a, *b), limit=3)
    assert [r["A_view_id"] for r in result] == ["a0", "a2"]


def test_top_matches_scores_then_ids_stably_and_never_mutates():
    a = [span("a1", "a", 10, 20), span("a0", "a", 0, 10)]
    b = [span("b1", "b", 10, 20), span("b0", "b", 0, 10)]
    data = vectors(*a, *b)
    data["b0"] = np.array([0.0, 1.0])
    saved = copy.deepcopy((a, b, data))
    result = top_matches(a, b, data)
    assert [(r["A_view_id"], r["B_view_id"]) for r in result] == [("a0", "b1"), ("a1", "b1")]
    assert result == top_matches(list(reversed(a)), list(reversed(b)), data)
    assert a == saved[0] and b == saved[1]
    assert all(np.array_equal(data[key], saved[2][key]) for key in data)


@pytest.mark.parametrize("bad", [np.array([0.0, 0.0]), np.array([np.nan, 1.0]), np.array([[1.0, 0.0]]), np.array([2.0, 0.0])])
def test_top_matches_rejects_invalid_vectors(bad):
    a, b = span("a", "a"), span("b", "b")
    with pytest.raises(ValueError):
        top_matches([a], [b], {"a": bad, "b": np.array([1.0, 0.0])})


def test_top_matches_empty_limits_dimensions_and_duplicate_ids():
    a, b = span("a", "a"), span("b", "b")
    assert top_matches([], [b], {}) == []
    assert top_matches([a], [b], {}, limit=0) == []
    with pytest.raises(ValueError):
        top_matches([a], [b], {}, limit=-1)
    with pytest.raises(ValueError, match="dimensions"):
        top_matches([a], [b], {"a": np.array([1.0, 0.0]), "b": np.array([1.0])})
    with pytest.raises(ValueError, match="Duplicate"):
        top_matches([a, a], [b], vectors(a, b))
