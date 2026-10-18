from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_edge_selector_reranker import alignment_ids, pair_key, routed_adaptive


def row(a, b, aa, bb, score):
    return {"source": a, "target": b, "source_article": aa, "target_article": bb,
            "reranker_logit": score}


def test_alignment_ids_deduplicate_reversed_view_matches():
    pair = {"best_views": {
        "dense_ab": {"source_view": "v1", "target_view": "v2"},
        "dense_ba": {"source_view": "v2", "target_view": "v1"},
        "bm25_ab": {"source_view": "v1", "target_view": "v3"},
    }}
    assert alignment_ids(pair) == [("v1", "v2"), ("v1", "v3")]


def test_routed_selector_escape_is_unique_and_off_route():
    scored = [
        row("a", "b", "A", "B", 10),
        row("a", "c", "A", "C", 9),
        row("d", "e", "D", "D", 8),
        row("f", "g", "A", "B", 7),
    ]
    selected = routed_adaptive(scored, {("A", "B")}, 4)
    assert len(selected) == len({pair_key(value) for value in selected}) == 4
    assert pair_key(scored[1]) in {pair_key(value) for value in selected}


def test_pair_key_is_orientation_independent():
    assert pair_key({"source": "z", "target": "a"}) == ("a", "z")
