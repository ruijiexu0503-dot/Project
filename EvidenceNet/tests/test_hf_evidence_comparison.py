import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_hf_evidence_comparison as hf


def test_score_ranking_has_fixed_tie_break_and_complete_pages():
    corpus = {("d", "1"), ("d", "2"), ("a", "10")}
    scores = [
        {"question_id": "q", "document_id": p[0], "page_number": p[1], "score": score}
        for p, score in [(('d', '2'), 1), (('d', '1'), 1), (('a', '10'), 2)]]
    ranking = hf._score_rankings(scores, corpus)["q"]
    assert ranking == [("a", "10"), ("d", "1"), ("d", "2")]


def test_paired_cases_keep_all_four_outcome_categories():
    queries = [{"question_id": name, "question": name} for name in ("n", "h", "b", "x")]
    gold = {name: {("d", "g")} for name in ("n", "h", "b", "x")}
    found = [("d", "g")] + [("d", str(i)) for i in range(1, 10)]
    missed = [("d", str(i)) for i in range(1, 11)] + [("d", "g")]
    h0 = {"n": missed, "h": found, "b": found, "x": missed}
    node = {"n": found, "h": missed, "b": found, "x": missed}
    rows = hf._paired_cases(queries, gold, h0, node)
    assert {row["category"] for row in rows} == {
        "colnomic_incomplete_node_complete", "colnomic_complete_node_incomplete",
        "both_complete", "both_incomplete"}
    assert all(row["threshold"].startswith("complete distinct gold-page") for row in rows)


def _node(node_id, page, text):
    return {"id": node_id, "document": "d", "page": page,
            "eligible_members": [{"member_id": "m", "eligible": True}],
            "members": [{"id": "m", "text": text, "kind": "text"}]}


def test_h1_page_locator_exposes_only_preselected_node_without_gold():
    first, second = _node("n1", 1, "preferred original"), _node("n2", 1, "other original")
    packets, by_page, spans = hf._packets_for_pages(
        [("d", "1")], {("d", "1"): [first, second]}, {("d", "1"): first})
    assert len(packets) == 1
    packet = next(iter(packets.values()))
    assert packet["source_node_ids"] == ["n1"] and packet["text"] == "preferred original"
    assert len(json.loads(next(iter(by_page)))) == 2
    assert {span["packet_id"] for span in spans.values()} == set(packets)


def test_remapped_node_pages_must_cover_full_corpus_exactly():
    tasks = [{"question_id": "q", "node_ranking": ["n1", "n2"]}]
    nodes = {"n1": {"document": "d", "page": 1}, "n2": {"document": "d", "page": 2}}
    corpus = {("d", "1"), ("d", "2")}
    assert hf._node_rankings(tasks, nodes, corpus)["q"] == [("d", "1"), ("d", "2")]
