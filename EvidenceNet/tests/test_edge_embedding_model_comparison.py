import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_edge_embedding_models import evaluate, reference_levels


def test_six_case_overlay_replaces_old_ordinal_levels_without_changing_ids():
    cases = [
        {"suite_case_id": "P11", "A": {"node_id": "a"}, "B": {"node_id": "b"}},
        {"suite_case_id": "P10", "A": {"node_id": "a"}, "B": {"node_id": "c"}},
        {"suite_case_id": "N01", "A": {"node_id": "a"}, "B": {"node_id": "d"}},
        {"suite_case_id": "U01", "A": {"node_id": "b"}, "B": {"node_id": "d"}},
    ]
    references = [
        {"suite_case_id": "P11", "allowed_levels": [2]},
        {"suite_case_id": "P10", "allowed_levels": [2]},
        {"suite_case_id": "N01", "allowed_levels": [0, 1]},
        {"suite_case_id": "U01", "allowed_levels": [1, 2]},
    ]
    overlay = [
        {"suite_case_id": "P11", "relatedness": 1},
        {"suite_case_id": "P10", "relatedness": 2},
    ]
    assert reference_levels(cases, references, overlay) == {
        "P11": 1, "P10": 2, "N01": 0, "U01": None,
    }


def test_evaluation_separates_strong_weak_and_no_link_coverage():
    cases = [
        {"suite_case_id": "strong", "A": {"node_id": "a"}, "B": {"node_id": "b"}},
        {"suite_case_id": "weak", "A": {"node_id": "a"}, "B": {"node_id": "c"}},
        {"suite_case_id": "none", "A": {"node_id": "b"}, "B": {"node_id": "c"}},
    ]
    views = [{"node_id": value} for value in "abc"]
    vectors = np.eye(3, dtype=np.float32)
    candidates = [{"source": "a", "target": "b"}]
    pool = candidates + [{"source": "a", "target": "c"}]
    records, metrics = evaluate(cases, {"strong": 2, "weak": 1, "none": 0},
                                candidates, pool, views, vectors)
    assert len(records) == 3
    assert metrics["strong_relatedness_2"]["final_candidates"] == 1
    assert metrics["weak_relatedness_1"]["initial_pool"] == 1
    assert metrics["weak_relatedness_1"]["final_candidates"] == 0
    assert metrics["no_link_0"]["final_candidates"] == 0
