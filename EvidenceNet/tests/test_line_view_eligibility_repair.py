from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from repair_line_view_eligibility import filter_cached_views, GENERATED


def fixture():
    nodes, policies, views = {}, {}, []
    for index, (kind, node_ok, member_ok) in enumerate([
        ("atom", True, True), ("visual", False, False),
        ("visual", True, True), ("atom", True, False),
        ("atom", False, True),
    ]):
        nid, vid = f"node{index}", f"VIEW_{index:06d}"
        text = f"source text {index}"
        nodes[nid] = {"members": [{"kind": kind, "id": "m", "text": text}]}
        policies[nid] = {"eligible": node_ok, "members": [
            {"kind": kind, "member_id": "m", "eligible": member_ok, "reason": "excluded" if not member_ok else None},
        ]}
        views.append({"view_id": vid, "node_id": nid, "member_id": "m", "member_kind": kind,
                      "char_start": 0, "char_end": len(text), "quote": text,
                      "retrieval_text": text, "source_status": "ORIGINAL_TEXT_LINE_STRUCTURE"})
    return views, np.arange(15, dtype=np.float32).reshape(5, 3), nodes, policies


def test_filter_preserves_ids_exact_rows_and_generated_provenance():
    views, vectors, nodes, policies = fixture()
    original = [dict(v) for v in views]
    kept, matrix, audit = filter_cached_views(views, vectors, nodes, policies, "line")
    assert [v["view_id"] for v in kept] == ["VIEW_000000", "VIEW_000002"]
    assert np.array_equal(matrix, vectors[[0, 2]])
    assert kept[0]["source_status"] == "ORIGINAL_TEXT_LINE_STRUCTURE"
    assert kept[1]["source_status"] == GENERATED
    assert views == original
    assert [a["original_vector_row"] for a in audit if a["kept"]] == [0, 2]
    assert sum(not a["kept"] for a in audit) == 3


def test_missing_member_policy_fails_closed():
    views, vectors, nodes, policies = fixture()
    policies["node0"]["members"] = []
    with pytest.raises(ValueError, match="Missing/ambiguous"):
        filter_cached_views(views, vectors, nodes, policies, "line")


def test_stale_vector_rows_and_source_offsets_are_rejected():
    views, vectors, nodes, policies = fixture()
    with pytest.raises(ValueError, match="row mismatch"):
        filter_cached_views(views, vectors[:-1], nodes, policies, "line")
    views[0]["quote"] = "wrong source"
    with pytest.raises(ValueError, match="offset/quote"):
        filter_cached_views(views, vectors, nodes, policies, "line")
