import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "d1", ROOT / "scripts/run_missing_requirement_retrieval_d1.py"
)
d1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d1)


def test_subquery_uses_question_and_evidence_without_identifiers():
    value = d1.make_missing_requirement_subquery(
        "Which result changed?", [{"node_id": "secret", "text": "The result changed in 2024."}]
    )
    assert "Which result changed?" in value
    assert "The result changed in 2024." in value
    assert "secret" not in value


def test_rank_excludes_d0_and_caps_budget():
    scores = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6}
    assert d1.rank(scores, {"a"}, 3) == ["b", "c", "d"]
    assert d1.rank(scores, {"a", "b"}, 1) == ["c"]


def test_aggregate_max_pools_views():
    views = [{"node_id": "a"}, {"node_id": "a"}, {"node_id": "b"}]
    scores = d1.aggregate_view_scores([0.2, 0.8, 0.5], views, {"a", "b"})
    assert scores == {"a": 0.8, "b": 0.5}
